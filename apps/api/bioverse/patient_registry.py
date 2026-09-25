"""The one place new patient records are created, so every path (admin, invite, self-registration, import)
gets the same duplicate check. Also: merging two records that turn out to be the same person.

register_patient(...) returns {"patient_id", "how", "message", ...}. `how` is one of:

    created                 no existing record looks like this person; a new record was created.
    linked                  a record without a sign-in is certainly this person (same identifier, or same name,
                            date of birth and email); the new sign-in was attached to it. No new record.
    matched_existing        as `linked`, but no sign-in was passed (e.g. an import): the existing record is
                            returned and the new identifiers/contact details were added to it. No new record.
    created_flagged         the person certainly matches a record that already has a DIFFERENT sign-in. A new
                            record was created (so sign-up is not blocked) and an urgent review was queued.
                            We never attach a second login to someone else's record silently.
    created_pending_review  probable or possible duplicates: a new record was created and review items queued.

Matching rules and thresholds: bioverse.patient_match.
"""

from __future__ import annotations

import json
import re
from datetime import date
from types import SimpleNamespace
from urllib.parse import urlparse

from psycopg import Connection, errors, sql

from bioverse import audit
from bioverse.patient_match import Match, Person, find_candidates, norm_email

MESSAGES = {
    "created": "New patient record created.",
    "linked": "Linked to an existing patient record (same person already on file).",
    "matched_existing": "This person is already on file; the existing record was used.",
    "created_flagged": "Created, but this looks like a patient who already has a sign-in. Flagged for urgent review.",
    "created_pending_review": "Created. A possible duplicate record was queued for review.",
}

# Tables whose patient reference is NOT moved by a merge. audit_events is append-only history; match_reviews
# is updated by the merge itself; patients.merged_into is re-pointed explicitly.
MERGE_SKIP = {("audit_events", "patient_id"), ("patients", "merged_into")}
MERGE_SKIP_TABLES = {"match_reviews"}


class MergeRefused(Exception):
    """A merge that must not happen (reason is safe to show)."""


# --- Identifiers ------------------------------------------------------------------------------------


def authority_for(conn: Connection, system: str) -> str:
    """HL7 v2 assigning authority for an identifier system: the one already used with that system, else derived
    from the system (never 'BIOVERSE', which lab import reserves for Bioverse patient ids)."""
    row = conn.execute("SELECT hl7_authority FROM patient_identifiers WHERE system = %s LIMIT 1", (system,)).fetchone()
    if row:
        return row["hl7_authority"]
    if system.startswith("urn:oid:"):
        raw = system[8:]
    elif "://" in system:
        u = urlparse(system)
        host = (u.hostname or "").split(".")[0]
        last = u.path.rstrip("/").rsplit("/", 1)[-1]
        raw = f"{host}-{last}" if last else host
    else:
        raw = system
    code = re.sub(r"[^A-Z0-9.]+", "-", raw.upper()).strip("-")[:40] or "EXTERNAL"
    return "BIOVERSE-EXT" if code == "BIOVERSE" else code


def attach_identifiers(conn: Connection, patient_id: str, identifiers: list[dict] | None) -> dict:
    """Add identifiers to a record. One that already belongs to another record is skipped (never stolen)."""
    added, skipped = [], []
    for ident in identifiers or []:
        system, value = (ident.get("system") or "").strip(), (ident.get("value") or "").strip()
        if not system or not value:
            continue
        authority = ident.get("hl7_authority") or ident.get("authority") or authority_for(conn, system)
        type_code = ident.get("type_code") or ident.get("type") or "MR"
        row = conn.execute(
            """
            INSERT INTO patient_identifiers (patient_id, system, hl7_authority, value, type_code)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id
            """,
            (patient_id, system, authority, value, type_code),
        ).fetchone()
        if row:
            added.append({"system": system, "value": value})
            continue
        mine = conn.execute(
            "SELECT 1 FROM patient_identifiers WHERE patient_id = %s AND system = %s AND value = %s",
            (patient_id, system, value),
        ).fetchone()
        if not mine:
            skipped.append({"system": system, "value": value, "reason": "already belongs to another record"})
    return {"added": added, "skipped": skipped}


# --- Registration -----------------------------------------------------------------------------------


def _actor(conn: Connection, actor_id: str | None):
    if not actor_id:
        return None
    row = conn.execute("SELECT id::text, role FROM users WHERE id = %s", (actor_id,)).fetchone()
    return SimpleNamespace(id=row["id"], role=row["role"]) if row else None


def queue_review(conn: Connection, *, organization_id: str, existing_id: str, new_id: str, match: Match,
                 source: str, level: str | None = None) -> str | None:
    """Open a review for the pair unless one is already open. Returns the review id (new or existing)."""
    row = conn.execute(
        """
        INSERT INTO match_reviews (organization_id, patient_a, patient_b, level, score, reasons, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id::text
        """,
        (organization_id, existing_id, new_id, level or match.level, match.score, json.dumps(match.reasons), source),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        """
        SELECT id::text FROM match_reviews WHERE status = 'open'
          AND LEAST(patient_a, patient_b) = LEAST(%s::uuid, %s::uuid)
          AND GREATEST(patient_a, patient_b) = GREATEST(%s::uuid, %s::uuid)
        """,
        (existing_id, new_id, existing_id, new_id),
    ).fetchone()
    return row["id"] if row else None


def _insert(conn: Connection, *, organization_id, user_id, name, birth_date, email, phone, sex_at_birth) -> str:
    return conn.execute(
        """
        INSERT INTO patients (user_id, organization_id, name, birth_date, email, phone, sex_at_birth)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (user_id, organization_id, name, birth_date, email, phone, sex_at_birth),
    ).fetchone()["id"]


def register_patient(conn: Connection, *, organization_id: str, user_id: str | None, name: str, birth_date: date,
                     email: str | None = None, phone: str | None = None,
                     identifiers: list[dict] | None = None, source: str = "admin", actor_id: str | None = None,
                     sex_at_birth: str | None = None, auto_link: bool = True) -> dict:
    """Find-or-create the patient record for a person. See the module docstring for the `how` values.

    identifiers: [{"system": ..., "value": ...}] such as a medical record number from an invite
    (optional "hl7_authority" and "type_code"; the authority is derived from the system otherwise).
    auto_link=False never attaches to an existing record: a certain match is queued for review instead.
    """
    email = norm_email(email)
    phone = (phone or "").strip() or None
    person = Person(name=name, birth_date=birth_date, email=email, phone=phone, sex=sex_at_birth,
                    identifiers=identifiers or [])
    candidates = find_candidates(conn, organization_id, person)
    certain = [c for c in candidates if c.level == "certain"]
    actor = _actor(conn, actor_id) or (_actor(conn, user_id) if source == "self" else None)
    top = candidates[0] if candidates else None

    # Exactly one certain match: use it, unless it belongs to someone else's sign-in.
    if auto_link and len(certain) == 1:
        match = certain[0]
        existing_user = match.record.get("user_id")
        if existing_user is None or user_id is None or existing_user == user_id:
            how = "matched_existing"
            if user_id and existing_user is None:
                linked = conn.execute(
                    "UPDATE patients SET user_id = %s WHERE id = %s AND user_id IS NULL AND merged_into IS NULL "
                    "RETURNING id", (user_id, match.patient_id),
                ).fetchone()
                how = "linked" if linked else None
            if how:
                conn.execute(
                    """
                    UPDATE patients SET email = COALESCE(email, %s), phone = COALESCE(phone, %s),
                                        sex_at_birth = COALESCE(sex_at_birth, %s)
                    WHERE id = %s
                    """,
                    (email, phone, sex_at_birth, match.patient_id),
                )
                idents = attach_identifiers(conn, match.patient_id, identifiers)
                audit.record(conn, action=f"patient_match.{how}", entity_type="patient", entity_id=match.patient_id,
                             actor=actor, patient_id=match.patient_id,
                             detail={"source": source, "score": match.score,
                                     "reasons": [r["code"] for r in match.reasons]})
                return {"patient_id": match.patient_id, "how": how, "message": MESSAGES[how],
                        "matched_patient_id": match.patient_id, "match": {"level": match.level, "score": match.score},
                        "review_ids": [], "identifiers": idents}

    patient_id = _insert(conn, organization_id=organization_id, user_id=user_id, name=name, birth_date=birth_date,
                         email=email, phone=phone, sex_at_birth=sex_at_birth)
    idents = attach_identifiers(conn, patient_id, identifiers)
    if not candidates:
        return {"patient_id": patient_id, "how": "created", "message": MESSAGES["created"], "review_ids": [],
                "identifiers": idents}

    flagged = bool(certain) and len(certain) == 1 and auto_link
    how = "created_flagged" if flagged else "created_pending_review"
    review_ids = []
    for c in candidates[:5]:
        rid = queue_review(conn, organization_id=organization_id, existing_id=c.patient_id, new_id=patient_id,
                           match=c, source=source)
        if rid:
            review_ids.append(rid)
    audit.record(conn, action="patient_match.review_queued", entity_type="patient", entity_id=patient_id,
                 actor=actor, patient_id=patient_id,
                 detail={"source": source, "how": how, "reviews": len(review_ids), "top_level": top.level,
                         "top_score": top.score})
    out = {"patient_id": patient_id, "how": how, "message": MESSAGES[how], "review_ids": review_ids,
           "match": {"level": top.level, "score": top.score}, "identifiers": idents}
    if flagged:
        out["matched_patient_id"] = top.patient_id
    return out


# --- Merge ------------------------------------------------------------------------------------------


def patient_references(conn: Connection) -> list[dict]:
    """Every single-column foreign key to patients(id), discovered from the catalog (new modules included)."""
    rows = conn.execute(
        """
        SELECT n.nspname AS schema, cl.relname AS tbl, a.attname AS col, array_length(c.conkey, 1) AS width
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.confrelid = 'patients'::regclass
        ORDER BY cl.relname, a.attname
        """
    ).fetchall()
    return [r for r in rows if (r["tbl"], r["col"]) not in MERGE_SKIP and r["tbl"] not in MERGE_SKIP_TABLES]


def record_counts(conn: Connection, patient_id: str) -> dict[str, int]:
    """How many rows in each module point at this record (non-zero only). One query."""
    refs = [r for r in patient_references(conn) if r["width"] == 1]
    if not refs:
        return {}
    parts = [
        sql.SQL("SELECT {label} AS t, count(*) AS n FROM {tbl} WHERE {col} = %(p)s").format(
            label=sql.Literal(r["tbl"]), tbl=sql.Identifier(r["schema"], r["tbl"]), col=sql.Identifier(r["col"]))
        for r in refs
    ]
    rows = conn.execute(sql.SQL(" UNION ALL ").join(parts), {"p": patient_id}).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        if r["n"]:
            counts[r["t"]] = counts.get(r["t"], 0) + r["n"]
    return counts


def _move_rows(conn: Connection, ref: dict, survivor: str, retired: str) -> tuple[int, int]:
    """(moved, kept on the retired record). Conflicts with a row the survivor already has stay behind."""
    tbl, col = sql.Identifier(ref["schema"], ref["tbl"]), sql.Identifier(ref["col"])
    try:
        with conn.transaction():
            cur = conn.execute(sql.SQL("UPDATE {} SET {} = %s WHERE {} = %s").format(tbl, col, col), (survivor, retired))
            return cur.rowcount, 0
    except (errors.UniqueViolation, errors.ExclusionViolation):
        pass
    moved = kept = 0
    ctids = conn.execute(sql.SQL("SELECT ctid::text AS ctid FROM {} WHERE {} = %s").format(tbl, col), (retired,)).fetchall()
    for r in ctids:
        try:
            with conn.transaction():
                conn.execute(sql.SQL("UPDATE {} SET {} = %s WHERE ctid = %s::tid").format(tbl, col), (survivor, r["ctid"]))
                moved += 1
        except (errors.UniqueViolation, errors.ExclusionViolation):
            kept += 1
    return moved, kept


def merge_patients(conn: Connection, *, survivor_id: str, retired_id: str, organization_id: str, actor,
                   review_id: str | None = None) -> dict:
    """Move everything from the retired record to the survivor; keep the retired row with merged_into.

    Refuses (MergeRefused) when the records are in another organization, already merged, or both have an
    active sign-in. Runs in a savepoint: any unexpected error leaves both records untouched.
    """
    if survivor_id == retired_id:
        raise MergeRefused("Pick two different records.")
    with conn.transaction():
        rows = {r["id"]: r for r in conn.execute(
            """
            SELECT p.id::text, p.organization_id::text, p.user_id::text, p.merged_into, u.disabled AS login_disabled
            FROM patients p LEFT JOIN users u ON u.id = p.user_id
            WHERE p.id = ANY(%s::uuid[]) ORDER BY p.id FOR UPDATE OF p
            """,
            ([survivor_id, retired_id],),
        ).fetchall()}
        s, r = rows.get(survivor_id), rows.get(retired_id)
        if not s or not r or s["organization_id"] != organization_id or r["organization_id"] != organization_id:
            raise MergeRefused("Patient record not found.")
        if s["merged_into"] or r["merged_into"]:
            raise MergeRefused("One of these records has already been merged.")
        login_moved = False
        if s["user_id"] and r["user_id"]:
            if not r["login_disabled"]:
                raise MergeRefused(
                    "Both records have their own sign-in, so they can't be merged automatically. Disable the "
                    "extra account in People & sign-in first; its sign-in is then not carried over.")
            conn.execute("UPDATE patients SET user_id = NULL WHERE id = %s", (retired_id,))
        elif r["user_id"]:
            conn.execute("UPDATE patients SET user_id = NULL WHERE id = %s", (retired_id,))
            conn.execute("UPDATE patients SET user_id = %s WHERE id = %s", (r["user_id"], survivor_id))
            login_moved = True

        # Fill gaps on the survivor from the retired record; never overwrite what the survivor has.
        conn.execute(
            """
            UPDATE patients s SET email = COALESCE(s.email, r.email), phone = COALESCE(s.phone, r.phone),
                   sex_at_birth = COALESCE(s.sex_at_birth, r.sex_at_birth), pronouns = COALESCE(s.pronouns, r.pronouns),
                   insurance_plan = COALESCE(s.insurance_plan, r.insurance_plan),
                   allergies = ARRAY(SELECT DISTINCT unnest(s.allergies || r.allergies) ORDER BY 1)
            FROM patients r WHERE s.id = %s AND r.id = %s
            """,
            (survivor_id, retired_id),
        )

        moved: dict[str, int] = {}
        kept: dict[str, int] = {}
        not_moved: list[str] = []
        for ref in patient_references(conn):
            key = ref["tbl"] if ref["col"] == "patient_id" else f"{ref['tbl']}.{ref['col']}"
            if ref["width"] != 1:
                not_moved.append(key)
                continue
            m, k = _move_rows(conn, ref, survivor_id, retired_id)
            if m:
                moved[key] = m
            if k:
                kept[key] = k

        conn.execute("UPDATE patients SET merged_into = %s WHERE merged_into = %s", (survivor_id, retired_id))
        conn.execute("UPDATE patients SET merged_into = %s, merged_at = now() WHERE id = %s", (survivor_id, retired_id))

        # Other open reviews that involve the retired record now concern the survivor.
        others = conn.execute(
            "SELECT id::text, patient_a::text, patient_b::text FROM match_reviews "
            "WHERE status = 'open' AND (patient_a = %s OR patient_b = %s) AND id::text IS DISTINCT FROM %s",
            (retired_id, retired_id, review_id),
        ).fetchall()
        for o in others:
            a = survivor_id if o["patient_a"] == retired_id else o["patient_a"]
            b = survivor_id if o["patient_b"] == retired_id else o["patient_b"]
            superseded = a == b
            if not superseded:
                try:
                    with conn.transaction():
                        conn.execute("UPDATE match_reviews SET patient_a = %s, patient_b = %s WHERE id = %s", (a, b, o["id"]))
                except errors.UniqueViolation:
                    superseded = True
            if superseded:
                conn.execute(
                    "UPDATE match_reviews SET status = 'merged', survivor = %s, decided_by = %s, decided_at = now(), "
                    "merge_report = %s WHERE id = %s",
                    (survivor_id, actor.id if actor else None, json.dumps({"superseded_by_merge": True}), o["id"]),
                )

    report = {"survivor": survivor_id, "retired": retired_id, "moved": moved, "kept_on_retired": kept,
              "not_moved": not_moved, "login_moved": login_moved,
              "total_moved": sum(moved.values()), "total_kept": sum(kept.values())}
    audit.record(conn, action="patient_match.merge", entity_type="patient", entity_id=survivor_id, actor=actor,
                 patient_id=survivor_id,
                 detail={"retired": retired_id, "total_moved": report["total_moved"], "total_kept": report["total_kept"],
                         "tables": sorted(moved), "login_moved": login_moved})
    audit.record(conn, action="patient_match.retired", entity_type="patient", entity_id=retired_id, actor=actor,
                 patient_id=retired_id, detail={"merged_into": survivor_id})
    return report
