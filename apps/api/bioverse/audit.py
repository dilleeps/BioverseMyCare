"""Append-only audit trail. Every write of patient data and every AI action records here."""

from __future__ import annotations

import json
from typing import Any

from psycopg import Connection

from bioverse.auth import User


def record(
    conn: Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor: User | None = None,
    agent: str | None = None,
    model: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events (actor_user_id, actor_role, agent, model, action, entity_type, entity_id, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            actor.id if actor else None,
            actor.role if actor else "system",
            agent,
            model,
            action,
            entity_type,
            entity_id,
            json.dumps(detail or {}, default=str),
        ),
    )
