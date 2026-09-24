"""Patient consent: one record per patient, scope and (optional) grantee. Every change is audited.

Known scopes (add yours here when a module introduces one):

    ai_processing       AI may process this patient's messages. Granted unless the patient opts out;
                        when denied, every agent must use its rules path.
    research_matching   The patient may be matched to research studies and contacted about them.
                        Denied unless the patient opts in.
    caregiver_access    A named person (grantee = their user id) may act on the patient's behalf.
                        `detail.permissions` lists what they may see or do. Denied unless granted.
                        Managed from /family.
    caregiver_results_adolescent
                        A 13-17 year old's own agreement that a caregiver may see their results
                        (grantee = caregiver user id). Required in addition to caregiver_access.

The Privacy Center (/privacy) lets patients change ai_processing and research_matching;
research_matching is also managed from /research, where revoking it pauses study contact.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg import Connection

from bioverse import audit
from bioverse.auth import User

# What a scope means when the patient has never decided.
DEFAULTS = {
    "ai_processing": True,
    "research_matching": False,
    "caregiver_access": False,
    "caregiver_results_adolescent": False,
}


def get(conn: Connection, patient_id: str, scope: str, grantee: str = "") -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text, scope, grantee, status, detail, expires_at, updated_at
        FROM consents WHERE patient_id = %s AND scope = %s AND grantee = %s
        """,
        (patient_id, scope, grantee),
    ).fetchone()


def is_granted(conn: Connection, patient_id: str, scope: str, grantee: str = "") -> bool:
    row = get(conn, patient_id, scope, grantee)
    if row is None:
        return DEFAULTS.get(scope, False)
    if row["status"] != "granted":
        return False
    expires = row["expires_at"]
    return expires is None or expires > datetime.now(expires.tzinfo)


def ai_allowed(conn: Connection, patient_id: str) -> bool:
    return is_granted(conn, patient_id, "ai_processing")


def set_status(
    conn: Connection,
    *,
    patient_id: str,
    scope: str,
    status: str,
    actor: User | None,
    grantee: str = "",
    detail: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    if status not in ("granted", "denied", "revoked"):
        raise ValueError(f"bad consent status {status!r}")
    row = conn.execute(
        """
        INSERT INTO consents (patient_id, scope, grantee, status, detail, expires_at, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (patient_id, scope, grantee) DO UPDATE
          SET status = EXCLUDED.status, detail = EXCLUDED.detail, expires_at = EXCLUDED.expires_at,
              updated_by = EXCLUDED.updated_by, updated_at = now()
        RETURNING id::text, scope, grantee, status, detail, expires_at, updated_at
        """,
        (patient_id, scope, grantee, status, json.dumps(detail or {}), expires_at, actor.id if actor else None),
    ).fetchone()
    audit.record(
        conn,
        action=f"consent_{status}",
        entity_type="consent",
        entity_id=row["id"],
        actor=actor,
        patient_id=patient_id,
        detail={"scope": scope, "grantee": grantee or None},
    )
    return row


def list_for(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id::text, scope, grantee, status, detail, expires_at, updated_at
        FROM consents WHERE patient_id = %s ORDER BY scope, grantee
        """,
        (patient_id,),
    ).fetchall()
