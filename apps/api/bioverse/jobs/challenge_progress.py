"""Daily: update challenge progress, award points and badges, send milestone notifications. Idempotent."""

from __future__ import annotations

from bioverse.challenge_engine import clinic_day, sync_enrollment
from bioverse.jobs import job


@job("challenge_progress", every_minutes=24 * 60, description="Update challenge progress, points, badges and milestones")
def run(conn, now):
    today = clinic_day(now)
    totals = {"enrollments": 0, "points": 0, "badges": 0, "notifications": 0, "completed": 0, "ended": 0}
    rows = conn.execute("SELECT id::text FROM challenge_enrollments WHERE status = 'active' ORDER BY created_at").fetchall()
    for r in rows:
        counts = sync_enrollment(conn, r["id"], today)
        totals["enrollments"] += 1
        for k, v in counts.items():
            totals[k] += int(v)
    return totals
