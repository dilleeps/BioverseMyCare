"""Creating people: the one place a Bioverse account gets the rows its role needs.

create_person is used by the admin form (routers/access.py), the CSV bulk import and just-in-time
provisioning from a mapped directory group (sso/plugins/group_mapping.py):

- clinician -> practitioners + consult_profiles (listed in the consult directory once their license is verified)
- staff on the pharmacy team -> pharmacy_staff (the order verification queue checks it)
- patient -> a patient record through bioverse.patient_registry.register_patient (duplicate check)
- admin, student, front-desk staff -> just the user

It does not write an audit event: callers record their own (one per person, or one per import).

The CSV import lives here too: parse_csv reads the file, plan_import says what each row would do,
apply_import does it.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import Connection

from bioverse.patient_registry import register_patient

if TYPE_CHECKING:
    from bioverse.auth import User

log = logging.getLogger(__name__)

ROLES = ("admin", "staff", "clinician", "patient", "student")
TEAMS = ("front_desk", "pharmacy")


class PersonError(ValueError):
    """A person can't be created as asked. `message` is safe to show an administrator."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_email(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v or len(v) > 200:
        raise ValueError("That doesn't look like an email address")
    return v


def email_taken(conn: Connection, email: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,)).fetchone() is not None


def sync_pharmacy_staff(conn: Connection, user_id: str, org_id: str, team: str | None) -> None:
    """Pharmacy-team staff are pharmacists: the order verification queue checks pharmacy_staff."""
    if team == "pharmacy":
        conn.execute(
            """
            INSERT INTO pharmacy_staff (user_id, organization_id, pharmacy_id)
            VALUES (%s, %s, (SELECT pharmacy_id FROM pharmacy_staff WHERE organization_id = %s
                             AND pharmacy_id IS NOT NULL LIMIT 1))
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id, org_id, org_id),
        )
    else:
        conn.execute("DELETE FROM pharmacy_staff WHERE user_id = %s", (user_id,))


def create_person(conn: Connection, *, organization_id: str, display_name: str, email: str, role: str,
                  team: str | None = None, specialty: str | None = None, location_name: str | None = None,
                  birth_date: date | None = None, consult_fee_dollars: int | None = None,
                  actor: "User | None" = None, source: str = "admin") -> dict:
    """Create a user and what their role needs. Returns {"id", "role", "team", "patient"?}.

    `email` must already be normalized (normalize_email). Raises PersonError (409 when the email is taken,
    422 when the role is missing something it needs).
    """
    if role not in ROLES:
        raise PersonError(f"Unknown role {role!r}")
    if email_taken(conn, email):
        raise PersonError("Someone already uses that email", 409)
    if role == "clinician" and not specialty:
        raise PersonError("A clinician needs a specialty")
    if role == "patient" and not birth_date:
        raise PersonError("A patient needs a date of birth")
    team = team if role == "staff" else None
    user_id = conn.execute(
        "INSERT INTO users (role, display_name, email, organization_id, team) VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
        (role, display_name, email, organization_id, team),
    ).fetchone()["id"]
    if role == "clinician":
        practitioner_id = conn.execute(
            "INSERT INTO practitioners (user_id, organization_id, name, specialty, location_name) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, organization_id, display_name, specialty, location_name or "Main clinic"),
        ).fetchone()["id"]
        # Online consult profile; they appear in the directory once their license is verified.
        conn.execute(
            "INSERT INTO consult_profiles (practitioner_id, modes, fee_cents) VALUES (%s, '{message,video}', %s)",
            (practitioner_id, (consult_fee_dollars or 0) * 100),
        )
    if role == "staff":
        sync_pharmacy_staff(conn, user_id, organization_id, team)
    out: dict[str, Any] = {"id": user_id, "role": role, "team": team}
    if role == "patient":
        out["patient"] = register_patient(conn, organization_id=organization_id, user_id=user_id,
                                          name=display_name, birth_date=birth_date, email=email,
                                          source=source, actor_id=actor.id if actor else None)
    return out


# --- CSV import ------------------------------------------------------------------------------------------

MAX_ROWS = 1000
MAX_CSV_CHARS = 2_000_000
COLUMNS = ("name", "email", "role", "team", "specialty", "location", "birth_date", "consult_fee")
REQUIRED_COLUMNS = ("name", "email", "role")

# Header spellings people use in spreadsheets and directory exports, after lower-casing and turning
# _ - . into spaces.
HEADER_ALIASES = {
    "name": ("name", "full name", "display name", "person", "person name", "staff name", "displayname"),
    "email": ("email", "e mail", "email address", "e mail address", "sign in email", "work email", "mail",
              "user principal name", "userprincipalname", "upn", "login", "username"),
    "role": ("role", "user role", "access role", "bioverse role", "user type", "type"),
    "team": ("team", "department", "dept", "staff team", "unit"),
    "specialty": ("specialty", "speciality", "specialization", "specialisation", "clinical specialty"),
    "location": ("location", "location name", "clinic", "site", "practice location"),
    "birth_date": ("birth date", "date of birth", "dob", "birthdate", "birthday"),
    "consult_fee": ("consult fee", "consultation fee", "fee", "consult fee dollars", "online consult fee",
                    "consult fee usd", "fee usd"),
}
_HEADER_LOOKUP = {alias: col for col, aliases in HEADER_ALIASES.items() for alias in aliases}

ROLE_ALIASES = {
    "admin": ("admin", "administrator", "org admin", "organization administrator"),
    "staff": ("staff", "operations", "ops"),
    "clinician": ("clinician", "doctor", "physician", "provider", "practitioner", "nurse practitioner", "np", "md"),
    "patient": ("patient", "member"),
    "student": ("student", "medical student", "med student", "learner"),
}
_ROLE_LOOKUP = {alias: r for r, aliases in ROLE_ALIASES.items() for alias in aliases}
# Job titles that imply a staff team when the team column is empty.
_ROLE_WITH_TEAM = {"pharmacist": "pharmacy", "pharmacy": "pharmacy", "pharmacy staff": "pharmacy",
                   "front desk": "front_desk", "receptionist": "front_desk", "reception": "front_desk"}
TEAM_ALIASES = {"front desk": "front_desk", "frontdesk": "front_desk", "reception": "front_desk",
                "front office": "front_desk", "pharmacy": "pharmacy", "pharmacist": "pharmacy",
                "pharmacists": "pharmacy", "none": None, "": None}

TEMPLATE_ROWS = [
    ("Alex Rivera", "alex.rivera@example.org", "staff", "front_desk", "", "", "", ""),
    ("Sam Lee", "sam.lee@example.org", "staff", "pharmacy", "", "", "", ""),
    ("Dr. Priya Shah", "priya.shah@example.org", "clinician", "", "Cardiology", "Main clinic", "", "60"),
    ("Jordan Kim", "jordan.kim@example.org", "patient", "", "", "", "1984-03-17", ""),
    ("Casey Morgan", "casey.morgan@example.org", "student", "", "", "", "", ""),
    ("Taylor Brooks", "taylor.brooks@example.org", "admin", "", "", "", "", ""),
]


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-.]", " ", (s or "").strip().lower())).strip()


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(COLUMNS)
    w.writerows(TEMPLATE_ROWS)
    return buf.getvalue()


@dataclass
class ParsedCsv:
    columns: dict[str, int]                   # our column -> index in the file
    ignored_columns: list[str]
    rows: list[tuple[int, list[str]]]         # (spreadsheet line number, cells)
    delimiter: str = ","


def parse_csv(text: str) -> ParsedCsv:
    """Read the header and rows. Raises PersonError for problems with the file as a whole."""
    if len(text) > MAX_CSV_CHARS:
        raise PersonError("That file is too large. Import at most 1,000 people at a time.", 413)
    text = text.lstrip("﻿")
    if not text.strip():
        raise PersonError("The file is empty")
    first = text.splitlines()[0]
    delimiter = max((",", ";", "\t"), key=first.count)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
        body = []
        for cells in reader:
            if any(c.strip() for c in cells):
                body.append((reader.line_num, cells))
                if len(body) > MAX_ROWS:
                    raise PersonError(f"Import at most {MAX_ROWS:,} people at a time", 413)
    except csv.Error as exc:
        raise PersonError(f"Couldn't read the file as CSV: {exc}") from exc
    columns: dict[str, int] = {}
    ignored: list[str] = []
    for i, h in enumerate(header):
        col = _HEADER_LOOKUP.get(_key(h))
        if col and col not in columns:
            columns[col] = i
        elif h.strip():
            ignored.append(h.strip())
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise PersonError(f"The first row must name the columns. Missing: {', '.join(missing)}. "
                          f"Download the template to see the expected columns.")
    if not body:
        raise PersonError("The file has a header row but no people")
    return ParsedCsv(columns, ignored, body, delimiter)


@dataclass
class RowPlan:
    row: int
    name: str
    email: str
    role: str | None = None
    team: str | None = None
    specialty: str | None = None
    location_name: str | None = None
    birth_date: date | None = None
    consult_fee_dollars: int | None = None
    status: str = "create"          # create | update | skip | duplicate | error
    message: str | None = None
    problems: list[str] = field(default_factory=list)
    existing_id: str | None = None
    id: str | None = None

    def public(self, dry_run: bool) -> dict:
        label = {"create": "would_create", "update": "would_update"} if dry_run else {"create": "created", "update": "updated"}
        return {
            "row": self.row, "name": self.name, "email": self.email, "role": self.role, "team": self.team,
            "specialty": self.specialty,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "consult_fee_dollars": self.consult_fee_dollars,
            "status": label.get(self.status, self.status), "message": self.message,
            **({"id": self.id} if self.id else {}),
        }


def _cell(cells: list[str], columns: dict[str, int], col: str) -> str:
    i = columns.get(col)
    return cells[i].strip() if i is not None and i < len(cells) else ""


def _parse_date(v: str) -> date:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if not m:
        raise ValueError(f"Date of birth {v!r} should look like 1984-03-17 (year-month-day)")
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        raise ValueError(f"{v!r} isn't a real date") from None
    if d > date.today() or d.year < 1900:
        raise ValueError(f"Date of birth {v} is out of range")
    return d


def _parse_fee(v: str) -> int:
    s = v.replace("$", "").replace(",", "").strip()
    try:
        n = float(s)
    except ValueError:
        raise ValueError(f"Consult fee {v!r} should be a number of dollars, like 60") from None
    if n != int(n):
        raise ValueError("Consult fee should be whole dollars")
    if not 0 <= n <= 2000:
        raise ValueError("Consult fee should be between 0 and 2,000 dollars")
    return int(n)


def _plan_row(line: int, cells: list[str], columns: dict[str, int]) -> RowPlan:
    get = lambda col: _cell(cells, columns, col)  # noqa: E731
    p = RowPlan(row=line, name=get("name"), email=get("email"))
    problems = p.problems

    if len(p.name) < 2:
        problems.append("Name is missing" if not p.name else "Name is too short")
    elif len(p.name) > 120:
        problems.append("Name is longer than 120 characters")

    try:
        p.email = normalize_email(p.email) if p.email else ""
        if not p.email:
            problems.append("Email is missing")
    except ValueError:
        problems.append(f"{p.email!r} doesn't look like an email address")

    raw_role, raw_team = _key(get("role")), _key(get("team"))
    implied_team = None
    if raw_role in _ROLE_WITH_TEAM:
        p.role, implied_team = "staff", _ROLE_WITH_TEAM[raw_role]
    else:
        p.role = _ROLE_LOOKUP.get(raw_role)
    if p.role is None:
        problems.append("Role is missing" if not raw_role else
                        f"Unknown role {get('role')!r}. Use admin, staff, clinician, patient or student")

    if p.role == "staff":      # other roles have no team; a "department" column is ignored for them
        if raw_team in TEAM_ALIASES:
            p.team = TEAM_ALIASES[raw_team] or implied_team
        else:
            problems.append(f"Unknown team {get('team')!r}. Use front_desk, pharmacy or leave it empty")

    specialty = get("specialty")
    if len(specialty) > 80:
        problems.append("Specialty is longer than 80 characters")
    location = get("location")
    if len(location) > 120:
        problems.append("Location is longer than 120 characters")
    if p.role == "clinician":
        p.specialty = specialty or None
        p.location_name = location or None
        if not specialty:
            problems.append("A clinician needs a specialty")
        if get("consult_fee"):
            try:
                p.consult_fee_dollars = _parse_fee(get("consult_fee"))
            except ValueError as exc:
                problems.append(str(exc))

    if p.role == "patient":
        if not get("birth_date"):
            problems.append("A patient needs a date of birth")
        else:
            try:
                p.birth_date = _parse_date(get("birth_date"))
            except ValueError as exc:
                problems.append(str(exc))

    if problems:
        p.status, p.message = "error", "; ".join(problems)
    return p


def plan_import(conn: Connection, parsed: ParsedCsv, *, organization_id: str,
                update_existing: bool = False) -> list[RowPlan]:
    plans = [_plan_row(line, cells, parsed.columns) for line, cells in parsed.rows]
    first_seen: dict[str, int] = {}
    for p in plans:
        if not p.email or "@" not in p.email:
            continue
        if p.email in first_seen:
            if p.status != "error":
                p.status = "duplicate"
                p.message = f"Same email as row {first_seen[p.email]}"
            continue
        first_seen[p.email] = p.row
    emails = list(first_seen)
    existing = {r["email"]: r for r in conn.execute(
        "SELECT lower(email) AS email, id::text, role, team, organization_id::text AS org FROM users "
        "WHERE lower(email) = ANY(%s)", (emails,)).fetchall()} if emails else {}
    for p in plans:
        found = existing.get(p.email)
        if found is None or p.status in ("error", "duplicate"):
            continue
        p.existing_id = found["id"]
        if not update_existing:
            p.status, p.message = "skip", "Already has an account; skipped"
        elif found["org"] not in (None, organization_id):
            p.status, p.message = "skip", "Already has an account in another organization; skipped"
        elif found["role"] != p.role:
            p.status, p.message = "skip", (f"Already has an account as {found['role']}; "
                                           "import doesn't change roles")
        elif p.role == "staff" and found["team"] != p.team:
            p.status = "update"
            p.message = f"Team {found['team'] or 'none'} → {p.team or 'none'}"
        else:
            p.status, p.message = "skip", "Already up to date"
    return plans


def totals(plans: list[RowPlan]) -> dict:
    t = {"rows": len(plans), "create": 0, "update": 0, "skip": 0, "duplicate": 0, "error": 0}
    for p in plans:
        t[p.status] += 1
    return t


def blocking(plans: list[RowPlan]) -> int:
    """Rows that stop an all-or-nothing import: errors and repeated emails."""
    return sum(p.status in ("error", "duplicate") for p in plans)


def apply_import(conn: Connection, plans: list[RowPlan], *, organization_id: str, actor: "User | None") -> None:
    """Create and update the planned rows. Each row runs in a savepoint so one failing row can be reported
    without losing the others; the caller decides whether any failure aborts the whole import."""
    for p in plans:
        if p.status == "create":
            try:
                with conn.transaction():
                    p.id = create_person(
                        conn, organization_id=organization_id, display_name=p.name, email=p.email, role=p.role,
                        team=p.team, specialty=p.specialty, location_name=p.location_name, birth_date=p.birth_date,
                        consult_fee_dollars=p.consult_fee_dollars, actor=actor, source="import",
                    )["id"]
            except (PersonError, ValueError) as exc:
                p.status, p.message = "error", getattr(exc, "message", None) or str(exc)
            except psycopg.Error:
                log.exception("import row %s failed", p.row)
                p.status, p.message = "error", "Couldn't save this person"
        elif p.status == "update":
            with conn.transaction():
                row = conn.execute(
                    "UPDATE users SET team = %s WHERE id::text = %s AND role = 'staff' "
                    "AND (organization_id = %s OR organization_id IS NULL) "
                    "RETURNING id::text, organization_id::text AS org",
                    (p.team, p.existing_id, organization_id),
                ).fetchone()
                if row:
                    sync_pharmacy_staff(conn, row["id"], row["org"] or organization_id, p.team)
                    p.id = row["id"]
                else:
                    p.status, p.message = "skip", "Changed since the dry run; skipped"


# --- CSV export ------------------------------------------------------------------------------------------

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v: Any) -> str:
    """Spreadsheet apps run cells that start with = + - @ as formulas; prefix those with a quote."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_START) else s
