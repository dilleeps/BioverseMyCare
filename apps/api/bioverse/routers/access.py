"""People and sign-in: who can use Bioverse One, with which email, and their linked SSO accounts. Admins only."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from bioverse import audit, people
from bioverse.auth import Admin
from bioverse.db import DbConn
from bioverse.sso import providers, sessions

router = APIRouter(prefix="/api/admin/users", tags=["access"])


def _email(v: str | None) -> str | None:
    return people.normalize_email(v)


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
    try:
        person = people.create_person(
            conn, organization_id=admin.organization_id, display_name=body.display_name, email=body.email,
            role=body.role, team=body.team, specialty=body.specialty, location_name=body.location_name,
            birth_date=body.birth_date, consult_fee_dollars=body.consult_fee_dollars, actor=admin, source="admin",
        )
    except people.PersonError as exc:
        raise HTTPException(exc.status, exc.message) from None
    user_id, patient = person["id"], person.get("patient")
    audit.record(conn, action="access.user_create", entity_type="user", entity_id=user_id, actor=admin,
                 detail={"role": body.role, "team": body.team} | ({"patient": patient["how"]} if patient else {}))
    return {"id": user_id} | ({"patient": patient} if patient else {})


# --- Bulk import and export (CSV) ------------------------------------------------------------------------


def _csv_response(text: str, filename: str) -> Response:
    return Response(content=text, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@router.get("/import/template")
def import_template(admin: Admin) -> Response:
    return _csv_response(people.template_csv(), "bioverse-people-template.csv")


class ImportRequest(BaseModel):
    csv: str
    dry_run: bool = True
    # Import the good rows and report the rest, instead of importing nothing when any row has a problem.
    skip_errors: bool = False
    # For emails that already have an account: update a staff member's team instead of skipping them.
    update_existing: bool = False


def _import_report(parsed: people.ParsedCsv, plans: list[people.RowPlan], *, dry_run: bool, committed: bool) -> dict:
    return {
        "dry_run": dry_run, "committed": committed,
        "rows": [p.public(dry_run) for p in plans],
        "totals": people.totals(plans),
        "blocking": people.blocking(plans),
        "ignored_columns": parsed.ignored_columns,
        "columns": sorted(parsed.columns, key=parsed.columns.get),
    }


@router.post("/import")
def import_users(body: ImportRequest, conn: DbConn, admin: Admin) -> dict:
    """Dry run first (the default): what each row would do. Then dry_run=false imports in one transaction,
    all or nothing unless skip_errors."""
    try:
        parsed = people.parse_csv(body.csv)
    except people.PersonError as exc:
        raise HTTPException(exc.status, exc.message) from None
    plans = people.plan_import(conn, parsed, organization_id=admin.organization_id,
                               update_existing=body.update_existing)
    if body.dry_run:
        return _import_report(parsed, plans, dry_run=True, committed=False)

    def refuse() -> None:
        n = people.blocking(plans)
        raise HTTPException(422, {
            "message": f"{n} row{'s' if n != 1 else ''} need{'s' if n == 1 else ''} fixing, so nobody was imported. "
                       "Fix them, or choose to skip rows with problems.",
            "report": _import_report(parsed, plans, dry_run=False, committed=False),
        })

    if people.blocking(plans) and not body.skip_errors:
        refuse()
    people.apply_import(conn, plans, organization_id=admin.organization_id, actor=admin)
    if people.blocking(plans) and not body.skip_errors:
        refuse()                            # a row failed while saving: the whole import rolls back
    t = people.totals(plans)
    created_roles: dict[str, int] = {}
    for p in plans:
        if p.status == "create":
            created_roles[p.role] = created_roles.get(p.role, 0) + 1
    audit.record(conn, action="access.bulk_import", entity_type="organization", entity_id=admin.organization_id,
                 actor=admin, detail={
                     "rows": t["rows"], "created": t["create"], "updated": t["update"], "skipped": t["skip"],
                     "duplicates": t["duplicate"], "errors": t["error"], "created_by_role": created_roles,
                     "skip_errors": body.skip_errors, "update_existing": body.update_existing})
    return _import_report(parsed, plans, dry_run=False, committed=True)


EXPORT_COLUMNS = ("name", "email", "role", "team", "specialty", "disabled", "last_sign_in", "linked_providers")


@router.get("/export.csv")
def export_users(conn: DbConn, admin: Admin) -> Response:
    rows = conn.execute(
        """
        SELECT u.display_name, u.email, u.role, u.team, pr.specialty, u.disabled,
               (SELECT max(last_login_at) FROM user_identities i WHERE i.user_id = u.id) AS last_sign_in,
               (SELECT string_agg(DISTINCT i.provider, ' ') FROM user_identities i WHERE i.user_id = u.id) AS providers
        FROM users u
        LEFT JOIN practitioners pr ON pr.user_id = u.id
        WHERE u.organization_id = %s OR u.organization_id IS NULL
        ORDER BY u.role, u.display_name
        """,
        (admin.organization_id,),
    ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(EXPORT_COLUMNS)
    for r in rows:
        w.writerow([people.safe_cell(v) for v in (
            r["display_name"], r["email"], r["role"], r["team"], r["specialty"], "yes" if r["disabled"] else "no",
            r["last_sign_in"].isoformat(timespec="seconds") if r["last_sign_in"] else "", r["providers"])])
    audit.record(conn, action="access.export", entity_type="organization", entity_id=admin.organization_id,
                 actor=admin, detail={"rows": len(rows)})
    # The byte order mark lets spreadsheet apps read names with accents as UTF-8.
    return _csv_response("﻿" + buf.getvalue(), f"bioverse-people-{date.today().isoformat()}.csv")


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
            people.sync_pharmacy_staff(conn, user_id, row["organization_id"], row["team"] if row["role"] == "staff" else None)
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
