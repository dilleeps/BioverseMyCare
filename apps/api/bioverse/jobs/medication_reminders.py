"""Medication reminders: one notification per scheduled dose, created up to an hour ahead.

Dose times come from each active prescription's directions (see `companion.parse_frequency`) and the
patient's preferred times, on the patient's own clock. Each reminder's dedupe key is
`med:<medication_request id>:<local date and time>`, so re-runs never duplicate. Pending reminders for a
prescription that is no longer active are cancelled.

Titles are generic ("Time for your evening medicine"): the medicine's name shows only on the companion
page, behind the link, because titles leave the app by text and push and can sit on a lock screen.
"""

from __future__ import annotations

from collections import defaultdict

from bioverse import audit, companion
from bioverse.jobs import job
from bioverse.notify import cancel, notify


@job("medication_reminders", every_minutes=15, description="Remind patients when a medicine dose is due")
def run(conn, now):
    rows = conn.execute(
        companion.MED_SQL + """
        JOIN patients p ON p.id = m.patient_id
        WHERE m.status = 'active' AND p.user_id IS NOT NULL
        ORDER BY m.patient_id, m.authored_at
        """
    ).fetchall()
    by_patient: dict[str, list] = defaultdict(list)
    for r in rows:
        by_patient[r["patient_id"]].append(companion.med_from_row(r))

    created = 0
    settings = companion.settings_for(conn, list(by_patient))
    for patient_id, meds in by_patient.items():
        prefs = settings[patient_id]
        if not prefs["medication_reminders"]:
            continue
        tz = companion.patient_tz(conn, patient_id)
        user_id = conn.execute("SELECT user_id::text FROM patients WHERE id = %s", (patient_id,)).fetchone()["user_id"]
        since, until = now - companion.REMINDER_GRACE, now + companion.REMINDER_LOOKAHEAD
        doses = [d for med in meds for d in companion.scheduled_doses(med, prefs, tz, since, until)]
        if not doses:
            continue
        marked = {(r["medication_request_id"], r["scheduled_local"]) for r in conn.execute(
            """
            SELECT medication_request_id::text, scheduled_local FROM medication_doses
            WHERE patient_id = %s AND scheduled_local = ANY(%s)
            """,
            (patient_id, [d.local for d in doses]),
        ).fetchall()}
        mine = 0
        for d in doses:
            if (d.rx_id, d.local) in marked:
                continue
            row = notify(conn, user_id=user_id, patient_id=patient_id, kind="medication_reminder",
                         title=companion.reminder_title(d.local.time()), body=companion.REMINDER_BODY,
                         link=f"/companion?rx={d.rx_id}&at={d.local:%Y-%m-%dT%H:%M}",
                         due_at=d.at, dedupe_key=d.key)
            mine += row is not None
        if mine:
            audit.record(conn, action="medication_reminders_scheduled", entity_type="medication_request",
                         agent="companion/jobs", patient_id=patient_id, detail={"created": mine})
        created += mine

    # Stopped, completed or paused prescriptions: nothing pending should still fire.
    stale = conn.execute(
        """
        SELECT DISTINCT n.user_id::text, m.id::text AS rx_id, m.patient_id::text
        FROM notifications n
        JOIN medication_requests m ON m.id::text = split_part(n.dedupe_key, ':', 2)
        WHERE n.status = 'pending' AND n.kind = 'medication_reminder' AND n.dedupe_key LIKE 'med:%'
          AND m.status <> 'active'
        """
    ).fetchall()
    cancelled = 0
    for s in stale:
        n = cancel(conn, user_id=s["user_id"], dedupe_prefix=f"med:{s['rx_id']}:")
        cancelled += n
        audit.record(conn, action="medication_reminders_cancelled", entity_type="medication_request",
                     entity_id=s["rx_id"], agent="companion/jobs", patient_id=s["patient_id"], detail={"cancelled": n})
    return {"created": created, "cancelled": cancelled, "patients": len(by_patient)}
