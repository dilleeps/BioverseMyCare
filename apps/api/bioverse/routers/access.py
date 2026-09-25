"""People and sign-in: who can use Bioverse One, with which email, and their linked SSO accounts. Admins only."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from bioverse import audit
from bioverse.patient_registry import register_patient
from bioverse.auth import Admin
from bioverse.db import DbConn
from bioverse.sso import providers, sessions

router = APIRouter(prefix="/api/admin/users", tags=["access"])


def _email(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v or len(v) > 200:
        raise ValueError("That doesn't look like an email address")
    return v


@router.get("")
def list_users(conn: DbConn, admin: Admin) -> dict:
    users = conn.execute(
        """
        SELECT u.id::text, u.display_name, u.email, u.role, u.team, u.disabled, u.demo_label,
               pr.specialty, (p.id IS NOT NULL) AS is_patient,
               (SELECT max(last_login_at) FROM user_identities i WHERE i.user_id = u.id) AS last_login_at,
               (SELECT count(*) FROM auth_sessions s WHERE s.user_id = u.id AND s.revoked_at IS NULL
                  AND s.expires_at > now()) AS active_sessions,
               coalesce((SELECT json_agg(json_build_object('id', i.id, 'provider', i.provider, 'email', i.email,
                                                           'last_login_at', i.last_login_at) ORDER BY i.provider)
                         FROM user_identities i WHERE i.user_id = u.id), '[]') AS identities
        FROM users u
        LEFT JOIN practitioners pr ON pr.user_id = u.id
        LEFT JOIN patients p ON p.user_id = u.id
        WHERE u.organization_id = %s OR u.organization_id IS NULL
        ORDER BY u.role, u.display_name
        """,
        (admin.organization_id,),
    ).fetchall()
    return {
        "users": users,
        "mode": providers.auth_mode(),
        "providers": [{"key": p.key, "label": p.label} for p in providers.configured().values()],
    }


class NewUser(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    email: str
    role: Literal["admin", "staff", "clinician", "patient", "student"]
    team: Literal["front_desk", "pharmacy"] | None = None
    specialty: str | None = Field(default=None, max_length=80)
    consult_fee_dollars: int | None = Field(default=None, ge=0, le=2000)
    location_name: str | None = Field(default=None, max_length=120)
    birth_date: date | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _email(v)


@router.post("", status_code=201)
def create_user(body: NewUser, conn: DbConn, admin: Admin) -> dict:
    if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (body.email,)).fetchone():
        raise HTTPException(409, "Someone already uses that email")
    if body.role == "clinician" and not body.specialty:
        raise HTTPException(422, "A clinician needs a specialty")
    if body.role == "patient" and not body.birth_date:
        raise HTTPException(422, "A patient needs a date of birth")
    user_id = conn.execute(
        "INSERT INTO users (role, display_name, email, organization_id, team) VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
        (body.role, body.display_name, body.email, admin.organization_id, body.team if body.role == "staff" else None),
    ).fetchone()["id"]
    if body.role == "clinician":
        practitioner_id = conn.execute(
            "INSERT INTO practitioners (user_id, organization_id, name, specialty, location_name) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, admin.organization_id, body.display_name, body.specialty, body.location_name or "Main clinic"),
        ).fetchone()["id"]
        # Online consult profile; they appear in the directory once their license is verified.
        conn.execute(
            "INSERT INTO consult_profiles (practitioner_id, modes, fee_cents) VALUES (%s, '{message,video}', %s)",
            (practitioner_id, (body.consult_fee_dollars or 0) * 100),
        )
    if body.role == "staff":
        _sync_pharmacy_staff(conn, user_id, admin.organization_id, body.team)
    patient = None
    if body.role == "patient":
        patient = register_patient(conn, organization_id=admin.organization_id, user_id=user_id,
                                   name=body.display_name, birth_date=body.birth_date, email=body.email,
                                   source="admin", actor_id=admin.id)
    audit.record(conn, action="access.user_create", entity_type="user", entity_id=user_id, actor=admin,
                 detail={"role": body.role, "team": body.team} | ({"patient": patient["how"]} if patient else {}))
    return {"id": user_id} | ({"patient": patient} if patient else {})


class UserPatch(BaseModel):
    email: str | None = None
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: Literal["admin", "staff"] | None = None
    team: Literal["front_desk", "pharmacy", "none"] | None = None
    disabled: bool | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return _email(v)


def _sync_pharmacy_staff(conn, user_id: str, org_id: str, team: str | None) -> None:
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


def _target(conn, admin, user_id: str) -> dict:
    row = conn.execute(
        "SELECT id::text, role FROM users WHERE id::text = %s AND (organization_id = %s OR organization_id IS NULL)",
        (user_id, admin.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "User not found")
    return row


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserPatch, conn: DbConn, admin: Admin) -> dict:
    target = _target(conn, admin, user_id)
    changes = body.model_dump(exclude_none=True)
    if user_id == admin.id and (changes.get("disabled") or changes.get("role", "admin") != "admin"):
        raise HTTPException(409, "You can't turn off or demote your own account")
    if "role" in changes and target["role"] not in ("admin", "staff"):
        raise HTTPException(409, "Only administrator and staff roles can be switched here")
    if "email" in changes and conn.execute(
            "SELECT 1 FROM users WHERE lower(email) = %s AND id::text <> %s", (changes["email"], user_id)).fetchone():
        raise HTTPException(409, "Someone already uses that email")
    sets, params = [], []
    for col in ("email", "display_name", "role", "disabled"):
        if col in changes:
            sets.append(f"{col} = %s")
            params.append(changes[col])
    if "team" in changes:
        sets.append("team = %s")
        params.append(None if changes["team"] == "none" else changes["team"])
    if sets:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id::text = %s", (*params, user_id))
    if "team" in changes or "role" in changes:
        row = conn.execute("SELECT role, team, organization_id::text FROM users WHERE id::text = %s", (user_id,)).fetchone()
        if row["role"] == "staff" or row["team"] is None:
            _sync_pharmacy_staff(conn, user_id, row["organization_id"], row["team"] if row["role"] == "staff" else None)
    if changes.get("disabled"):
        sessions.revoke_all(conn, user_id)
    audit.record(conn, action="access.user_update", entity_type="user", entity_id=user_id, actor=admin,
                 detail={k: v for k, v in changes.items() if k != "email"} | ({"email_changed": True} if "email" in changes else {}))
    return {"ok": True}


@router.delete("/{user_id}/identities/{identity_id}")
def unlink_identity(user_id: str, identity_id: str, conn: DbConn, admin: Admin) -> dict:
    _target(conn, admin, user_id)
    row = conn.execute(
        "DELETE FROM user_identities WHERE id::text = %s AND user_id::text = %s RETURNING provider",
        (identity_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Linked account not found")
    sessions.revoke_all(conn, user_id)
    audit.record(conn, action="access.identity_unlink", entity_type="user", entity_id=user_id, actor=admin,
                 detail={"provider": row["provider"]})
    return {"ok": True}


@router.post("/{user_id}/sign-out")
def sign_out_everywhere(user_id: str, conn: DbConn, admin: Admin) -> dict:
    _target(conn, admin, user_id)
    n = sessions.revoke_all(conn, user_id)
    audit.record(conn, action="access.sessions_revoke", entity_type="user", entity_id=user_id, actor=admin,
                 detail={"sessions": n})
    return {"revoked": n}
