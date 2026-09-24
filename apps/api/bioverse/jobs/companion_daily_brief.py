"""Daily brief (opt-in): a morning summary at the patient's chosen time.

Counts only, no names: today's doses, appointments and open check-ins, plus one tip from a small static
library of evidence-based tips with sources (`companion.TIPS`). One per patient per day (`brief:<date>`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bioverse import companion
from bioverse.jobs import job
from bioverse.notify import notify

WINDOW = timedelta(hours=2)   # a brief more than two hours late is skipped for the day


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary_line(doses: int, appointments: int, checkins: int) -> str:
    parts = []
    if doses:
        parts.append(plural(doses, "medicine dose"))
    if appointments:
        parts.append(plural(appointments, "appointment"))
    if checkins:
        parts.append(plural(checkins, "check-in") + " waiting")
    if not parts:
        return "Nothing scheduled today."
    return "Today: " + ", ".join(parts) + "."


@job("companion_daily_brief", every_minutes=15, description="Send opted-in patients a short morning summary")
def run(conn, now):
    rows = conn.execute(
        """
        SELECT s.patient_id::text, s.daily_brief_time, p.user_id::text
        FROM companion_settings s JOIN patients p ON p.id = s.patient_id
        WHERE s.daily_brief AND p.user_id IS NOT NULL
        """
    ).fetchall()
    created = 0
    for r in rows:
        tz = companion.patient_tz(conn, r["patient_id"])
        today = now.astimezone(tz).date()
        due = companion.local_to_instant(datetime.combine(today, r["daily_brief_time"]), tz)
        if not (due <= now < due + WINDOW):
            continue
        settings = companion.load_settings(conn, r["patient_id"])
        doses = sum(len(companion.doses_on(m, settings, tz, today)) for m in companion.load_meds(conn, r["patient_id"]))
        end = companion.local_to_instant(datetime.combine(today + timedelta(days=1), datetime.min.time()), tz)
        appts = conn.execute(
            """
            SELECT count(*) AS n FROM appointments a JOIN slots s ON s.id = a.slot_id
            WHERE a.patient_id = %s AND a.status = 'booked' AND s.starts_at >= %s AND s.starts_at < %s
            """,
            (r["patient_id"], due, end),
        ).fetchone()["n"]
        checkins = conn.execute(
            "SELECT count(*) AS n FROM companion_checkins WHERE patient_id = %s AND status = 'open' AND due_at <= %s",
            (r["patient_id"], now),
        ).fetchone()["n"]
        tip = companion.tip_for(today)
        row = notify(conn, user_id=r["user_id"], patient_id=r["patient_id"], kind="companion",
                     title="Good morning. Here's your day", body=f"{summary_line(doses, appts, checkins)} Tip: {tip['text']}",
                     link="/companion", priority="low", due_at=due, dedupe_key=f"brief:{today.isoformat()}")
        created += row is not None
    return {"created": created, "opted_in": len(rows)}
