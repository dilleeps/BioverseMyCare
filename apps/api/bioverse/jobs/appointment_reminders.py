"""Appointment reminders: 24 hours and 2 hours before each booked visit.

Dedupe keys are `appt:<appointment id>:24h` and `appt:<appointment id>:2h`. A visit booked less than four
hours ahead gets only the 2-hour reminder. Reminders for visits that were cancelled or already happened are
cancelled. The body carries the time, place and preparation the visit type implies (fasting blood work,
bringing a medication list, testing a video link), from the same checklist the visits page shows.
"""

from __future__ import annotations

from datetime import timedelta

from bioverse import audit, companion
from bioverse.jobs import job
from bioverse.notify import cancel, notify
from bioverse.routers.visits import checklist_template

LEADS = (("24h", timedelta(hours=24), timedelta(hours=4)), ("2h", timedelta(hours=2), timedelta(minutes=15)))


def when_words(due_local, start_local) -> str:
    days = (start_local.date() - due_local.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"on {start_local:%A}"


def prep_lines(appt: dict) -> list[str]:
    keys = {k for k, _, _ in checklist_template(appt)}
    lines = []
    if "fasting" in keys:
        lines.append("This visit may include fasting blood work: have nothing but water for 8 to 12 hours before, "
                     "unless your care team told you otherwise.")
    if "tech_check" in keys:
        lines.append("Open the video link from your visits page 15 minutes early to test your camera and sound.")
    else:
        lines.append("Bring your medication list, insurance card and photo ID.")
    return lines


def body_for(appt: dict, location: dict | None) -> str:
    video = appt["mode"] == "video" or appt["location_name"] == "Video visit"
    if video:
        where = "Video visit."
    else:
        place = location["name"] if location else appt["location_name"]
        address = f", {location['address']}" if location and location.get("address") else ""
        where = f"At {place}{address}."
    return " ".join([f"With {appt['practitioner_name']}.", where, *prep_lines(appt)])


@job("appointment_reminders", every_minutes=15, description="Remind patients 24 hours and 2 hours before a visit")
def run(conn, now):
    rows = conn.execute(
        """
        SELECT a.id::text, a.patient_id::text, p.user_id::text, a.reason, s.starts_at, s.mode,
               pr.name AS practitioner_name, pr.location_name, pr.organization_id::text
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        JOIN patients p ON p.id = a.patient_id
        LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
        WHERE a.status = 'booked' AND e.appointment_id IS NULL AND p.user_id IS NOT NULL
          AND s.starts_at > %s AND s.starts_at <= %s
        ORDER BY s.starts_at
        """,
        (now, now + timedelta(hours=24) + companion.REMINDER_LOOKAHEAD),
    ).fetchall()
    settings = companion.settings_for(conn, sorted({r["patient_id"] for r in rows}))
    created = 0
    for appt in rows:
        if not settings[appt["patient_id"]]["appointment_reminders"]:
            continue
        tz = companion.patient_tz(conn, appt["patient_id"])
        location = conn.execute(
            "SELECT name, address FROM locations WHERE organization_id = %s AND name = %s",
            (appt["organization_id"], appt["location_name"]),
        ).fetchone()
        start_local = appt["starts_at"].astimezone(tz)
        for label, lead, min_notice in LEADS:
            due = appt["starts_at"] - lead
            if due > now + companion.REMINDER_LOOKAHEAD or appt["starts_at"] - now < min_notice:
                continue
            due = max(due, now - companion.REMINDER_GRACE)   # booked late: remind now, not in the past
            title = f"Appointment {when_words(due.astimezone(tz), start_local)} at {companion.fmt_clock(start_local.time())}"
            row = notify(conn, user_id=appt["user_id"], patient_id=appt["patient_id"], kind="appointment_reminder",
                         title=title, body=body_for(appt, location), link="/visits", due_at=due,
                         dedupe_key=f"appt:{appt['id']}:{label}")
            if row is not None:
                created += 1
                audit.record(conn, action="appointment_reminder_scheduled", entity_type="appointment",
                             entity_id=appt["id"], agent="companion/jobs", patient_id=appt["patient_id"],
                             detail={"lead": label})

    stale = conn.execute(
        """
        SELECT DISTINCT n.user_id::text, a.id::text AS appt_id
        FROM notifications n
        JOIN appointments a ON a.id::text = split_part(n.dedupe_key, ':', 2)
        LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
        WHERE n.status = 'pending' AND n.kind = 'appointment_reminder' AND n.dedupe_key LIKE 'appt:%'
          AND (a.status <> 'booked' OR e.status IN ('completed', 'no_show'))
        """
    ).fetchall()
    cancelled = sum(cancel(conn, user_id=s["user_id"], dedupe_prefix=f"appt:{s['appt_id']}:") for s in stale)
    return {"created": created, "cancelled": cancelled, "upcoming": len(rows)}
