"""Weekly hours for the demo clinicians, so their schedules keep rolling forward after the seeded slots run out.

The hours cover the times the earlier seed modules already put on their calendars (08:00 to 17:00 on
weekdays, the telehealth team into the evening). No slot is written, changed or removed here: every seeded
slot keeps `source = 'manual'` (the column default from migration 230), so the generator never touches it,
and it never places a generated slot on top of one. Slots are opened by the `availability_slots` job, or when
someone saves the hours.

Idempotent: a clinician whose hours were already set (by this seed or by a person) is skipped.
"""

from __future__ import annotations

from datetime import time

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_ACHEBE, DR_FERREIRA, DR_LINDQVIST, DR_MORI, DR_OKAFOR, DR_RAMAN, DR_WEISS, TEAM_DERM_TELE, _id,
)

WEEKDAYS = range(0, 5)  # Monday to Friday

# practitioner: [(weekdays, start, end, mode, slot minutes)]; location comes from the practitioner.
TEMPLATES = {
    DR_OKAFOR: [(WEEKDAYS, time(8), time(17), "in_person", 20)],
    DR_FERREIRA: [(WEEKDAYS, time(8), time(17), "in_person", 20)],
    DR_ACHEBE: [(WEEKDAYS, time(8), time(17), "in_person", 20)],
    DR_MORI: [(WEEKDAYS, time(9), time(18), "in_person", 20)],
    # Clinicians who also see patients by video: Friday afternoons are video visits.
    DR_LINDQVIST: [(range(0, 4), time(8), time(17), "in_person", 20), ((4,), time(8), time(12), "in_person", 20),
                   ((4,), time(13), time(17), "video", 20)],
    DR_RAMAN: [(range(0, 4), time(8), time(17), "in_person", 20), ((4,), time(8), time(12), "in_person", 20),
               ((4,), time(13), time(17), "video", 20)],
    DR_WEISS: [(range(0, 4), time(8), time(17), "in_person", 20), ((4,), time(8), time(12), "in_person", 20),
               ((4,), time(13), time(17), "video", 20)],
    TEAM_DERM_TELE: [(WEEKDAYS, time(8), time(20), "video", 20)],
}


def run(conn, ctx: SeedContext) -> None:
    n = 19000
    for practitioner, windows in TEMPLATES.items():
        pr = conn.execute("SELECT location_name FROM practitioners WHERE id = %s", (practitioner,)).fetchone()
        created = conn.execute(
            """
            INSERT INTO availability_settings (practitioner_id, timezone, horizon_days)
            SELECT %s, %s, 28 WHERE EXISTS (SELECT 1 FROM practitioners WHERE id = %s)
            ON CONFLICT (practitioner_id) DO NOTHING
            """,
            (practitioner, ctx.tz.key, practitioner),
        ).rowcount
        rows = []
        for days, start, end, mode, minutes in windows:
            for weekday in days:
                n += 1
                rows.append((_id(n), practitioner, weekday, start, end, mode,
                             "Video visit" if mode == "video" else pr[0] if pr else None, minutes))
        if not created:
            continue    # hours already set: never overwrite them
        conn.cursor().executemany(
            """
            INSERT INTO availability_windows (id, practitioner_id, weekday, start_time, end_time, mode, location,
                                              slot_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
            """,
            rows,
        )
