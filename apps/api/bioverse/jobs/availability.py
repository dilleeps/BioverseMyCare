"""Keep clinicians' bookable slots rolling forward from their weekly hours (see bioverse/availability.py).

Saving hours syncs straight away; this job opens the next day's slots as the horizon moves and withdraws
free generated slots that no longer fit (for example, a window that has reached its end date). Idempotent.
"""

from __future__ import annotations

from bioverse import availability
from bioverse.jobs import job


@job("availability_slots", every_minutes=60,
     description="Open bookable slots from clinicians' weekly hours and time off, rolling the horizon forward")
def run(conn, now):
    ids = [r["id"] for r in conn.execute(
        """
        SELECT practitioner_id::text AS id FROM availability_windows
        UNION
        SELECT practitioner_id::text FROM slots WHERE source = 'template' AND status = 'free' AND starts_at > %s
        ORDER BY 1
        """,
        (now,),
    ).fetchall()]
    totals = {"practitioners": len(ids), "created": 0, "removed": 0, "updated": 0}
    for pid in ids:
        result = availability.sync(conn, pid, now)
        for key in ("created", "removed", "updated"):
            totals[key] += result[key]
    return totals
