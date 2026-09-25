"""Identity and access control.

Two ways to be signed in, chosen by BIOVERSE_AUTH_MODE (bioverse.sso.providers.auth_mode):

- **SSO session** (modes `sso`, `sso+demo`): an opaque `bv_session` cookie set after an OpenID Connect
  sign-in with Microsoft Entra ID, Okta or Google (bioverse/sso). State-changing requests made with the
  cookie must also carry `X-Bioverse-Client: web`, which a cross-site page cannot add without CORS
  permission (CSRF protection on top of SameSite=Lax).
- **Demo header** (modes `demo`, `sso+demo`): the caller names who they are in `X-Bioverse-User`. Fine for a
  local demo, unacceptable anywhere real patient data exists.

Every access check below is the same either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from psycopg import Connection

from bioverse.db import DbConn
from bioverse.sso import sessions as sso_sessions
from bioverse.sso.providers import demo_allowed, sso_allowed


@dataclass(frozen=True)
class User:
    id: str
    role: str
    display_name: str
    organization_id: str
    patient_id: str | None
    practitioner_id: str | None
    team: str | None = None


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _load_user(conn: Connection, user_id: str) -> dict | None:
    return conn.execute(
        """
        SELECT u.id::text, u.role, u.display_name, u.organization_id::text, u.team,
               p.id::text AS patient_id, pr.id::text AS practitioner_id
        FROM users u
        LEFT JOIN patients p ON p.user_id = u.id
        LEFT JOIN practitioners pr ON pr.user_id = u.id
        WHERE u.id = %s AND NOT u.disabled
        """,
        (user_id,),
    ).fetchone()


def current_user(
    request: Request,
    conn: DbConn,
    x_bioverse_user: Annotated[str | None, Header()] = None,
) -> User:
    row = None
    auth = None
    token = request.cookies.get(sso_sessions.SESSION_COOKIE)
    if token and sso_allowed():
        session = sso_sessions.resolve(conn, token)
        if session:
            if request.method in UNSAFE_METHODS and request.headers.get("x-bioverse-client") != "web":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Bioverse-Client header")
            row, auth = _load_user(conn, session["user_id"]), "sso"
    if row is None and x_bioverse_user and demo_allowed():
        try:
            UUID(x_bioverse_user)
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user") from None
        row, auth = _load_user(conn, x_bioverse_user), "demo"
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    request.state.auth = auth
    return User(
        id=row["id"],
        role=row["role"],
        display_name=row["display_name"],
        organization_id=row["organization_id"],
        patient_id=row["patient_id"],
        practitioner_id=row["practitioner_id"],
        team=row["team"],
    )


CurrentUser = Annotated[User, Depends(current_user)]


def require_clinician(user: CurrentUser) -> User:
    if user.role != "clinician" or not user.practitioner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinician access required")
    return user


Clinician = Annotated[User, Depends(require_clinician)]


def require_patient(user: CurrentUser) -> User:
    if user.role != "patient" or not user.patient_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Patient access required")
    return user


Patient = Annotated[User, Depends(require_patient)]


def require_admin(user: CurrentUser) -> User:
    """Organization administrators: hospital operations, configuration, analytics, audit."""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


Admin = Annotated[User, Depends(require_admin)]


def require_staff_or_admin(user: CurrentUser) -> User:
    """Clinicians, staff and admins: anyone working for the organization."""
    if user.role not in ("clinician", "staff", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff access required")
    return user


Workforce = Annotated[User, Depends(require_staff_or_admin)]


def require_student(user: CurrentUser) -> User:
    """Medical students: de-identified teaching material only, never patient records."""
    if user.role != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Medical student access required")
    return user


Student = Annotated[User, Depends(require_student)]


def assert_patient_access(conn: Connection, user: User, patient_id: str) -> None:
    """Patients see only themselves. Clinicians and staff see patients in their organization.
    Medical students never reach an identifiable patient record."""
    if user.role == "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Students work with de-identified cases only")
    if user.role == "patient":
        if user.patient_id != patient_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record")
        return
    row = conn.execute(
        "SELECT 1 FROM patients WHERE id = %s AND organization_id = %s",
        (patient_id, user.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
