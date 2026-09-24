"""Home monitoring reminders: at each plan time (clinic time zone), remind the patient to measure, unless a
reading of that measure was already logged in the slot's window. Also closes plans whose last day has passed."""

from __future__ import annotations

from datetime import time

from bioverse.config import clinic_tz
from bioverse.jobs import job
from bioverse.notify import notify, patient_user
from bioverse.routers import vitals_core as core

VERB = {"bp": "blood pressure", "heart_rate": "heart rate", "spo2": "oxygen level", "temperature": "temperature",
        "glucose": "blood glucose", "weight": "weight"}


@job("vitals_reminders", every_minutes=15, description="Remind patients to take home readings their clinician asked for")
def run(conn, now):
    today = now.astimezone(clinic_tz()).date()
    completed = conn.execute(
        "UPDATE vital_monitoring_plans SET status = 'completed' WHERE status = 'active' AND end_on < %s RETURNING id",
        (today,),
    ).fetchall()
    plans = conn.execute(
        """
        SELECT id::text, patient_id::text, measure, times, start_on, end_on, instructions
        FROM vital_monitoring_plans WHERE status = 'active' AND start_on <= %s AND end_on >= %s
        """,
        (today, today),
    ).fetchall()
    created = skipped = 0
    for p in plans:
        uid = patient_user(conn, p["patient_id"])
        if uid is None:
            continue
        for start, due, end in core.slots({**p, "times": sorted(t if isinstance(t, time) else time.fromisoformat(t)
                                                                for t in p["times"])}, today):
            if not due <= now < end:
                continue
            if core.reading_times(conn, p["patient_id"], p["measure"], start, now):
                skipped += 1
                continue
            row = notify(conn, user_id=uid, kind="vital_reminder", title=f"Time to measure your {VERB[p['measure']]}",
                         body=p["instructions"] or "Your care team asked you to take this reading. Log it in Bioverse.",
                         link="/vitals", patient_id=p["patient_id"], due_at=due,
                         dedupe_key=f"vitals:plan:{p['id']}:slot:{due.isoformat()}", created_by="vitals_reminders")
            created += row is not None
    return {"created": created, "already_logged": skipped, "plans": len(plans), "completed_plans": len(completed)}
