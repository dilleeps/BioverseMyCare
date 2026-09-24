"""Notifications: one call from any module, delivered in-app and on the user's chosen channels.

    notify(conn, user_id=..., kind="medication_reminder", title="Time for atorvastatin",
           body="Take 20 mg with your evening meal.", link="/pharmacy", patient_id=...,
           due_at=<when>, dedupe_key="med:<rx id>:2026-09-24T21:00")

- The row is visible in the in-app notification center as soon as `due_at` passes.
- Other channels (email, SMS, push) are attempted by the `dispatch_notifications` job, which respects
  the user's preferences and quiet hours. A channel that isn't configured is recorded as skipped.
- `dedupe_key` makes scheduling idempotent: the same key for the same user is only created once, so
  jobs can safely re-run.
- Clinical content follows the same rules as everywhere else: nothing clinical goes to a patient that a
  clinician hasn't approved. Reminders and logistics are fine; new advice is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import tuple_row

DEFAULT_CHANNELS = ("in_app",)


def notify(
    conn: Connection,
    *,
    user_id: str,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    patient_id: str | None = None,
    priority: str = "normal",
    channels: tuple[str, ...] | list[str] | None = None,
    due_at: datetime | None = None,
    dedupe_key: str | None = None,
    created_by: str = "system",
) -> dict[str, Any] | None:
    """Create a notification. Returns the row, or None when the dedupe key already exists."""
    row = conn.execute(
        """
        INSERT INTO notifications (user_id, patient_id, kind, title, body, link, priority, channels, due_at,
                                   dedupe_key, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s, now()), %s, %s)
        ON CONFLICT (user_id, dedupe_key) DO NOTHING
        RETURNING id::text, kind, title, due_at
        """,
        (user_id, patient_id, kind, title[:200], body[:2000], link, priority,
         list(channels or DEFAULT_CHANNELS), due_at, dedupe_key, created_by),
    ).fetchone()
    return row


def cancel(conn: Connection, *, user_id: str, dedupe_prefix: str) -> int:
    """Cancel pending notifications whose dedupe key starts with a prefix (e.g. a stopped prescription)."""
    cur = conn.execute(
        """
        UPDATE notifications SET status = 'cancelled'
        WHERE user_id = %s AND status = 'pending' AND dedupe_key LIKE %s
        """,
        (user_id, dedupe_prefix.replace("%", r"\%") + "%"),
    )
    return cur.rowcount


def patient_user(conn: Connection, patient_id: str) -> str | None:
    """The user account of a patient, if they have one."""
    row = conn.cursor(row_factory=tuple_row).execute(
        "SELECT user_id::text FROM patients WHERE id = %s", (patient_id,)
    ).fetchone()
    return row[0] if row else None
