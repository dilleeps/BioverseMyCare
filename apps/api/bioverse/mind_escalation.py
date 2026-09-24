"""Putting wellbeing items in front of the care team: a review item plus a notification to the clinician.

Used by the mood and anxiety checks (routers/mind.py), the mood journal and the weight coach's eating
screen (routers/weight.py). Notification titles leave the app by email and text, so they never carry
clinical detail; the detail sits behind the link.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg import Connection

from bioverse import audit
from bioverse.auth import User
from bioverse.notify import notify

log = logging.getLogger(__name__)


def care_team_practitioner(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    """The clinician on the patient's active care plan, else the first clinician with an account in their organization."""
    row = conn.execute(
        """
        SELECT pr.id::text, pr.user_id::text FROM care_plans c JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s AND c.status = 'active' ORDER BY c.started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT pr.id::text, pr.user_id::text FROM practitioners pr JOIN patients p ON p.organization_id = pr.organization_id
            WHERE p.id = %s AND pr.user_id IS NOT NULL ORDER BY pr.name LIMIT 1
            """,
            (patient_id,),
        ).fetchone()
    return row


def raise_review(
    conn: Connection,
    *,
    patient_id: str,
    kind: str,
    title: str,
    body: str,
    link: str,
    priority: str,
    actor: User | None,
    agent: str,
    ref_id: str | None = None,
    notify_title: str,
    detail: dict[str, Any] | None = None,
) -> str | None:
    """Create the review item and notify the clinician. Returns the review item id, or None if there is no
    care team to reach. Runs in a savepoint so a failure here never undoes what the patient just saw."""
    try:
        with conn.transaction():
            pr = care_team_practitioner(conn, patient_id)
            if pr is None:
                return None
            item = conn.execute(
                """
                INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
                """,
                (kind, patient_id, pr["id"], ref_id, title[:200], body[:4000], priority, link),
            ).fetchone()
            if pr["user_id"]:
                urgent = priority == "urgent"
                notify(conn, user_id=pr["user_id"], kind="wellbeing_review", title=notify_title,
                       body="Open Bioverse to see the details.", link=link, patient_id=patient_id,
                       priority="urgent" if urgent else "normal",
                       channels=["in_app", "email", "sms"] if urgent else ["in_app"],
                       dedupe_key=f"review:{item['id']}")
            audit.record(conn, action="wellbeing_review_raised", entity_type="review_item", entity_id=item["id"],
                         actor=actor, agent=agent, patient_id=patient_id,
                         detail={"kind": kind, "priority": priority, **(detail or {})})
            return item["id"]
    except Exception:  # noqa: BLE001 - the patient-facing response must still go out
        log.exception("could not raise %s review for patient %s", kind, patient_id)
        return None


def own_open_item(conn: Connection, item_id: str, user: User, kinds: tuple[str, ...]) -> dict[str, Any]:
    """A review item of one of `kinds`, assigned to this clinician and still open, locked for update."""
    from fastapi import HTTPException, status

    item = conn.execute(
        """
        SELECT id::text, kind, patient_id::text, ref_id::text, status, practitioner_id::text
        FROM review_items WHERE id::text = %s FOR UPDATE
        """,
        (item_id,),
    ).fetchone()
    if item is None or item["kind"] not in kinds or item["practitioner_id"] != user.practitioner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review item not found")
    if item["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already resolved")
    return item


def resolve_item(conn: Connection, item: dict[str, Any], user: User, resolution: str) -> None:
    conn.execute(
        """
        UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now()
        WHERE id = %s
        """,
        (resolution[:2000], user.id, item["id"]),
    )
    audit.record(conn, action="review_item_resolved", entity_type="review_item", entity_id=item["id"], actor=user,
                 patient_id=item["patient_id"], detail={"kind": item["kind"], "resolution": resolution[:200]})
