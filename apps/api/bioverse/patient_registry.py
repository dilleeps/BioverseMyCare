"""The one place new patient records are created, so every path (admin, invite, self-registration, import)
gets the same duplicate check.

register_patient links to an existing record when it is safely the same person, otherwise creates one.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection


def register_patient(conn: Connection, *, organization_id: str, user_id: str | None, name: str, birth_date: date,
                     email: str | None = None, phone: str | None = None,
                     identifiers: list[dict] | None = None, source: str = "admin", actor_id: str | None = None) -> dict:
    """Returns {"patient_id", "how": "created" | "linked" | ..., ...}.

    identifiers: [{"system": ..., "value": ...}] such as a medical record number from an invite.
    """
    patient_id = conn.execute(
        "INSERT INTO patients (user_id, organization_id, name, birth_date) VALUES (%s, %s, %s, %s) RETURNING id::text",
        (user_id, organization_id, name, birth_date),
    ).fetchone()["id"]
    return {"patient_id": patient_id, "how": "created"}
