"""Patient invites.

Staff side (/api/invites): administrators, front-desk staff and clinicians invite a patient by email, see the
invites they have sent, resend (which issues a new link) and revoke. The link is always returned so staff can
copy it, whether or not email is configured.

Patient side (/api/join/{token}, public): what the join page shows, and the date-of-birth check that must pass
before the invite can be used to sign in. See bioverse/sso/plugins/invites.py for how the account is created.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from bioverse import audit
from bioverse.auth import CurrentUser, User
from bioverse.db import DbConn
from bioverse.sso import providers
from bioverse.sso.plugins import invites as core

router = APIRouter(tags=["invites"])


def require_inviter(user: CurrentUser) -> User:
    """Administrators, clinicians, and staff on the front desk (or with no team) may invite patients."""
    if user.role in ("admin", "clinician") or (user.role == "staff" and user.team in (None, "front_desk")):
        return user
    raise HTTPException(403, "Only administrators, the front desk and clinicians can invite patients")


Inviter = Annotated[User, Depends(require_inviter)]


def require_web_client(request: Request) -> None:
    """Public writes (join, email codes) must come from the Bioverse web app: a cross-site page can't add this
    header without passing CORS, so another site can't drive them (e.g. log someone into the wrong account)."""
    if request.headers.get("x-bioverse-client") != "web":
        raise HTTPException(403, "Missing X-Bioverse-Client header")


WebClient = Depends(require_web_client)


def email_signin_enabled() -> bool:
    """Email one-time codes: BIOVERSE_EMAIL_SIGNIN=on|off; unset follows single sign-on."""
    flag = os.getenv("BIOVERSE_EMAIL_SIGNIN", "").strip().lower()
    if flag in ("on", "true", "1", "yes"):
        return True
    if flag in ("off", "false", "0", "no"):
        return False
    return providers.sso_allowed()


def public_base(request: Request) -> str:
    return (os.getenv("BIOVERSE_PUBLIC_URL") or str(request.base_url)).rstrip("/")


def normalize_email(v: str) -> str:
    v = (v or "").strip().lower()
    if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v or len(v) > 200 or "." not in v.rsplit("@", 1)[-1]:
        raise ValueError("That doesn't look like an email address")
    return v


class NewInvite(BaseModel):
    email: str
    name: str = Field(min_length=2, max_length=120)
    birth_date: date
    mrn: str | None = Field(default=None, max_length=60)
    message: str | None = Field(default=None, max_length=500)
    expires_in_days: int = Field(default=core.DEFAULT_TTL_DAYS, ge=1, le=60)

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


def _send(conn, request: Request, invite_id: str, token: str, *, email: str, name: str, clinic: str,
          inviter: str, message: str | None) -> dict:
    path = core.link_path(token)
    title = f"{clinic} invited you to Bioverse One"
    body = (f"Hi {name.split()[0]},\n\n{inviter} at {clinic} invited you to Bioverse One.\n"
            + (f"\n\"{message}\"\n" if message else "")
            + f"\nOpen this link to join (you'll confirm your date of birth first):\n{public_base(request)}{path}\n")
    res = core.deliver_email(conn, to=email, title=title, body=body, link=path)
    delivery = {"status": res.status, "detail": res.detail, "at": datetime.now(timezone.utc).isoformat()}
    conn.execute(
        """
        UPDATE patient_invites SET sent_at = now(), send_count = send_count + 1, delivery = %s WHERE id = %s
        """,
        (Jsonb(delivery), invite_id),
    )
    return delivery


def _view(row: dict, request: Request, token: str | None = None) -> dict:
    out = {
        "id": row["id"], "email": row["email"], "name": row["name"], "birth_date": row["birth_date"],
        "mrn": row["mrn"], "message": row["message"], "status": row["status"],
        "locked": row["locked_at"] is not None and row["status"] == "pending",
        "expires_at": row["expires_at"], "created_at": row["created_at"], "sent_at": row["sent_at"],
        "send_count": row["send_count"], "delivery": row["delivery"], "invited_by": row["invited_by_name"],
        "accepted_at": row["accepted_at"], "accepted_email": row["accepted_email"], "accepted_via": row["accepted_via"],
    }
    if token:
        out["link"] = f"{public_base(request)}{core.link_path(token)}"
    return out


LIST_SQL = """
    SELECT i.id::text, i.email, i.name, i.birth_date, i.mrn, i.message, i.status, i.locked_at, i.expires_at,
           i.created_at, i.sent_at, i.send_count, i.delivery, u.display_name AS invited_by_name,
           i.accepted_at, i.accepted_email, i.accepted_via
    FROM patient_invites i LEFT JOIN users u ON u.id = i.invited_by
    WHERE i.organization_id = %s
"""


def _get(conn, user: User, invite_id: str, *, lock: bool = False) -> dict:
    row = conn.execute(LIST_SQL + " AND i.id::text = %s" + (" FOR UPDATE OF i" if lock else ""),
                       (user.organization_id, invite_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Invite not found")
    return row


def _clinic(conn, org_id: str) -> str:
    row = conn.execute("SELECT name FROM organizations WHERE id = %s", (org_id,)).fetchone()
    return row["name"] if row else "Your clinic"


@router.post("/api/invites", status_code=201)
def create_invite(body: NewInvite, request: Request, conn: DbConn, user: Inviter) -> dict:
    if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (body.email,)).fetchone():
        raise HTTPException(409, "Someone already signs in with that email. They don't need an invite.")
    core.expire_stale(conn, user.organization_id)
    if conn.execute("SELECT 1 FROM patient_invites WHERE organization_id = %s AND lower(email) = %s AND status = 'pending'",
                    (user.organization_id, body.email)).fetchone():
        raise HTTPException(409, "There's already an open invite for that email. Resend it instead.")
    token = core.new_token()
    mrn = (body.mrn or "").strip() or None
    invite_id = conn.execute(
        """
        INSERT INTO patient_invites (organization_id, token_hash, email, name, birth_date, mrn, mrn_system, message,
                                     expires_at, invited_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (user.organization_id, core.hash_token(token), body.email, body.name.strip(), body.birth_date, mrn,
         core.MRN_SYSTEM.format(org=user.organization_id) if mrn else None, (body.message or "").strip() or None,
         datetime.now(timezone.utc) + timedelta(days=body.expires_in_days), user.id),
    ).fetchone()["id"]
    _send(conn, request, invite_id, token, email=body.email, name=body.name, clinic=_clinic(conn, user.organization_id),
          inviter=user.display_name, message=body.message)
    audit.record(conn, action="invite.create", entity_type="patient_invite", entity_id=invite_id, actor=user,
                 detail={"expires_in_days": body.expires_in_days, "has_mrn": bool(mrn)})
    return _view(_get(conn, user, invite_id), request, token)


@router.get("/api/invites")
def list_invites(request: Request, conn: DbConn, user: Inviter, status: str | None = None) -> dict:
    core.expire_stale(conn, user.organization_id)
    sql, params = LIST_SQL, [user.organization_id]
    if status:
        sql += " AND i.status = %s"
        params.append(status)
    rows = conn.execute(sql + " ORDER BY i.created_at DESC LIMIT 200", params).fetchall()
    return {
        "invites": [_view(r, request) for r in rows],
        "sign_in": {"providers": [p.label for p in providers.configured().values()] if providers.sso_allowed() else [],
                    "email": email_signin_enabled()},
    }


@router.post("/api/invites/{invite_id}/resend")
def resend_invite(invite_id: str, request: Request, conn: DbConn, user: Inviter) -> dict:
    """A new link (the old one stops working), a fresh expiry, and the date-of-birth tries reset."""
    core.expire_stale(conn, user.organization_id)
    row = _get(conn, user, invite_id, lock=True)
    if row["status"] not in ("pending", "expired"):
        raise HTTPException(409, f"This invite was {row['status']}, so it can't be resent")
    token = core.new_token()
    conn.execute(
        """
        UPDATE patient_invites SET token_hash = %s, status = 'pending', expires_at = %s, dob_attempts = 0,
               locked_at = NULL, dob_confirmed_at = NULL, terms_accepted_at = NULL
        WHERE id = %s
        """,
        (core.hash_token(token), datetime.now(timezone.utc) + timedelta(days=core.DEFAULT_TTL_DAYS), invite_id),
    )
    _send(conn, request, invite_id, token, email=row["email"], name=row["name"],
          clinic=_clinic(conn, user.organization_id), inviter=user.display_name, message=row["message"])
    audit.record(conn, action="invite.resend", entity_type="patient_invite", entity_id=invite_id, actor=user,
                 detail={"was": row["status"], "was_locked": row["locked_at"] is not None})
    return _view(_get(conn, user, invite_id), request, token)


@router.post("/api/invites/{invite_id}/revoke")
def revoke_invite(invite_id: str, request: Request, conn: DbConn, user: Inviter) -> dict:
    row = _get(conn, user, invite_id, lock=True)
    if row["status"] == "accepted":
        raise HTTPException(409, "This invite was already used")
    conn.execute("UPDATE patient_invites SET status = 'revoked', revoked_at = now(), revoked_by = %s WHERE id = %s",
                 (user.id, invite_id))
    audit.record(conn, action="invite.revoke", entity_type="patient_invite", entity_id=invite_id, actor=user)
    return _view(_get(conn, user, invite_id), request)


# --- Public: the join page ------------------------------------------------------------------------------------


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}{'•' * max(2, min(len(local) - 1, 6))}@{domain}"


def _public(conn, token: str) -> dict:
    invite = core.find(conn, token)
    if invite is None:
        raise HTTPException(404, "This invite link isn't valid. Check the link or ask your clinic for a new one.")
    return invite


@router.get("/api/join/{token}")
def join_info(token: str, conn: DbConn) -> dict:
    """What the join page shows. No sign-in needed; reveals nothing beyond what the invite email said."""
    invite = _public(conn, token)
    st = core.state(invite)
    out = {"status": st, "clinic": invite["clinic"]}
    if st != "pending":
        return out
    return out | {
        "first_name": invite["name"].split()[0],
        "invited_by": invite["invited_by_name"] or invite["clinic"],
        "message": invite["message"],
        "email_hint": _mask(invite["email"]),
        "expires_at": invite["expires_at"],
        "dob_confirmed": core.dob_confirmed(invite),
        "attempts_left": core.MAX_DOB_ATTEMPTS - invite["dob_attempts"],
        "sign_in": {
            "providers": [{"key": p.key, "label": p.label} for p in providers.configured().values()]
            if providers.sso_allowed() else [],
            "email": email_signin_enabled(),
        },
    }


class Confirm(BaseModel):
    birth_date: date
    accept_terms: bool


@router.post("/api/join/{token}/confirm", dependencies=[WebClient])
def confirm_identity(token: str, body: Confirm, conn: DbConn) -> dict:
    """The date of birth must match the invite. Five wrong tries lock it until the clinic resends."""
    invite = core.find(conn, token, lock=True)
    if invite is None:
        raise HTTPException(404, "This invite link isn't valid.")
    st = core.state(invite)
    if st == "locked":
        raise HTTPException(423, "Too many tries. Ask your clinic to send a new invite.")
    if st != "pending":
        raise HTTPException(410, f"This invite is {st}.")
    if not body.accept_terms:
        raise HTTPException(422, "Please accept the terms and privacy notice to continue")
    if body.birth_date != invite["birth_date"]:
        attempts = invite["dob_attempts"] + 1
        locked = attempts >= core.MAX_DOB_ATTEMPTS
        conn.execute(
            "UPDATE patient_invites SET dob_attempts = %s, locked_at = CASE WHEN %s THEN now() END WHERE id = %s",
            (attempts, locked, invite["id"]),
        )
        audit.record(conn, action="invite.dob_mismatch", entity_type="patient_invite", entity_id=invite["id"],
                     agent="join", detail={"attempts": attempts, "locked": locked})
        # The failed attempt must be saved even though the request fails.
        conn.commit()
        if locked:
            raise HTTPException(423, "Too many tries. Ask your clinic to send a new invite.")
        raise HTTPException(400, {"message": "That date of birth doesn't match our records.",
                                  "attempts_left": core.MAX_DOB_ATTEMPTS - attempts})
    conn.execute(
        "UPDATE patient_invites SET dob_confirmed_at = now(), terms_accepted_at = now() WHERE id = %s",
        (invite["id"],),
    )
    audit.record(conn, action="invite.dob_confirmed", entity_type="patient_invite", entity_id=invite["id"],
                 agent="join", detail={"terms_accepted": True})
    return {"ok": True, "valid_minutes": int(core.DOB_CONFIRM_WINDOW.total_seconds() // 60)}
