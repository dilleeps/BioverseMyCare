"""Identity and access control.

DEMO IDENTITY ONLY. The caller names who they are in the `X-Bioverse-User` header,
which is fine for a local demo and unacceptable anywhere real patient data exists.
Replace `current_user` with OIDC/SAML verification (docs/04-safety-and-governance.md)
before any deployment. Every access check below stays the same when you do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from psycopg import Connection

from bioverse.db import DbConn


@dataclass(frozen=True)
class User:
    id: str
    role: str
    display_name: str
    organization_id: str
    patient_id: str | None
    practitioner_id: str | None


def current_user(
    conn: DbConn,
    x_bioverse_user: Annotated[str | None, Header()] = None,
) -> User:
    if not x_bioverse_user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Bioverse-User header")
    try:
        UUID(x_bioverse_user)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user") from None

    row = conn.execute(
        """
        SELECT u.id::text, u.role, u.display_name, u.organization_id::text,
               p.id::text AS patient_id, pr.id::text AS practitioner_id
        FROM users u
        LEFT JOIN patients p ON p.user_id = u.id
        LEFT JOIN practitioners pr ON pr.user_id = u.id
        WHERE u.id = %s
        """,
        (x_bioverse_user,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return User(
        id=row["id"],
        role=row["role"],
        display_name=row["display_name"],
        organization_id=row["organization_id"],
        patient_id=row["patient_id"],
        practitioner_id=row["practitioner_id"],
    )


CurrentUser = Annotated[User, Depends(current_user)]


def require_clinician(user: CurrentUser) -> User:
    if user.role != "clinician" or not user.practitioner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinician access required")
    return user


Clinician = Annotated[User, Depends(require_clinician)]


def assert_patient_access(conn: Connection, user: User, patient_id: str) -> None:
    """Patients see only themselves. Clinicians and staff see patients in their organization."""
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
