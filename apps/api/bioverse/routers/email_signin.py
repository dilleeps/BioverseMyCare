"""Passwordless sign-in with a one-time code sent by email, for patients without Google, Microsoft or Okta.

    POST /api/auth/email/start   {email, invite?}          -> always the same answer (no account enumeration)
    POST /api/auth/email/verify  {email, code, invite?, next?} -> starts a session (bv_session cookie)
    GET  /api/auth/dev-outbox?email=...                     -> demo only: email the app would have sent
    GET/POST /api/auth/register                             -> open self-registration (BIOVERSE_SELF_REGISTRATION=on)

A code is six digits, stored only as a salted SHA-256, valid for ten minutes and five tries, and at most five
are sent per email address per hour. Codes go only to patient accounts, to someone accepting an invite whose
date of birth was just confirmed, or to a new self-registration; staff and clinicians sign in with single
sign-on. A request for any other address is recorded but nothing is sent, and the response is identical.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from bioverse import audit
from bioverse.db import DbConn
from bioverse.patient_registry import register_patient
from bioverse.routers.invites import WebClient, email_signin_enabled, normalize_email
from bioverse.sso import sessions
from bioverse.sso.plugins import invites as invite_core
from bioverse.sso.providers import demo_allowed

router = APIRouter(prefix="/api/auth", tags=["sign-in"])

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_PER_EMAIL_PER_HOUR = 5
MAX_PER_IP_PER_HOUR = 30

SENT = {"sent": True, "expires_in_minutes": int(CODE_TTL.total_seconds() // 60),
        "message": "If that address can sign in here, we've emailed it a 6-digit code."}
BAD_CODE = "That code didn't work. Check it, or ask for a new one."


def self_registration_enabled() -> bool:
    return os.getenv("BIOVERSE_SELF_REGISTRATION", "").strip().lower() in ("on", "true", "1", "yes")


def _require_enabled() -> None:
    if not email_signin_enabled():
        raise HTTPException(404, "Email sign-in is off")


def _hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _safe_next(path: str | None) -> str:
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


def _client_ip(request: Request) -> str:
    # The server's own view (uvicorn --proxy-headers resolves trusted proxies); a raw X-Forwarded-For is spoofable.
    return (request.client.host if request.client else "") or "unknown"


def _user_by_email(conn: Connection, email: str) -> dict | None:
    return conn.execute("SELECT id::text, role, disabled FROM users WHERE lower(email) = %s", (email,)).fetchone()


def _issue(conn: Connection, request: Request, background: BackgroundTasks, *, email: str, purpose: str | None,
           invite_id: str | None = None, registration: dict | None = None) -> dict:
    """Rate-limit, store a code and (when `purpose` is set) email it. purpose None: store an unknowable code."""
    conn.execute("DELETE FROM email_signin_codes WHERE created_at < now() - interval '1 day'")
    ip = _client_ip(request)
    recent = conn.execute(
        """
        SELECT count(*) FILTER (WHERE email = %s) AS by_email, count(*) FILTER (WHERE requested_ip = %s) AS by_ip
        FROM email_signin_codes WHERE created_at > now() - interval '1 hour'
        """,
        (email, ip),
    ).fetchone()
    if recent["by_email"] >= MAX_PER_EMAIL_PER_HOUR or recent["by_ip"] >= MAX_PER_IP_PER_HOUR:
        raise HTTPException(429, "Too many codes requested. Please wait a while and try again.")
    # A new code replaces any earlier one for this address.
    conn.execute("UPDATE email_signin_codes SET used_at = now() WHERE email = %s AND used_at IS NULL", (email,))
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    conn.execute(
        """
        INSERT INTO email_signin_codes (email, salt, code_hash, purpose, invite_id, registration, delivered,
                                        requested_ip, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (email, salt, _hash(salt, code), purpose or "sign_in", invite_id,
         Jsonb(registration) if registration else None, purpose is not None, ip,
         datetime.now(timezone.utc) + CODE_TTL),
    )
    if purpose is not None:
        invite_core.deliver_email(
            conn, to=email, title=f"{code} is your Bioverse One sign-in code", link="/signin",
            body=(f"Your Bioverse One sign-in code is {code}.\n\nIt works once and expires in "
                  f"{SENT['expires_in_minutes']} minutes. If you didn't ask for it, you can ignore this email."),
            background=background,
        )
    return SENT | {"dev_outbox": demo_allowed()}


class Start(BaseModel):
    email: str
    invite: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return normalize_email(v)


@router.post("/email/start", dependencies=[WebClient])
def start(body: Start, request: Request, background: BackgroundTasks, conn: DbConn) -> dict:
    _require_enabled()
    user = _user_by_email(conn, body.email)
    purpose, invite_id = None, None
    if user is not None:
        # Existing accounts: only patients sign in by email code. Staff and clinicians use single sign-on.
        if user["role"] == "patient" and not user["disabled"]:
            purpose = "sign_in"
    elif body.invite:
        invite = invite_core.claimable(conn, body.invite)
        if invite is not None:
            purpose, invite_id = "invite", invite["id"]
    return _issue(conn, request, background, email=body.email, purpose=purpose, invite_id=invite_id)


class Verify(BaseModel):
    email: str
    code: str = Field(min_length=1, max_length=12)
    invite: str | None = Field(default=None, max_length=200)
    next: str | None = Field(default=None, max_length=300)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return normalize_email(v)


def _consume(conn: Connection, email: str, code: str) -> dict:
    """The matching code row, marked used. Wrong codes count against the code; failures look the same."""
    row = conn.execute(
        """
        SELECT id::text, salt, code_hash, purpose, invite_id::text, registration, attempts
        FROM email_signin_codes
        WHERE email = %s AND used_at IS NULL AND expires_at > now()
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE
        """,
        (email,),
    ).fetchone()
    if row is None:
        raise HTTPException(400, BAD_CODE)
    if row["attempts"] >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many tries. Ask for a new code.")
    code = "".join(ch for ch in code if ch.isdigit())
    if not hmac.compare_digest(_hash(row["salt"], code), row["code_hash"]):
        attempts = row["attempts"] + 1
        conn.execute("UPDATE email_signin_codes SET attempts = %s WHERE id = %s", (attempts, row["id"]))
        conn.commit()  # the failed try counts even though this request fails
        if attempts >= MAX_ATTEMPTS:
            raise HTTPException(429, "Too many tries. Ask for a new code.")
        raise HTTPException(400, BAD_CODE)
    conn.execute("UPDATE email_signin_codes SET used_at = now() WHERE id = %s", (row["id"],))
    return row


def _new_self_registered(conn: Connection, email: str, reg: dict) -> str:
    org = conn.execute("SELECT id::text FROM organizations ORDER BY created_at LIMIT 1").fetchone()
    if org is None:
        raise HTTPException(503, "Registration isn't available")
    user_id = conn.execute(
        "INSERT INTO users (role, display_name, email, organization_id) VALUES ('patient', %s, %s, %s) RETURNING id::text",
        (reg["name"], email, org["id"]),
    ).fetchone()["id"]
    patient = register_patient(conn, organization_id=org["id"], user_id=user_id, name=reg["name"],
                               birth_date=date.fromisoformat(reg["birth_date"]), email=email, source="self",
                               actor_id=user_id)
    audit.record(conn, action="patient.self_register", entity_type="user", entity_id=user_id, agent="email",
                 patient_id=patient.get("patient_id"), detail={"patient": patient.get("how")})
    return user_id


@router.post("/email/verify", dependencies=[WebClient])
def verify(body: Verify, request: Request, conn: DbConn) -> JSONResponse:
    _require_enabled()
    row = _consume(conn, body.email, body.code)
    user = _user_by_email(conn, body.email)
    if user is not None:
        if user["role"] != "patient" or user["disabled"]:
            raise HTTPException(400, BAD_CODE)
        user_id, how = user["id"], "matched_email"
    elif row["purpose"] == "invite":
        invite = invite_core.claimable(conn, None, invite_id=row["invite_id"])
        if invite is None:
            raise HTTPException(410, "This invite has expired or the date-of-birth check needs doing again. "
                                     "Open the invite link again.")
        user_id, _ = invite_core.accept(conn, invite, email=body.email, via="email")
        how = "invite"
    elif row["purpose"] == "register" and self_registration_enabled() and row["registration"]:
        user_id, how = _new_self_registered(conn, body.email, row["registration"]), "self_registered"
    else:
        raise HTTPException(400, BAD_CODE)

    token = sessions.create(conn, user_id=user_id, provider="email", id_token=None,
                            user_agent=request.headers.get("user-agent"))
    audit.record(conn, action="auth.sign_in", entity_type="user", entity_id=user_id, agent="email",
                 detail={"provider": "email", "how": how})
    resp = JSONResponse({"ok": True, "next": _safe_next(body.next)})
    resp.set_cookie(sessions.SESSION_COOKIE, token, max_age=sessions.max_hours() * 3600, httponly=True,
                    secure=sessions.cookie_secure(), samesite="lax", path="/")
    return resp


@router.get("/dev-outbox")
def dev_outbox(email: str, conn: DbConn) -> dict:
    """Demo and development only: recent email the app sent (or would have sent) to an address."""
    if not demo_allowed():
        raise HTTPException(404, "Not found")
    rows = conn.execute(
        """
        SELECT subject, body, link, status, detail, created_at FROM dev_outbox
        WHERE lower(to_address) = %s AND created_at > now() - interval '1 hour'
        ORDER BY created_at DESC, id DESC LIMIT 5
        """,
        (email.strip().lower(),),
    ).fetchall()
    return {"messages": rows}


# --- Open self-registration (off unless BIOVERSE_SELF_REGISTRATION=on) -------------------------------------------


def _require_registration() -> None:
    if not (self_registration_enabled() and email_signin_enabled()):
        raise HTTPException(404, "Not found")


@router.get("/register")
def registration_config() -> dict:
    _require_registration()
    return {"enabled": True}


class Register(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    birth_date: date
    email: str
    accept_terms: bool

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("birth_date")
    @classmethod
    def check_dob(cls, v: date) -> date:
        if v > date.today() or v.year < 1900:
            raise ValueError("Enter a real date of birth")
        return v


@router.post("/register", dependencies=[WebClient])
def register(body: Register, request: Request, background: BackgroundTasks, conn: DbConn) -> dict:
    """Emails a code; the account is created only when the code is verified. Same answer for any address."""
    _require_registration()
    if not body.accept_terms:
        raise HTTPException(422, "Please accept the terms and privacy notice to continue")
    user = _user_by_email(conn, body.email)
    if user is None:
        return _issue(conn, request, background, email=body.email, purpose="register",
                      registration={"name": body.name.strip(), "birth_date": body.birth_date.isoformat()})
    # Already registered: a patient gets an ordinary sign-in code; anyone else gets nothing.
    ok = user["role"] == "patient" and not user["disabled"]
    return _issue(conn, request, background, email=body.email, purpose="sign_in" if ok else None)
