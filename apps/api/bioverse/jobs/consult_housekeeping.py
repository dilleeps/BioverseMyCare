"""Online consults: remind both people before a scheduled call, cancel requests nobody took in time, and
delete old video-call signaling."""

from __future__ import annotations

from datetime import timedelta

from bioverse import audit
from bioverse.config import clinic_tz
from bioverse.jobs import job
from bioverse.notify import notify

REMIND_MINUTES = 60
UNCLAIMED_MESSAGE_HOURS = 72
SIGNAL_RETENTION_HOURS = 24


@job("consult_housekeeping", every_minutes=15,
     description="Remind before online consults, close requests nobody took, clear old call signaling")
def run(conn, now):
    reminded = 0
    upcoming = conn.execute(
        """
        SELECT c.id::text, c.patient_id::text, c.mode, c.scheduled_at, p.user_id::text AS patient_user,
               pr.user_id::text AS clinician_user, pr.name
        FROM consultations c JOIN patients p ON p.id = c.patient_id JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.status = 'accepted' AND c.scheduled_at > %s AND c.scheduled_at <= %s
        """,
        (now, now + timedelta(minutes=REMIND_MINUTES)),
    ).fetchall()
    for c in upcoming:
        local = c["scheduled_at"].astimezone(clinic_tz())
        kind = "video call" if c["mode"] == "video" else "phone call"
        if c["patient_user"]:
            reminded += bool(notify(
                conn, user_id=c["patient_user"], kind="consultation", title=f"Your online consult starts at {local:%H:%M}",
                body=f"{c['name']} · {kind}. Open the consult a few minutes early.", link=f"/consult/{c['id']}",
                patient_id=c["patient_id"], priority="high", channels=["in_app", "push", "sms"],
                dedupe_key=f"consult:{c['id']}:reminder"))
        if c["clinician_user"]:
            notify(conn, user_id=c["clinician_user"], kind="consultation", title=f"Online consult at {local:%H:%M}",
                   body=f"{kind.capitalize()} with a patient.", link=f"/clinician/consults/{c['id']}",
                   patient_id=c["patient_id"], dedupe_key=f"consult:{c['id']}:reminder")

    stale = conn.execute(
        """
        UPDATE consultations c
        SET status = 'cancelled', cancelled_by = 'system', closed_at = now(), updated_at = now(),
            cancel_reason = CASE WHEN c.scheduled_at IS NOT NULL
                                 THEN 'No clinician accepted the request before the scheduled time.'
                                 ELSE 'No clinician was able to take the request in time.' END
        FROM patients p
        WHERE p.id = c.patient_id AND c.status = 'requested'
          AND ((c.scheduled_at IS NOT NULL AND c.scheduled_at < %s)
               OR (c.scheduled_at IS NULL AND c.created_at < %s))
        RETURNING c.id::text, c.patient_id::text, p.user_id::text AS patient_user
        """,
        (now, now - timedelta(hours=UNCLAIMED_MESSAGE_HOURS)),
    ).fetchall()
    for c in stale:
        audit.record(conn, action="consult_cancelled", entity_type="consultation", entity_id=c["id"],
                     agent="job/consult_housekeeping", patient_id=c["patient_id"], detail={"reason": "expired_request"})
        if c["patient_user"]:
            notify(conn, user_id=c["patient_user"], kind="consultation", title="Your online consult request expired",
                   body="No clinician could take it in time. You can request another.", link=f"/consult/{c['id']}",
                   patient_id=c["patient_id"], dedupe_key=f"consult:{c['id']}:cancelled")

    cleared = conn.execute(
        "DELETE FROM consultation_signals WHERE created_at < %s", (now - timedelta(hours=SIGNAL_RETENTION_HOURS),)
    ).rowcount
    return {"reminded": reminded, "expired_requests": len(stale), "signals_cleared": cleared}
