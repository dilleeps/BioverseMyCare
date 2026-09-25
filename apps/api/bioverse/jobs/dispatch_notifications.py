"""Deliver due notifications on email, SMS and push, respecting preferences and quiet hours."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from bioverse import channels, webpush
from bioverse.jobs import job


def in_quiet_hours(start: time | None, end: time | None, tz: str, now: datetime) -> bool:
    if start is None or end is None or start == end:
        return False
    try:
        local = now.astimezone(ZoneInfo(tz)).time()
    except Exception:  # noqa: BLE001 - an unknown zone falls back to UTC
        local = now.time()
    return start <= local < end if start < end else (local >= start or local < end)


@job("dispatch_notifications", every_minutes=5, description="Send due notifications by email, text and push")
def run(conn, now):
    rows = conn.execute(
        """
        SELECT n.id, n.user_id::text, n.kind, n.title, n.link, n.priority, n.channels, n.delivery,
               u.email AS account_email, p.email, p.phone, p.channels AS prefs,
               p.quiet_start, p.quiet_end, coalesce(p.timezone, 'America/New_York') AS tz
        FROM notifications n
        JOIN users u ON u.id = n.user_id
        LEFT JOIN notification_preferences p ON p.user_id = n.user_id
        WHERE n.status = 'pending' AND n.due_at <= %s
        ORDER BY n.due_at
        LIMIT 500
        FOR UPDATE OF n SKIP LOCKED
        """,
        (now,),
    ).fetchall()

    counts = {"sent": 0, "held_quiet_hours": 0, "email": 0, "sms": 0, "push": 0, "skipped": 0, "failed": 0}
    for r in rows:
        if r["priority"] != "urgent" and in_quiet_hours(r["quiet_start"], r["quiet_end"], r["tz"], now):
            counts["held_quiet_hours"] += 1
            continue
        wanted = set(r["channels"])
        # A user's per-kind preference replaces the sender's default channel list.
        if r["prefs"] and r["kind"] in r["prefs"]:
            wanted = set(r["prefs"][r["kind"]]) | {"in_app"}
        delivery = dict(r["delivery"] or {})
        delivery["in_app"] = {"status": "sent", "at": now.isoformat()}
        for ch in sorted(wanted - {"in_app"}):
            sender = channels.SENDERS.get(ch)
            if sender is None:
                continue
            if ch == "push":
                # Push goes to each of the user's devices, looked up by user rather than by an address.
                res = webpush.deliver(conn, r["user_id"], r["title"], r["link"], r["priority"], tag=str(r["id"]))
            else:
                to = (r["email"] or r["account_email"]) if ch == "email" else r["phone"] if ch == "sms" else None
                res = sender(to, r["title"], r["link"])
            delivery[ch] = {"status": res.status, "detail": res.detail, "at": now.isoformat()}
            if res.status == "sent":
                counts[ch] += 1
            else:
                counts[res.status] += 1
        conn.execute(
            "UPDATE notifications SET status = 'sent', sent_at = %s, delivery = %s WHERE id = %s",
            (now, Jsonb(delivery), r["id"]),
        )
        counts["sent"] += 1
    return counts
