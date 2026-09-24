"""Follow-up check-ins: the day after a visit, and three days into a new medicine.

Each check-in is a `companion_checkins` row (unique per patient, kind and visit or prescription) plus a
notification. It arrives at 10:00 on the patient's clock. Visits and medicines further back than the look-back
window are left alone, so turning the job on never floods anyone with old check-ins. Unanswered check-ins
expire after a week.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from bioverse import companion
from bioverse.jobs import job

VISIT_LOOKBACK = timedelta(days=3)       # how late a post-visit check-in may still be sent
MEDICATION_DAY = 3                        # "three days after a new medication starts"
MEDICATION_LOOKBACK = timedelta(days=4)


def _due(local_day, tz) -> datetime:
    return companion.local_to_instant(datetime.combine(local_day, time(companion.CHECKIN_HOUR)), tz)


@job("companion_checkins", every_minutes=60, description="Check in after visits and new medicines")
def run(conn, now):
    created = {"post_visit": 0, "new_medication": 0}

    visits = conn.execute(
        """
        SELECT e.id::text, e.patient_id::text, e.occurred_at, e.kind, e.practitioner_id::text,
               pr.name AS practitioner_name, p.user_id::text, p.name AS patient_name
        FROM encounters e
        JOIN patients p ON p.id = e.patient_id
        LEFT JOIN practitioners pr ON pr.id = e.practitioner_id
        WHERE p.user_id IS NOT NULL AND e.occurred_at <= %s AND e.occurred_at > %s
          AND NOT EXISTS (SELECT 1 FROM companion_checkins c
                          WHERE c.patient_id = e.patient_id AND c.kind = 'post_visit' AND c.ref_id = e.id)
        """,
        (now, now - VISIT_LOOKBACK - timedelta(days=2)),
    ).fetchall()
    meds = conn.execute(
        companion.MED_SQL + """
        JOIN patients p ON p.id = m.patient_id
        WHERE m.status = 'active' AND p.user_id IS NOT NULL AND m.authored_at > %s
          AND NOT EXISTS (SELECT 1 FROM companion_checkins c
                          WHERE c.patient_id = m.patient_id AND c.kind = 'new_medication' AND c.ref_id = m.id)
        """,
        (now - timedelta(days=120),),
    ).fetchall()

    patients = sorted({v["patient_id"] for v in visits} | {m["patient_id"] for m in meds})
    settings = companion.settings_for(conn, patients)
    people = {r["id"]: r for r in conn.execute(
        "SELECT id::text, user_id::text, name FROM patients WHERE id = ANY(%s::uuid[])", (patients,)
    ).fetchall()}

    for v in visits:
        if not settings[v["patient_id"]]["checkins"]:
            continue
        tz = companion.patient_tz(conn, v["patient_id"])
        due = _due(v["occurred_at"].astimezone(tz).date() + timedelta(days=1), tz)
        if not (due <= now < due + VISIT_LOOKBACK):
            continue
        who = v["practitioner_name"] or "your care team"
        row = companion.create_checkin(
            conn, patient_id=v["patient_id"], user_id=v["user_id"], patient_name=v["patient_name"],
            kind="post_visit", ref_id=v["id"], subject=f"your visit with {who}",
            practitioner_id=v["practitioner_id"], facts={"clinician": who, "visit": v["kind"]}, due_at=due,
        )
        created["post_visit"] += row is not None

    for r in meds:
        med = companion.med_from_row(r)
        if med.start is None or med.freq.as_needed or not settings[med.patient_id]["checkins"]:
            continue
        tz = companion.patient_tz(conn, med.patient_id)
        due = _due(med.start.astimezone(tz).date() + timedelta(days=MEDICATION_DAY), tz)
        if not (due <= now < due + MEDICATION_LOOKBACK):
            continue
        person = people[med.patient_id]
        row = companion.create_checkin(
            conn, patient_id=med.patient_id, user_id=person["user_id"], patient_name=person["name"],
            kind="new_medication", ref_id=med.id, subject=med.label, practitioner_id=med.prescriber_id,
            facts={"medicine": med.drug_name}, due_at=due,
        )
        created["new_medication"] += row is not None

    expired = conn.execute(
        "UPDATE companion_checkins SET status = 'expired' WHERE status = 'open' AND due_at < %s",
        (now - companion.CHECKIN_EXPIRES,),
    ).rowcount
    return {**created, "expired": expired}
