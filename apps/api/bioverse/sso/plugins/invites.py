"""Patient invites: the link a clinic sends, the date-of-birth check, and turning an invite into an account.

An invite is a single-use random token (only its SHA-256 is stored) tied to a name, date of birth and email.
The patient opens {PUBLIC_URL}/join/{token}, confirms their date of birth (five wrong tries lock the invite)
and then signs in with a configured provider (`/api/auth/login/google?invite={token}`) or an email code.

The provisioner below runs when that sign-in matches no existing user: if the invite's date of birth was
confirmed in the last 30 minutes it creates the patient's account and record. The verified email they sign in
with may differ from the invited address (people often use a personal Gmail); both are recorded.

Also here: `deliver_email`, which sends through bioverse.channels (respecting BIOVERSE_OUTBOUND_ALLOWLIST) and,
while demo sign-in is allowed, keeps a copy in the development outbox so demos work without a mail server.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from psycopg import Connection

from bioverse import audit, channels
from bioverse.patient_registry import register_patient
from bioverse.sso import hooks
from bioverse.sso.providers import SSOError, demo_allowed

DEFAULT_TTL_DAYS = 14
MAX_DOB_ATTEMPTS = 5
DOB_CONFIRM_WINDOW = timedelta(minutes=30)
MRN_SYSTEM = "urn:bioverse:org:{org}:mrn"


def new_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link_path(token: str) -> str:
    return f"/join/{token}"


def expire_stale(conn: Connection, organization_id: str | None = None) -> None:
    conn.execute(
        "UPDATE patient_invites SET status = 'expired' WHERE status = 'pending' AND expires_at <= now()"
        + (" AND organization_id = %s" if organization_id else ""),
        (organization_id,) if organization_id else (),
    )


def find(conn: Connection, token: str | None, *, lock: bool = False, invite_id: str | None = None) -> dict | None:
    """An invite by its link token (or, internally, by id)."""
    if invite_id:
        where, key = "i.id::text = %s", invite_id
    elif token and len(token) <= 200:
        where, key = "i.token_hash = %s", hash_token(token)
    else:
        return None
    return conn.execute(
        """
        SELECT i.id::text AS id, i.organization_id::text AS organization_id, i.email, i.name, i.birth_date,
               i.mrn, i.mrn_system, i.message, i.status, i.expires_at, i.dob_attempts, i.locked_at,
               i.dob_confirmed_at, i.terms_accepted_at, o.name AS clinic,
               inviter.display_name AS invited_by_name, inviter.role AS invited_by_role
        FROM patient_invites i
        JOIN organizations o ON o.id = i.organization_id
        LEFT JOIN users inviter ON inviter.id = i.invited_by
        WHERE """ + where + (" FOR UPDATE OF i" if lock else ""),
        (key,),
    ).fetchone()


def state(invite: dict, now: datetime | None = None) -> str:
    """pending | locked | expired | accepted | revoked, as the join page shows it."""
    now = now or datetime.now(timezone.utc)
    if invite["status"] != "pending":
        return invite["status"]
    if invite["expires_at"] <= now:
        return "expired"
    if invite["locked_at"] is not None:
        return "locked"
    return "pending"


def dob_confirmed(invite: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return (state(invite, now) == "pending" and invite["dob_confirmed_at"] is not None
            and invite["terms_accepted_at"] is not None and invite["dob_confirmed_at"] > now - DOB_CONFIRM_WINDOW)


def claimable(conn: Connection, token: str | None, *, invite_id: str | None = None) -> dict | None:
    """The invite, locked for update, when it may be accepted right now; otherwise None."""
    invite = find(conn, token, lock=True, invite_id=invite_id)
    return invite if invite and dob_confirmed(invite) else None


def accept(conn: Connection, invite: dict, *, email: str, via: str) -> tuple[str, dict]:
    """Create the patient's account and record from an invite. Returns (user_id, register_patient result)."""
    email = email.strip().lower()
    user_id = conn.execute(
        "INSERT INTO users (role, display_name, email, organization_id) VALUES ('patient', %s, %s, %s) RETURNING id::text",
        (invite["name"], email, invite["organization_id"]),
    ).fetchone()["id"]
    identifiers = None
    if invite["mrn"]:
        identifiers = [{"system": invite["mrn_system"] or MRN_SYSTEM.format(org=invite["organization_id"]),
                        "value": invite["mrn"]}]
    patient = register_patient(conn, organization_id=invite["organization_id"], user_id=user_id, name=invite["name"],
                               birth_date=invite["birth_date"], email=email, identifiers=identifiers,
                               source="invite", actor_id=user_id)
    conn.execute(
        """
        UPDATE patient_invites SET status = 'accepted', accepted_at = now(), accepted_user_id = %s,
               accepted_patient_id = %s, accepted_email = %s, accepted_via = %s
        WHERE id = %s
        """,
        (user_id, patient.get("patient_id"), email, via, invite["id"]),
    )
    audit.record(conn, action="invite.accept", entity_type="patient_invite", entity_id=invite["id"],
                 agent=f"sso/{via}", patient_id=patient.get("patient_id"),
                 detail={"invited_email": invite["email"], "signed_in_email": email, "via": via,
                         "user_id": user_id, "patient": patient.get("how")})
    return user_id, patient


@hooks.provisioner
def provision_from_invite(conn: Connection, provider, identity, context: dict) -> tuple[str, str] | None:
    token = (context or {}).get("invite")
    if not token:
        return None
    invite = claimable(conn, token)
    if invite is None:
        # The person came from an invite link, so "not registered" would be misleading.
        found = find(conn, token)
        code = "invite_unconfirmed" if found and state(found) == "pending" else "invite_invalid"
        raise SSOError(code, f"invite {found['id'] if found else 'unknown'} not claimable")
    user_id, _ = accept(conn, invite, email=identity.email, via=provider.key)
    return user_id, "invite"


# --- Outbound email -----------------------------------------------------------------------------------------


def deliver_email(conn: Connection, *, to: str, title: str, body: str, link: str | None,
                  background: BackgroundTasks | None = None) -> channels.Result:
    """Send through the email channel (SMTP, allowlist). `title` is what the real email shows, so it carries
    anything the recipient needs (a code); `body` is the fuller text kept in the development outbox.

    With `background`, the real send happens after the response, so response time says nothing about the
    recipient (used for sign-in codes). Demo deployments send inline and keep a copy in dev_outbox."""
    if background is not None and not demo_allowed():
        background.add_task(channels.send_email, to, title, link)
        return channels.Result("queued")
    result = channels.send_email(to, title, link)
    if demo_allowed():
        conn.execute(
            """
            INSERT INTO dev_outbox (channel, to_address, subject, body, link, status, detail)
            VALUES ('email', %s, %s, %s, %s, %s, %s)
            """,
            (to, f"Bioverse One: {title}", body, channels.public_url(link) if link else None, result.status,
             result.detail),
        )
    return result
