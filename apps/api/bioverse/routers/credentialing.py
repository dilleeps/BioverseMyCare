"""Clinician credentialing: licenses, NPI, board certification, and their verification.

The rule this module enforces for the rest of the platform: a clinician may appear in the online
directory, or accept an online consultation, only while `is_credentialed` is true, meaning they hold at
least one `verified` license whose expiry date has not passed and no license of theirs is `suspended`.
The check reads the dates directly, so it holds even on a day the `credential_expiry` job hasn't run.

NPI check digits are validated for real (Luhn over the number with the 80840 prefix). The NPPES registry
and state-board lookups are SIMULATED for this demo, and every check they produce is labelled that way.

Access: administrators run the verification queue for their organization. A clinician can read and
submit their own licenses. Nobody else sees credential records.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bioverse import audit
from bioverse.auth import Admin, Clinician, CurrentUser, User
from bioverse.config import clinic_today
from bioverse.db import DbConn

router = APIRouter(prefix="/api/credentialing", tags=["credentialing"])

Conn = DbConn

DEMO_NOTICE = (
    "Demo verification: NPI check digits are validated for real, but the NPPES registry and state-board "
    "lookups are simulated. Nothing here contacts a real registry."
)
SOURCE_LABELS = {"nppes": "NPPES registry (simulated demo lookup)", "state_board": "State board (simulated demo lookup)"}
STATUS_LABELS = {"pending": "Pending", "verified": "Verified", "expired": "Expired", "rejected": "Rejected",
                 "suspended": "Suspended"}
EXPIRY_NOTICE_DAYS = (60, 30, 7)


# --- NPI --------------------------------------------------------------------------------------


def luhn_ok(digits: str) -> bool:
    """Standard Luhn: from the right, double every second digit, subtract 9 when over 9, sum mod 10 == 0."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def npi_check_digit(first_nine: str) -> int:
    """The tenth digit that makes `first_nine` a valid NPI (Luhn over 80840 + the nine digits)."""
    if len(first_nine) != 9 or not first_nine.isdigit():
        raise ValueError("an NPI stem is nine digits")
    for d in range(10):
        if luhn_ok("80840" + first_nine + str(d)):
            return d
    raise AssertionError("unreachable: exactly one check digit fits")


def npi_is_valid(npi: str | None) -> bool:
    """Ten digits, starting with 1 or 2, whose last digit is the Luhn check digit of 80840 + the first nine."""
    npi = (npi or "").strip()
    return len(npi) == 10 and npi.isdigit() and npi[0] in "12" and luhn_ok("80840" + npi)


def npi_problem(npi: str | None) -> str | None:
    npi = (npi or "").strip()
    if len(npi) != 10 or not npi.isdigit():
        return "An NPI is exactly 10 digits"
    if npi[0] not in "12":
        return "An NPI starts with 1 (individual) or 2 (organization)"
    if not luhn_ok("80840" + npi):
        return "The NPI check digit doesn't match. Check for a typo"
    return None


# --- The gate every other module uses ----------------------------------------------------------

CREDENTIALED_SQL = """
    EXISTS (SELECT 1 FROM practitioner_credentials c
            WHERE c.practitioner_id = {pr} AND c.status = 'verified' AND c.expires_on >= {today}::date)
    AND NOT EXISTS (SELECT 1 FROM practitioner_credentials c
                    WHERE c.practitioner_id = {pr} AND c.status = 'suspended')
"""


def credentialed_sql(pr_col: str, today_param: str = "%(today)s") -> str:
    """A SQL condition, true when the practitioner in `pr_col` is credentialed on `today_param`."""
    return CREDENTIALED_SQL.format(pr=pr_col, today=today_param)


def is_credentialed(conn: Connection, practitioner_id: str | None, today: date | None = None) -> bool:
    if not practitioner_id:
        return False
    row = conn.execute(
        "SELECT " + credentialed_sql("%(pr)s::uuid") + " AS ok",
        {"pr": practitioner_id, "today": today or clinic_today()},
    ).fetchone()
    return bool(row["ok"])


def require_credentialed(conn: Connection, practitioner_id: str | None) -> None:
    if not is_credentialed(conn, practitioner_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "not_credentialed",
             "message": "You need a verified, unexpired license on file before you can take online consultations."},
        )


def verification_badge(conn: Connection, practitioner_id: str, today: date | None = None) -> dict | None:
    """What a patient sees behind the "Verified" badge: the license checked, how, and when."""
    row = conn.execute(
        """
        SELECT license_type, jurisdiction, license_number, board_certification, npi, expires_on, source,
               verification_checks, verified_at
        FROM practitioner_credentials
        WHERE practitioner_id = %s AND status = 'verified' AND expires_on >= %s
        ORDER BY verified_at DESC NULLS LAST LIMIT 1
        """,
        (practitioner_id, today or clinic_today()),
    ).fetchone()
    if row is None:
        return None
    return {
        "license": f"{row['license_type']} license {row['license_number']} ({row['jurisdiction']})",
        "license_type": row["license_type"],
        "jurisdiction": row["jurisdiction"],
        "board_certification": row["board_certification"],
        "npi": row["npi"],
        "expires_on": row["expires_on"],
        "verified_at": row["verified_at"],
        "source": SOURCE_LABELS.get(row["source"], row["source"]),
        "checks": row["verification_checks"],
        "notice": DEMO_NOTICE,
    }


def credential_state(conn: Connection, practitioner_id: str) -> dict:
    """A clinician's own standing, for their consult queue."""
    rows = _rows(conn, "c.practitioner_id = %(pr)s", {"pr": practitioner_id})
    ok = is_credentialed(conn, practitioner_id)
    if ok:
        msg = "Your license is verified. You appear in the online directory and can take consultations."
    elif any(r["status"] == "suspended" for r in rows):
        msg = "A license of yours is suspended. You can't take online consultations until an administrator reinstates it."
    elif any(r["status"] == "pending" for r in rows):
        msg = "Your license is waiting for verification. You'll appear in the directory once it's verified."
    elif rows:
        msg = "None of your licenses is currently verified and in date. Submit a current license to take consultations."
    else:
        msg = "No license on file. Submit one to take online consultations."
    return {"credentialed": ok, "message": msg, "credentials": rows}


# --- Reading ----------------------------------------------------------------------------------

SELECT = """
    SELECT c.id::text, c.practitioner_id::text, pr.name AS practitioner_name, pr.specialty,
           c.license_number, c.jurisdiction, c.license_type, c.board_certification, c.npi, c.issued_on,
           c.expires_on, c.status, c.source, c.verification_checks, c.verified_at, vu.display_name AS verified_by_name,
           c.decision_reason, c.notes, c.created_at, c.updated_at
    FROM practitioner_credentials c
    JOIN practitioners pr ON pr.id = c.practitioner_id
    LEFT JOIN users vu ON vu.id = c.verified_by
"""


def _out(row: dict, today: date) -> dict:
    row["npi_valid"] = npi_is_valid(row["npi"])
    row["days_to_expiry"] = (row["expires_on"] - today).days
    row["status_label"] = STATUS_LABELS[row["status"]]
    row["source_label"] = SOURCE_LABELS.get(row["source"], row["source"])
    row["expiring_soon"] = row["status"] == "verified" and 0 <= row["days_to_expiry"] <= EXPIRY_NOTICE_DAYS[0]
    row["lapsed"] = row["status"] == "verified" and row["days_to_expiry"] < 0
    return row


def _rows(conn: Connection, where: str, params: dict, order: str = "c.created_at DESC") -> list[dict]:
    today = clinic_today()
    rows = conn.execute(SELECT + " WHERE " + where + " ORDER BY " + order, params).fetchall()
    return [_out(r, today) for r in rows]


def _valid_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found") from None


def _load(conn: Connection, user: User, credential_id: str, lock: bool = False) -> dict:
    cid = _valid_uuid(credential_id)
    row = conn.execute(
        SELECT + " WHERE c.id = %s AND pr.organization_id = %s" + (" FOR UPDATE OF c" if lock else ""),
        (cid, user.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    return _out(row, clinic_today())


QueueFilter = Literal["pending", "expiring", "verified", "attention", "all"]


@router.get("/credentials")
def list_credentials(conn: Conn, user: Admin, filter: QueueFilter = "pending") -> dict:
    today = clinic_today()
    where = {
        "pending": "c.status = 'pending'",
        "expiring": "c.status = 'verified' AND c.expires_on <= %(today)s::date + 60",
        "verified": "c.status = 'verified'",
        "attention": "c.status IN ('expired', 'rejected', 'suspended')",
        "all": "true",
    }[filter]
    order = "c.expires_on ASC" if filter == "expiring" else "c.created_at ASC" if filter == "pending" else "pr.name, c.expires_on"
    rows = _rows(conn, f"pr.organization_id = %(org)s AND {where}", {"org": user.organization_id, "today": today}, order)
    audit.record(conn, action="credential_queue_viewed", entity_type="practitioner_credential", actor=user,
                 detail={"filter": filter, "count": len(rows)})
    return {"credentials": rows, "notice": DEMO_NOTICE}


@router.get("/summary")
def summary(conn: Conn, user: Admin) -> dict:
    row = conn.execute(
        """
        SELECT count(*) FILTER (WHERE c.status = 'pending') AS pending,
               count(*) FILTER (WHERE c.status = 'verified' AND c.expires_on BETWEEN %(t)s AND %(t)s::date + 60) AS expiring,
               count(*) FILTER (WHERE c.status = 'verified' AND c.expires_on >= %(t)s) AS verified,
               count(*) FILTER (WHERE c.status IN ('expired', 'rejected', 'suspended')
                                 OR (c.status = 'verified' AND c.expires_on < %(t)s)) AS attention
        FROM practitioner_credentials c JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE pr.organization_id = %(org)s
        """,
        {"t": clinic_today(), "org": user.organization_id},
    ).fetchone()
    return {**row, "notice": DEMO_NOTICE}


@router.get("/npi/{npi}")
def check_npi(npi: str, user: CurrentUser) -> dict:
    if user.role not in ("clinician", "admin", "staff"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff access required")
    problem = npi_problem(npi)
    return {"npi": npi, "valid": problem is None, "problem": problem}


# --- Submitting ---------------------------------------------------------------------------------


class CredentialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    license_number: str = Field(min_length=3, max_length=30)
    jurisdiction: str = Field(min_length=2, max_length=2)
    license_type: Literal["MD", "DO", "NP", "PA", "RN", "PsyD", "PhD"]
    board_certification: str | None = Field(default=None, max_length=160)
    npi: str
    issued_on: date | None = None
    expires_on: date
    source: Literal["nppes", "state_board"] = "state_board"
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("board_certification", "notes")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (" ".join(v.split()) or None) if v is not None else None

    @field_validator("license_number")
    @classmethod
    def _license(cls, v: str) -> str:
        v = "".join(v.split()).upper()
        if len(v) < 3 or not all(ch.isalnum() or ch == "-" for ch in v):
            raise ValueError("Use the license number as printed: letters, digits and dashes")
        return v

    @field_validator("jurisdiction")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("Use the two-letter state code")
        return v

    @field_validator("npi")
    @classmethod
    def _npi(cls, v: str) -> str:
        v = v.strip()
        problem = npi_problem(v)
        if problem:
            raise ValueError(problem)
        return v


def _insert(conn: Connection, user: User, practitioner_id: str, body: CredentialIn) -> dict:
    if body.expires_on <= clinic_today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This license has already expired")
    if body.issued_on and body.issued_on >= body.expires_on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The issue date must be before the expiry date")
    row = conn.execute(
        """
        INSERT INTO practitioner_credentials (practitioner_id, license_number, jurisdiction, license_type,
            board_certification, npi, issued_on, expires_on, source, notes, submitted_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (jurisdiction, license_number) DO NOTHING
        RETURNING id::text
        """,
        (practitioner_id, body.license_number, body.jurisdiction, body.license_type, body.board_certification,
         body.npi, body.issued_on, body.expires_on, body.source, body.notes, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That license number is already on file for this jurisdiction")
    audit.record(conn, action="credential_submitted", entity_type="practitioner_credential", entity_id=row["id"],
                 actor=user, detail={"practitioner_id": practitioner_id, "jurisdiction": body.jurisdiction,
                                     "license_type": body.license_type})
    return _rows(conn, "c.id = %(id)s", {"id": row["id"]})[0]


@router.get("/mine")
def my_credentials(conn: Conn, user: Clinician) -> dict:
    return {**credential_state(conn, user.practitioner_id), "notice": DEMO_NOTICE}


@router.post("/mine", status_code=status.HTTP_201_CREATED)
def submit_mine(body: CredentialIn, conn: Conn, user: Clinician) -> dict:
    return _insert(conn, user, user.practitioner_id, body)


class AdminCredentialIn(CredentialIn):
    practitioner_id: str


@router.post("/credentials", status_code=status.HTTP_201_CREATED)
def submit_for(body: AdminCredentialIn, conn: Conn, user: Admin) -> dict:
    pr = conn.execute(
        "SELECT id::text FROM practitioners WHERE id::text = %s AND organization_id = %s",
        (body.practitioner_id, user.organization_id),
    ).fetchone()
    if pr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinician not found")
    return _insert(conn, user, pr["id"], CredentialIn(**body.model_dump(exclude={"practitioner_id"})))


# --- Deciding ---------------------------------------------------------------------------------


def simulated_checks(cred: dict, today: date, now: datetime) -> list[dict]:
    """The verification steps. The NPI and date checks are real; registry lookups are simulated."""
    at = now.isoformat()
    checks = [
        {"check": "NPI check digit (Luhn with 80840 prefix)", "result": "pass" if npi_is_valid(cred["npi"]) else "fail",
         "detail": f"NPI {cred['npi']}", "demo": False, "at": at},
        {"check": "License in date", "result": "pass" if cred["expires_on"] >= today else "fail",
         "detail": f"Expires {cred['expires_on']:%d %b %Y}", "demo": False, "at": at},
        {"check": "NPPES registry lookup", "result": "match",
         "detail": f"Name and NPI match {cred['practitioner_name']} (simulated demo lookup)", "demo": True, "at": at},
        {"check": f"State board lookup ({cred['jurisdiction']})", "result": "active",
         "detail": f"{cred['license_type']} license {cred['license_number']} active, no public discipline "
                   "(simulated demo lookup)", "demo": True, "at": at},
    ]
    if cred["board_certification"]:
        checks.append({"check": "Board certification", "result": "confirmed",
                       "detail": f"{cred['board_certification']} (simulated demo lookup)", "demo": True, "at": at})
    return checks


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/credentials/{credential_id}/verify")
def verify(credential_id: str, body: VerifyIn, conn: Conn, user: Admin) -> dict:
    cred = _load(conn, user, credential_id, lock=True)
    if cred["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only pending licenses can be verified (this one is {cred['status']})")
    today = clinic_today()
    now = datetime.now(timezone.utc)
    checks = simulated_checks(cred, today, now)
    failed = [c["check"] for c in checks if c["result"] == "fail"]
    if failed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "checks_failed", "message": "Can't verify: " + ", ".join(failed).lower() + " failed. Reject it with a reason instead.",
             "checks": checks},
        )
    conn.execute(
        """
        UPDATE practitioner_credentials
        SET status = 'verified', verification_checks = %s, verified_by = %s, verified_at = %s,
            notes = coalesce(%s, notes), decision_reason = NULL, updated_at = now()
        WHERE id = %s
        """,
        (Jsonb(checks), user.id, now, (body.notes or "").strip() or None, cred["id"]),
    )
    audit.record(conn, action="credential_verified", entity_type="practitioner_credential", entity_id=cred["id"],
                 actor=user, agent="credentialing/demo-lookups",
                 detail={"practitioner_id": cred["practitioner_id"], "checks": [c["check"] for c in checks],
                         "simulated": [c["check"] for c in checks if c["demo"]]})
    return _load(conn, user, cred["id"])


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/credentials/{credential_id}/reject")
def reject(credential_id: str, body: ReasonIn, conn: Conn, user: Admin) -> dict:
    cred = _load(conn, user, credential_id, lock=True)
    if cred["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending licenses can be rejected")
    reason = " ".join(body.reason.split())
    conn.execute(
        """
        UPDATE practitioner_credentials SET status = 'rejected', decision_reason = %s, verified_by = %s,
               verified_at = NULL, updated_at = now() WHERE id = %s
        """,
        (reason, user.id, cred["id"]),
    )
    audit.record(conn, action="credential_rejected", entity_type="practitioner_credential", entity_id=cred["id"],
                 actor=user, detail={"practitioner_id": cred["practitioner_id"], "reason": reason})
    return _load(conn, user, cred["id"])


@router.post("/credentials/{credential_id}/suspend")
def suspend(credential_id: str, body: ReasonIn, conn: Conn, user: Admin) -> dict:
    cred = _load(conn, user, credential_id, lock=True)
    if cred["status"] != "verified":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only verified licenses can be suspended")
    reason = " ".join(body.reason.split())
    conn.execute(
        "UPDATE practitioner_credentials SET status = 'suspended', decision_reason = %s, updated_at = now() WHERE id = %s",
        (reason, cred["id"]),
    )
    audit.record(conn, action="credential_suspended", entity_type="practitioner_credential", entity_id=cred["id"],
                 actor=user, detail={"practitioner_id": cred["practitioner_id"], "reason": reason})
    return _load(conn, user, cred["id"])
