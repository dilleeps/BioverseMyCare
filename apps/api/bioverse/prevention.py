"""Preventive care rules: which screenings and vaccines are due, from the patient's own record.

ILLUSTRATIVE RULESET. NOT CLINICAL ADVICE. The rules below are simplified from public
guidance (USPSTF, CDC ACIP, ACC/AHA) so the demo has something realistic to evaluate. In
production this ruleset is clinician-owned, versioned, localized per jurisdiction, and released
only after sign-off against a labelled test set, exactly like the red-flag rules.

`evaluate()` is a pure function of a `Record` and a date, so every rule is testable with known
ages and dates. `load_record()` reads the database; `sync_gaps()` writes results to `care_gaps`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from psycopg import Connection

from bioverse import audit
from bioverse.auth import User

RULESET_VERSION = "prevention-2026.09-illustrative"
DISCLAIMER = (
    "This checklist uses a simplified, illustrative ruleset. It is not medical advice. "
    "Your clinician decides what is right for you."
)
# A due date this close counts as "due" rather than "up to date".
DUE_SOON_DAYS = 30


# --- Record ------------------------------------------------------------------------------------


@dataclass
class Record:
    birth_date: date
    sex: str | None = None  # 'female' | 'male' | 'intersex' | 'unknown' | None
    immunizations: list[dict[str, Any]] = field(default_factory=list)  # id, vaccine, occurred_at
    reports: list[dict[str, Any]] = field(default_factory=list)        # id, name, collected_at
    observations: list[dict[str, Any]] = field(default_factory=list)   # id, report_id, loinc_code, display, value, interpretation, effective_at
    encounters: list[dict[str, Any]] = field(default_factory=list)     # id, kind, summary, occurred_at


@dataclass(frozen=True)
class Evidence:
    on: date
    source_type: str
    source_id: str
    label: str
    tag: str = ""  # what kind of test it was, when the interval depends on it


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def age_on(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, min(d.day, day))
        except ValueError:
            continue
    raise ValueError("unreachable")


# --- Evidence finders ----------------------------------------------------------------------------

_BP_TEXT = re.compile(r"\bBP\s*(\d{2,3})\s*/\s*(\d{2,3})|\bblood pressure\b", re.I)
_BP_LOINC = {"8480-6", "8462-4", "85354-9"}
_LDL_LOINC = "13457-7"
_A1C_LOINC = "4548-4"


def _immunizations(pattern: str) -> Callable[[Record], list[Evidence]]:
    rx = re.compile(pattern, re.I)

    def find(r: Record) -> list[Evidence]:
        return [Evidence(_day(i["occurred_at"]), "immunization", str(i["id"]), i["vaccine"])
                for i in r.immunizations if rx.search(i["vaccine"])]
    return find


def _tests(tags: dict[str, str], encounters: bool = True) -> Callable[[Record], list[Evidence]]:
    """Reports (and, unless `encounters` is False, encounters) whose name or summary mentions the test.
    `tags` maps tag -> regex. Encounter notes are skipped for lab tests, where a note like
    "lipid panel ordered" is not evidence the test was done."""
    compiled = {tag: re.compile(p, re.I) for tag, p in tags.items()}

    def tag_of(text: str) -> str | None:
        return next((tag for tag, rx in compiled.items() if rx.search(text)), None)

    def find(r: Record) -> list[Evidence]:
        out = []
        for rep in r.reports:
            if (tag := tag_of(rep["name"])) is not None:
                out.append(Evidence(_day(rep["collected_at"]), "report", str(rep["id"]), rep["name"], tag))
        for enc in (r.encounters if encounters else []):
            text = f"{enc['kind']} {enc['summary']}"
            if (tag := tag_of(text)) is not None:
                out.append(Evidence(_day(enc["occurred_at"]), "encounter", str(enc["id"]), enc["kind"], tag))
        return out
    return find


def _bp_evidence(r: Record) -> list[Evidence]:
    out = []
    for enc in r.encounters:
        m = _BP_TEXT.search(enc["summary"]) or _BP_TEXT.search(enc["kind"])
        if m:
            label = f"{enc['kind']}: BP {m.group(1)}/{m.group(2)}" if m.group(1) else enc["kind"]
            out.append(Evidence(_day(enc["occurred_at"]), "encounter", str(enc["id"]), label))
    seen_reports = set()
    for o in r.observations:
        if o["loinc_code"] in _BP_LOINC and o.get("report_id") not in seen_reports:
            seen_reports.add(o.get("report_id"))
            out.append(Evidence(_day(o["effective_at"]), "report", str(o.get("report_id") or o["id"]), o["display"]))
    return out


def _lipid_evidence(r: Record) -> list[Evidence]:
    out = _tests({"lipid": r"lipid|cholesterol"}, encounters=False)(r)
    reported = {e.source_id for e in out}
    for o in r.observations:
        if o["loinc_code"] == _LDL_LOINC and str(o.get("report_id")) not in reported:
            out.append(Evidence(_day(o["effective_at"]), "report", str(o.get("report_id") or o["id"]), o["display"]))
    return out


# --- Conditions the record shows ------------------------------------------------------------------


def _latest_bp(r: Record) -> tuple[int, int] | None:
    best: tuple[date, int, int] | None = None
    for enc in r.encounters:
        m = _BP_TEXT.search(enc["summary"])
        if m and m.group(1):
            d = _day(enc["occurred_at"])
            if best is None or d > best[0]:
                best = (d, int(m.group(1)), int(m.group(2)))
    return (best[1], best[2]) if best else None


def _latest(r: Record, loinc: str) -> dict[str, Any] | None:
    matches = [o for o in r.observations if o["loinc_code"] == loinc]
    return max(matches, key=lambda o: o["effective_at"]) if matches else None


def conditions(r: Record) -> set[str]:
    """Record facts that change a rule. Derived only from recorded values, never inferred."""
    found = set()
    bp = _latest_bp(r)
    if bp and (bp[0] >= 130 or bp[1] >= 80):
        found.add("elevated_bp")
    ldl = _latest(r, _LDL_LOINC)
    if ldl and ldl["interpretation"] == "H":
        found.add("high_ldl")
    a1c = _latest(r, _A1C_LOINC)
    if a1c and float(a1c["value"]) >= 6.5:
        found.add("diabetes")
    return found


# --- Rules ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    kind: str                    # 'screening' | 'vaccine'
    why: str                     # one plain-language line for patients
    source: str                  # the guidance this illustrative rule is adapted from
    find: Callable[[Record], list[Evidence]]
    min_age: int = 0
    max_age: int | None = None
    sexes: tuple[str, ...] | None = None
    interval_months: int | None = None   # None: once in a lifetime (a completed series)
    doses: int = 1
    specialty: str = "Primary care"
    gap_match: str | None = None         # regex that recognizes an existing care gap for this rule
    # Optional: (conditions, latest evidence) -> (months, reason) when the interval depends on the record.
    interval_for: Callable[[set[str], Evidence | None], tuple[int, str] | None] | None = None
    # Optional: extra eligibility outside the age band, e.g. a condition.
    also_eligible: Callable[[int, set[str]], bool] | None = None


def _bp_interval(conds: set[str], _: Evidence | None) -> tuple[int, str] | None:
    if "elevated_bp" in conds:
        return 6, "Your last recorded reading was above 130/80, so a recheck is suggested within 6 months."
    return None


def _lipid_interval(conds: set[str], _: Evidence | None) -> tuple[int, str] | None:
    if "high_ldl" in conds:
        return 12, "Your last LDL cholesterol was high, so a yearly check is suggested."
    return None


def _colorectal_interval(_: set[str], last: Evidence | None) -> tuple[int, str] | None:
    if last is None:
        return None
    return {
        "colonoscopy": (120, "After a normal colonoscopy, the next is usually in 10 years."),
        "sigmoidoscopy": (60, "After a sigmoidoscopy or CT colonography, the next is usually in 5 years."),
        "stool_dna": (36, "After a stool DNA test, the next is usually in 3 years."),
        "fit": (12, "A stool (FIT) test is repeated every year."),
    }.get(last.tag)


def _cervical_interval(_: set[str], last: Evidence | None) -> tuple[int, str] | None:
    if last is not None and last.tag == "hpv":
        return 60, "After an HPV test, the next is usually in 5 years."
    return None


RULES: tuple[Rule, ...] = (
    Rule(
        id="bp_check", title="Blood pressure check", kind="screening", min_age=40, interval_months=12,
        why="High blood pressure has no symptoms. A yearly check catches it early.",
        source="Illustrative; adapted from USPSTF 2021 hypertension screening (yearly from age 40) "
               "and ACC/AHA 2017 recheck intervals",
        find=_bp_evidence, interval_for=_bp_interval, gap_match=r"blood pressure",
    ),
    Rule(
        id="lipid_panel", title="Cholesterol blood test (lipid panel)", kind="screening",
        min_age=40, max_age=75, interval_months=60,
        why="Cholesterol levels help your clinician judge heart and stroke risk.",
        source="Illustrative; adapted from USPSTF 2022 statin use for primary prevention (adults 40 to 75)",
        find=_lipid_evidence, interval_for=_lipid_interval, gap_match=r"cholesterol|lipid",
    ),
    Rule(
        id="colorectal", title="Colorectal cancer screening", kind="screening",
        min_age=45, max_age=75, interval_months=12,
        why="Screening finds polyps and early cancers when they are easiest to treat.",
        source="Illustrative; adapted from USPSTF 2021 colorectal cancer screening (adults 45 to 75)",
        find=_tests({"colonoscopy": r"colonoscopy", "sigmoidoscopy": r"sigmoidoscopy|ct colonograph",
                     "stool_dna": r"stool dna|mt-sdna|cologuard", "fit": r"\bfit\b|fecal immunochemical|stool test"}),
        interval_for=_colorectal_interval, gap_match=r"colorectal|colon",
    ),
    Rule(
        id="cervical", title="Cervical cancer screening", kind="screening",
        min_age=21, max_age=65, sexes=("female",), interval_months=36,
        why="A Pap or HPV test finds changes long before they become cancer.",
        source="Illustrative; adapted from USPSTF 2018 cervical cancer screening (ages 21 to 65)",
        find=_tests({"hpv": r"\bhpv\b", "pap": r"\bpap\b|cervical cytology|cervical screen"}),
        interval_for=_cervical_interval, gap_match=r"cervical|pap",
    ),
    Rule(
        id="breast", title="Breast cancer screening (mammogram)", kind="screening",
        min_age=40, max_age=74, sexes=("female",), interval_months=24,
        why="A mammogram every two years finds breast cancer early.",
        source="Illustrative; adapted from USPSTF 2024 breast cancer screening (ages 40 to 74, every 2 years)",
        find=_tests({"mammogram": r"mammogra"}), gap_match=r"mammogra|breast",
    ),
    Rule(
        id="influenza", title="Flu vaccine", kind="vaccine", min_age=1, interval_months=12,
        why="A yearly flu shot lowers your chance of serious illness.",
        source="Illustrative; adapted from the CDC ACIP immunization schedule (influenza, yearly)",
        find=_immunizations(r"influenza|\bflu\b"), gap_match=r"\bflu\b|influenza",
    ),
    Rule(
        id="td_tdap", title="Tetanus booster (Td or Tdap)", kind="vaccine", min_age=11, interval_months=120,
        why="Protects against tetanus, diphtheria and whooping cough. A booster every 10 years.",
        source="Illustrative; adapted from the CDC ACIP immunization schedule (Td/Tdap every 10 years)",
        find=_immunizations(r"\bt?dap\b|\btd\b|tetanus"), gap_match=r"tetanus|tdap|\btd\b",
    ),
    Rule(
        id="shingles", title="Shingles vaccine (2 doses)", kind="vaccine", min_age=50, doses=2,
        why="Two doses protect against shingles and the long-lasting nerve pain it can cause.",
        source="Illustrative; adapted from the CDC ACIP recombinant zoster vaccine recommendation (age 50+)",
        find=_immunizations(r"shingl|zoster|shingrix"), gap_match=r"shingles|zoster",
    ),
    Rule(
        id="pneumococcal", title="Pneumococcal (pneumonia) vaccine", kind="vaccine", min_age=65,
        why="Protects against pneumonia and serious blood and brain infections.",
        source="Illustrative; adapted from the CDC ACIP pneumococcal recommendation (65+, or 19 to 64 with "
               "certain conditions such as diabetes)",
        find=_immunizations(r"pneumo|\bpcv\d*|ppsv|prevnar"), gap_match=r"pneumo",
        also_eligible=lambda age, conds: 19 <= age < 65 and "diabetes" in conds,
    ),
)
RULES_BY_ID = {r.id: r for r in RULES}


# --- Evaluation ------------------------------------------------------------------------------------


def _eligible(rule: Rule, age: int, sex: str | None, conds: set[str]) -> bool | None:
    """True, False, or None when eligibility depends on sex at birth and the record doesn't say."""
    in_band = age >= rule.min_age and (rule.max_age is None or age <= rule.max_age)
    if not in_band:
        return bool(rule.also_eligible and rule.also_eligible(age, conds))
    if rule.sexes is not None:
        if sex not in ("female", "male"):
            return None
        return sex in rule.sexes
    return True


def evaluate(record: Record, today: date | None = None) -> dict[str, Any]:
    """Every applicable rule with status 'due' | 'overdue' | 'up_to_date', its dates and its evidence."""
    today = today or date.today()
    age = age_on(record.birth_date, today)
    conds = conditions(record)
    items: list[dict[str, Any]] = []
    unknown_sex: list[str] = []

    for rule in RULES:
        eligible = _eligible(rule, age, record.sex, conds)
        if eligible is None:
            unknown_sex.append(rule.title)
            continue
        if not eligible:
            continue

        evidence = sorted(rule.find(record), key=lambda e: e.on, reverse=True)
        evidence = [e for e in evidence if e.on <= today]
        last = evidence[0] if evidence else None
        months, reason = rule.interval_months, None
        if rule.interval_for and (custom := rule.interval_for(conds, last)):
            months, reason = custom

        if last is None:
            status, next_due = "due", today
            detail = "No record of this yet."
        elif len({e.on for e in evidence}) < rule.doses:
            status, next_due = "due", today
            detail = f"{len({e.on for e in evidence})} of {rule.doses} doses recorded. The next dose is due."
        elif months is None:
            status, next_due = "up_to_date", None
            detail = "Complete."
        else:
            next_due = add_months(last.on, months)
            if next_due < today:
                status = "overdue"
            elif (next_due - today).days <= DUE_SOON_DAYS:
                status = "due"
            else:
                status = "up_to_date"
            detail = reason or f"Suggested every {_interval_text(months)}."

        items.append({
            "rule_id": rule.id,
            "title": rule.title,
            "kind": rule.kind,
            "status": status,
            "last_date": last.on if last else None,
            "next_due": next_due,
            "interval": _interval_text(months) if months else None,
            "detail": detail,
            "why": rule.why,
            "source": rule.source,
            "specialty": rule.specialty,
            "evidence": [
                {"date": e.on, "source_type": e.source_type, "source_id": e.source_id, "label": e.label}
                for e in evidence[:3]
            ],
        })

    order = {"overdue": 0, "due": 1, "up_to_date": 2}
    items.sort(key=lambda i: (order[i["status"]], RULES.index(RULES_BY_ID[i["rule_id"]])))
    notes = []
    if unknown_sex:
        notes.append(
            "Some screenings depend on sex assigned at birth, which isn't in your record: "
            + ", ".join(t.lower() for t in unknown_sex) + ". Ask your clinician whether they apply to you."
        )
    return {
        "ruleset": RULESET_VERSION,
        "disclaimer": DISCLAIMER,
        "evaluated_on": today,
        "age": age,
        "conditions": sorted(conds),
        "items": items,
        "notes": notes,
    }


def _interval_text(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return "year" if years == 1 else f"{years} years"
    return f"{months} months"


# --- Database ---------------------------------------------------------------------------------------


def load_record(conn: Connection, patient_id: str) -> Record:
    p = conn.execute("SELECT birth_date, sex_at_birth FROM patients WHERE id = %s", (patient_id,)).fetchone()
    return Record(
        birth_date=p["birth_date"],
        sex=p["sex_at_birth"],
        immunizations=conn.execute(
            "SELECT id::text, vaccine, occurred_at FROM immunizations WHERE patient_id = %s", (patient_id,)
        ).fetchall(),
        reports=conn.execute(
            "SELECT id::text, name, collected_at FROM diagnostic_reports WHERE patient_id = %s", (patient_id,)
        ).fetchall(),
        observations=conn.execute(
            """
            SELECT id::text, report_id::text, loinc_code, display, value, interpretation, effective_at
            FROM observations WHERE patient_id = %s AND (category = 'laboratory' OR source = 'clinic')
            """,
            (patient_id,),
        ).fetchall(),
        encounters=conn.execute(
            "SELECT id::text, kind, summary, occurred_at FROM encounters WHERE patient_id = %s", (patient_id,)
        ).fetchall(),
    )


def _gap_text(item: dict[str, Any]) -> tuple[str, str]:
    if item["status"] == "overdue":
        title = f"{item['title']} overdue"
        detail = f"Last done {item['last_date']:%B %Y}. {item['detail']}"
    else:
        title = f"{item['title']} due"
        detail = item["detail"] if item["last_date"] is None else f"Last done {item['last_date']:%B %Y}. {item['detail']}"
    return title, detail


def sync_gaps(conn: Connection, patient_id: str, items: list[dict[str, Any]], actor: User | None) -> dict[str, list]:
    """Mirror due/overdue items into care_gaps. Idempotent: one gap per rule, adopted if it already
    exists (matched by title), reopened when due again, closed when up to date."""
    linked = {
        row["rule_id"]: row
        for row in conn.execute(
            """
            SELECT l.rule_id, g.id::text AS gap_id, g.status, g.title
            FROM prevention_gap_links l JOIN care_gaps g ON g.id = l.gap_id
            WHERE l.patient_id = %s
            """,
            (patient_id,),
        ).fetchall()
    }
    unlinked_open = conn.execute(
        """
        SELECT g.id::text AS gap_id, g.title FROM care_gaps g
        WHERE g.patient_id = %s AND g.status = 'open'
          AND NOT EXISTS (SELECT 1 FROM prevention_gap_links l WHERE l.gap_id = g.id)
        """,
        (patient_id,),
    ).fetchall()

    result: dict[str, list] = {"opened": [], "closed": [], "unchanged": []}

    def link(gap_id: str, rule_id: str) -> None:
        conn.execute(
            """
            INSERT INTO prevention_gap_links (gap_id, patient_id, rule_id, ruleset) VALUES (%s, %s, %s, %s)
            ON CONFLICT (patient_id, rule_id) DO UPDATE SET gap_id = EXCLUDED.gap_id, ruleset = EXCLUDED.ruleset,
                updated_at = now()
            """,
            (gap_id, patient_id, rule_id, RULESET_VERSION),
        )

    def adoptable(rule: Rule) -> dict | None:
        if not rule.gap_match:
            return None
        rx = re.compile(rule.gap_match, re.I)
        for gap in unlinked_open:
            if rx.search(gap["title"]):
                unlinked_open.remove(gap)
                return gap
        return None

    def log(action: str, gap_id: str, rule_id: str) -> None:
        audit.record(conn, action=action, entity_type="care_gap", entity_id=gap_id, actor=actor,
                     agent="prevention-rules", patient_id=patient_id,
                     detail={"rule_id": rule_id, "ruleset": RULESET_VERSION})

    for item in items:
        rule = RULES_BY_ID[item["rule_id"]]
        current = linked.get(rule.id)
        wants_gap = item["status"] in ("due", "overdue")

        if current is None:
            adopted = adoptable(rule)
            if adopted is not None:
                link(adopted["gap_id"], rule.id)
                current = {"gap_id": adopted["gap_id"], "status": "open", "title": adopted["title"]}

        if wants_gap:
            if current is None:
                title, detail = _gap_text(item)
                gap = conn.execute(
                    "INSERT INTO care_gaps (patient_id, title, detail, specialty) VALUES (%s, %s, %s, %s) RETURNING id::text",
                    (patient_id, title, detail, rule.specialty),
                ).fetchone()
                link(gap["id"], rule.id)
                log("care_gap_opened", gap["id"], rule.id)
                result["opened"].append({"rule_id": rule.id, "gap_id": gap["id"], "title": title})
            elif current["status"] == "closed":
                title, detail = _gap_text(item)
                conn.execute("UPDATE care_gaps SET status = 'open', title = %s, detail = %s WHERE id = %s",
                             (title, detail, current["gap_id"]))
                log("care_gap_reopened", current["gap_id"], rule.id)
                result["opened"].append({"rule_id": rule.id, "gap_id": current["gap_id"], "title": title})
            else:
                result["unchanged"].append({"rule_id": rule.id, "gap_id": current["gap_id"], "title": current["title"]})
        elif current is not None and current["status"] == "open":
            conn.execute("UPDATE care_gaps SET status = 'closed' WHERE id = %s", (current["gap_id"],))
            log("care_gap_closed", current["gap_id"], rule.id)
            result["closed"].append({"rule_id": rule.id, "gap_id": current["gap_id"], "title": current["title"]})
    return result
