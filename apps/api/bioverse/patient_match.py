"""Patient matching for the master patient index: is this person already on file?

Two layers, always within one organization:

- **Deterministic.** The same identifier (system + value, e.g. an MRN) is the same person, unless the date of
  birth or family name contradicts it.
- **Scored.** Points for name (normalized for case, accents and punctuation; first/last swap; a small nickname
  table; Jaro-Winkler for typos), date of birth (exact, or day and month swapped), email, phone and sex at
  birth. Evidence against (a different date of birth, a different sex) subtracts. A phone number adds points but
  never makes a match certain: it is unverified and shared within households, and a certain match attaches a
  new sign-in to an existing clinical record.

Levels, and what registration does with them (bioverse.patient_registry):

    certain   identifier match, or exact name + exact date of birth + same email             -> link / flag
    probable  score >= PROBABLE (e.g. exact name + date of birth; a typo or nickname + date of birth)  -> review
    possible  score >= POSSIBLE (e.g. exact name with day/month swapped)                   -> review
    none      below that                                                                     -> just create

Every candidate carries its reasons (for the review screen). Candidates are pre-filtered in SQL by date of
birth, email, phone or identifier, never by scanning the organization.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import Connection

PROBABLE = 65
POSSIBLE = 45

LEVEL_ORDER = {"certain": 3, "probable": 2, "possible": 1, "none": 0}

# Each line is one name and the short forms people register with. Two names match when they share a line.
NICKNAME_GROUPS = [
    "william bill billy will willy liam",
    "robert bob bobby rob robbie bert",
    "elizabeth liz lizzie beth betty eliza libby",
    "margaret maggie meg peggy marge",
    "richard rick ricky dick rich richie",
    "james jim jimmy jamie",
    "john jack johnny jon",
    "jonathan jon jonny",
    "michael mike mikey mick",
    "katherine catherine kathryn kate katie kathy cathy kat",
    "thomas tomas tom tommy",
    "joseph joe joey",
    "charles charlie chuck",
    "christopher chris",
    "christine christina chris tina",
    "alexander alex sasha xander",
    "alexandra alex sasha lexi",
    "daniel dan danny",
    "david dave davy",
    "edward ed eddie ted ned",
    "patricia pat patty trish",
    "jennifer jen jenny",
    "susan sue suzy",
    "deborah debra deb debbie",
    "rebecca becky becca",
    "anthony tony",
    "andrew andy drew",
    "matthew matt",
    "nicholas nick nicky",
    "benjamin ben benny",
    "samuel sam sammy",
    "samantha sam sammy",
    "steven stephen steve",
    "eleanor ellie nell nora",
    "victoria vicky tori",
    "abigail abby",
    "gregory greg",
    "timothy tim timmy",
    "jose pepe",
    "francisco paco pancho",
    "alejandro alex",
]
_NICK: dict[str, set[int]] = {}
for _i, _line in enumerate(NICKNAME_GROUPS):
    for _n in _line.split():
        _NICK.setdefault(_n, set()).add(_i)

_DROP = {"mr", "mrs", "ms", "miss", "mx", "dr", "jr", "sr", "ii", "iii", "iv"}


# --- Normalization ---------------------------------------------------------------------------------


def fold(s: str | None) -> str:
    """Lowercase, accents removed, apostrophes and periods dropped, other punctuation to spaces."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"['’.]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def name_parts(full: str | None) -> tuple[str, str, list[str]]:
    """(given, family, all tokens). "Family, Given" order is understood."""
    raw = full or ""
    if "," in raw:
        family, _, given = raw.partition(",")
        raw = f"{given} {family}"
    tokens = [t for t in fold(raw).split() if t not in _DROP]
    if not tokens:
        return "", "", []
    if len(tokens) == 1:
        return tokens[0], "", tokens
    return tokens[0], tokens[-1], tokens


def norm_email(email: str | None) -> str | None:
    e = (email or "").strip().lower()
    return e or None


def norm_phone(phone: str | None) -> str | None:
    """The last 10 digits (drops country code and punctuation). Fewer than 7 digits is not a phone number."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 7 else None


def transposed(d: date | None) -> date | None:
    """The same date with day and month swapped, when that is a different valid date."""
    if d is None or d.day > 12 or d.day == d.month:
        return None
    try:
        return d.replace(month=d.day, day=d.month)
    except ValueError:
        return None


def jaro_winkler(a: str, b: str, prefix_scale: float = 0.1) -> float:
    if a == b:
        return 1.0 if a else 0.0
    if not a or not b:
        return 0.0
    window = max(max(len(a), len(b)) // 2 - 1, 0)
    a_hit = [False] * len(a)
    b_hit = [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    a_m = [ch for ch, hit in zip(a, a_hit) if hit]
    b_m = [ch for ch, hit in zip(b, b_hit) if hit]
    transpositions = sum(x != y for x, y in zip(a_m, b_m)) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)


def one_edit_apart(a: str, b: str) -> bool:
    """One inserted, deleted, replaced or swapped-adjacent letter (a typo)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((k for k, (x, y) in enumerate(zip(short, long_)) if x != y), len(short))
    return short[i:] == long_[i + 1:]


def _typo(a: str, b: str) -> bool:
    return min(len(a), len(b)) >= 4 and one_edit_apart(a, b)


def nicknames_match(a: str, b: str) -> bool:
    return a != b and bool(_NICK.get(a, set()) & _NICK.get(b, set()))


# --- Scoring ---------------------------------------------------------------------------------------


@dataclass
class Person:
    """The demographics being compared: a registration, a search, or a stored record."""
    name: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone: str | None = None
    sex: str | None = None
    identifiers: list[dict] = field(default_factory=list)


@dataclass
class Match:
    patient_id: str
    level: str
    score: int
    reasons: list[dict]
    record: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"patient_id": self.patient_id, "level": self.level, "score": self.score, "reasons": self.reasons}


def _reason(code: str, label: str, points: int, kind: str = "match") -> dict:
    return {"code": code, "label": label, "points": points, "kind": kind}


def _given_points(a: str, b: str) -> tuple[int, str | None]:
    if not a or not b:
        return 0, None
    if a == b:
        return 20, "exact"
    if nicknames_match(a, b):
        return 17, "nickname"
    sim = jaro_winkler(a, b)
    if sim >= 0.92 or _typo(a, b):
        return 16, "close"
    if sim >= 0.85:
        return 10, "similar"
    if (len(a) == 1 or len(b) == 1) and a[0] == b[0]:
        return 8, "initial"
    return 0, None


def _family_points(a: str, b: str, a_tokens: list[str], b_tokens: list[str]) -> tuple[int, str | None]:
    if not a or not b:
        return 0, None
    if a == b:
        return 20, "exact"
    # Compound surnames: "Garcia Lopez" and "Garcia" share a family name.
    if a in b_tokens[1:] or b in a_tokens[1:]:
        return 16, "compound"
    sim = jaro_winkler(a, b)
    if sim >= 0.92 or _typo(a, b):
        return 16, "close"
    if sim >= 0.85:
        return 10, "similar"
    return 0, None


def compare_names(a: str | None, b: str | None) -> tuple[int, list[dict], bool]:
    """(points out of 40, reasons, exact). Exact means same first and last name, in either order."""
    ga, fa, ta = name_parts(a)
    gb, fb, tb = name_parts(b)
    if not ta or not tb:
        return 0, [], False
    options = []
    for swapped, (g2, f2) in ((False, (gb, fb)), (True, (fb, gb))):
        gp, gk = _given_points(ga, g2)
        fp, fk = _family_points(fa, f2, ta, tb)
        total = gp + fp - (2 if swapped else 0)
        options.append((total, swapped, gp, gk, fp, fk, g2))
    total, swapped, gp, gk, fp, fk, g2 = max(options, key=lambda o: o[0])
    exact = gk == "exact" and fk == "exact"
    reasons: list[dict] = []
    if total <= 0:
        reasons.append(_reason("name_differs", "Names are different", 0, "conflict"))
        return 0, reasons, False
    if exact:
        label = "Same first and last name" + (" (entered in the opposite order)" if swapped else "")
        reasons.append(_reason("name_exact" if not swapped else "name_swapped", label, total))
        return max(total, 0), reasons, True
    given_label = {
        "exact": "same first name",
        "nickname": f"first names are the same name ({ga.title()} / {g2.title()})",
        "close": "first names differ by a typo",
        "similar": "first names are similar",
        "initial": "first name matches an initial",
        None: "first names differ",
    }[gk]
    family_label = {
        "exact": "same last name",
        "compound": "one last name is part of the other",
        "close": "last names differ by a typo",
        "similar": "last names are similar",
        None: "last names differ",
    }[fk]
    label = f"{given_label[0].upper()}{given_label[1:]}; {family_label}" + (" (first and last swapped)" if swapped else "")
    code = "name_nickname" if gk == "nickname" else "name_similar"
    reasons.append(_reason(code, label, total, "match" if total >= 26 else "partial"))
    return total, reasons, False


def compare_dob(a: date | None, b: date | None) -> tuple[int, list[dict], bool]:
    if a is None or b is None:
        return 0, [], False
    if a == b:
        return 30, [_reason("dob_exact", "Same date of birth", 30)], True
    if transposed(a) == b:
        return 15, [_reason("dob_transposed", "Date of birth with day and month swapped", 15, "partial")], False
    if a.month == b.month and a.day == b.day and abs(a.year - b.year) <= 10 and \
            sum(x != y for x, y in zip(str(a.year), str(b.year))) == 1:
        return 10, [_reason("dob_year_typo", "Same birthday; birth year differs by one digit", 10, "partial")], False
    return -10, [_reason("dob_differs", "Different date of birth", -10, "conflict")], False


def score(new: Person, existing: Person) -> tuple[int, str, list[dict]]:
    """(score 0-100, level, reasons) for two people. Identifiers are handled by the caller."""
    name_pts, reasons, name_exact = compare_names(new.name, existing.name)
    dob_pts, dob_reasons, dob_exact = compare_dob(new.birth_date, existing.birth_date)
    reasons += dob_reasons
    total = name_pts + dob_pts
    # Email can make a match certain (sign-in and invite emails are verified). Phone numbers are shared within
    # households and never verified, so they add points but never make a match certain on their own.
    same_email = False
    ea, eb = norm_email(new.email), norm_email(existing.email)
    if ea and eb and ea == eb:
        total += 15
        same_email = True
        reasons.append(_reason("email", "Same email address", 15))
    pa, pb = norm_phone(new.phone), norm_phone(existing.phone)
    if pa and pb and pa == pb:
        total += 10
        reasons.append(_reason("phone", "Same phone number", 10))
    sex_conflict = False
    sa, sb = (new.sex or "").lower(), (existing.sex or "").lower()
    if sa and sb and "unknown" not in (sa, sb):
        if sa == sb:
            total += 3
            reasons.append(_reason("sex", "Same sex at birth", 3))
        else:
            total -= 20
            sex_conflict = True
            reasons.append(_reason("sex_differs", "Different sex at birth", -20, "conflict"))
    total = max(0, min(100, total))
    if name_exact and dob_exact and same_email and not sex_conflict:
        return max(total, 90), "certain", reasons
    if total >= PROBABLE:
        return total, "probable", reasons
    if total >= POSSIBLE:
        return total, "possible", reasons
    return total, "none", reasons


# --- Candidates from the database ------------------------------------------------------------------

_RECORD_SQL = """
    SELECT p.id::text, p.name, p.birth_date, p.sex_at_birth, p.user_id::text, p.created_at,
           COALESCE(p.email, u.email) AS email, p.phone
    FROM patients p LEFT JOIN users u ON u.id = p.user_id
"""


def _person(row: dict) -> Person:
    return Person(name=row["name"], birth_date=row["birth_date"], email=row["email"], phone=row["phone"],
                  sex=row["sex_at_birth"])


def identifier_hits(conn: Connection, organization_id: str, identifiers: list[dict]) -> dict[str, list[dict]]:
    """patient_id -> the given identifiers already on that patient (system + value, exact)."""
    pairs = [(i.get("system"), i.get("value")) for i in identifiers or [] if i.get("system") and i.get("value")]
    if not pairs:
        return {}
    hits: dict[str, list[dict]] = {}
    for system, value in pairs:
        rows = conn.execute(
            """
            SELECT COALESCE(p.merged_into, p.id)::text AS patient_id FROM patient_identifiers pi
            JOIN patients p ON p.id = pi.patient_id
            WHERE pi.system = %s AND pi.value = %s AND p.organization_id = %s
            """,
            (system, value, organization_id),
        ).fetchall()
        for r in rows:
            hits.setdefault(r["patient_id"], []).append({"system": system, "value": value})
    return hits


def find_candidates(conn: Connection, organization_id: str, new: Person, *, exclude: list[str] | None = None,
                    include_none: bool = False, limit: int = 25) -> list[Match]:
    """Records in the organization that may be `new`, best first. Only unmerged records are considered."""
    ids = identifier_hits(conn, organization_id, new.identifiers)
    dobs = [d for d in (new.birth_date, transposed(new.birth_date)) if d]
    email = norm_email(new.email)
    phone = norm_phone(new.phone)
    parts = []
    params: dict[str, Any] = {"org": organization_id}
    if dobs:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s AND merged_into IS NULL "
                     "AND birth_date = ANY(%(dobs)s)")
        params["dobs"] = dobs
    if email:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s AND lower(email) = %(email)s")
        parts.append("SELECT p.id FROM users u JOIN patients p ON p.user_id = u.id "
                     "WHERE lower(u.email) = %(email)s AND p.organization_id = %(org)s")
        params["email"] = email
    if phone:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s "
                     "AND right(regexp_replace(phone, '\\D', '', 'g'), 10) = %(phone)s")
        params["phone"] = phone
    if ids:
        parts.append("SELECT id FROM patients WHERE id = ANY(%(ids)s::uuid[])")
        params["ids"] = list(ids)
    if not parts:
        return []
    params["exclude"] = exclude or []
    rows = conn.execute(
        _RECORD_SQL + " WHERE p.id IN (" + " UNION ".join(parts) + ") AND p.merged_into IS NULL "
        "AND p.organization_id = %(org)s AND NOT (p.id::text = ANY(%(exclude)s)) LIMIT 500",
        params,
    ).fetchall()
    return rank(new, rows, ids, include_none=include_none, limit=limit)


def rank(new: Person, rows: list[dict], ids: dict[str, list[dict]] | None = None, *,
         include_none: bool = False, limit: int = 25) -> list[Match]:
    ids = ids or {}
    out: list[Match] = []
    for row in rows:
        pts, level, reasons = score(new, _person(row))
        hit = ids.get(row["id"])
        if hit:
            label = "Same identifier (" + ", ".join(h["value"] for h in hit) + ")"
            dob_conflict = any(r["code"] == "dob_differs" for r in reasons)
            name_conflict = any(r["code"] == "name_differs" for r in reasons)
            if dob_conflict or name_conflict:
                reasons.insert(0, _reason("identifier_conflict", label + ", but the demographics disagree", 0, "conflict"))
                level, pts = "probable", max(pts, PROBABLE)
            else:
                reasons.insert(0, _reason("identifier", label, 100))
                level, pts = "certain", 100
        if level == "none" and not include_none:
            continue
        out.append(Match(patient_id=row["id"], level=level, score=pts, reasons=reasons, record=row))
    out.sort(key=lambda m: (LEVEL_ORDER[m.level], m.score), reverse=True)
    return out[:limit]


def search(conn: Connection, organization_id: str, *, name: str | None = None, birth_date: date | None = None,
           identifier: str | None = None, email: str | None = None, phone: str | None = None,
           limit: int = 20) -> list[Match]:
    """Front-desk lookup: find existing records by any mix of name, date of birth, identifier, email, phone.

    Each result's `level` is how well it fits what was searched for (identifier / strong / partial / weak) and
    `score` the percentage of the searched details that match; these are not duplicate levels."""
    params: dict[str, Any] = {"org": organization_id}
    parts = []
    given, family, tokens = name_parts(name)
    if birth_date:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s AND birth_date = ANY(%(dobs)s)")
        params["dobs"] = [d for d in (birth_date, transposed(birth_date)) if d]
    if tokens:
        # Substring match on any name part (at least 2 characters), then scored. Folded to ASCII on both sides
        # is not possible in plain SQL without the unaccent extension, so accents in stored names can hide a
        # hit here; date of birth, identifier, email or phone still find them.
        likes = [t for t in {given, family} if len(t) >= 2]
        for k, t in enumerate(likes):
            parts.append(f"SELECT id FROM patients WHERE organization_id = %(org)s AND lower(name) LIKE %(n{k})s")
            params[f"n{k}"] = f"%{t}%"
    if identifier and identifier.strip():
        parts.append("SELECT pi.patient_id FROM patient_identifiers pi JOIN patients p ON p.id = pi.patient_id "
                     "WHERE p.organization_id = %(org)s AND (pi.value = %(ident)s OR p.id::text = %(ident)s)")
        params["ident"] = identifier.strip()
    e = norm_email(email)
    if e:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s AND lower(email) = %(email)s")
        parts.append("SELECT p.id FROM users u JOIN patients p ON p.user_id = u.id "
                     "WHERE lower(u.email) = %(email)s AND p.organization_id = %(org)s")
        params["email"] = e
    ph = norm_phone(phone)
    if ph:
        parts.append("SELECT id FROM patients WHERE organization_id = %(org)s "
                     "AND right(regexp_replace(phone, '\\D', '', 'g'), 10) = %(phone)s")
        params["phone"] = ph
    if not parts:
        return []
    rows = conn.execute(
        _RECORD_SQL + " WHERE p.id IN (" + " UNION ".join(parts) + ") AND p.merged_into IS NULL "
        "AND p.organization_id = %(org)s LIMIT 500",
        params,
    ).fetchall()
    probe = Person(name=name, birth_date=birth_date, email=email, phone=phone)
    ident_rows = set()
    if identifier and identifier.strip():
        ident_rows = {r["patient_id"] for r in conn.execute(
            "SELECT pi.patient_id::text FROM patient_identifiers pi JOIN patients p ON p.id = pi.patient_id "
            "WHERE p.organization_id = %s AND pi.value = %s", (organization_id, identifier.strip())).fetchall()}
        ident_rows |= {r["id"] for r in rows if r["id"] == identifier.strip()}
    # How much of what was searched for matches: a name-only search that matches the name exactly is a full fit.
    possible_pts = (40 if tokens else 0) + (30 if birth_date else 0) + (15 if e else 0) + (10 if ph else 0)
    out = []
    for row in rows:
        pts, _, reasons = score(probe, _person(row))
        fit = round(100 * pts / possible_pts) if possible_pts else 0
        level = "strong" if fit >= 90 else "partial" if fit >= 55 else "weak"
        if row["id"] in ident_rows:
            reasons.insert(0, _reason("identifier", "Identifier matches", 100))
            fit, level = 100, "identifier"
        out.append(Match(patient_id=row["id"], level=level, score=min(fit, 100), reasons=reasons, record=row))
    rank_of = {"identifier": 3, "strong": 2, "partial": 1, "weak": 0}
    out.sort(key=lambda m: (-rank_of[m.level], -m.score, m.record["name"]))
    return out[:limit]
