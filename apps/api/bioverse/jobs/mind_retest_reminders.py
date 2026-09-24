"""Remind opted-in patients to retake the PHQ-9 or GAD-7 every 2 to 4 weeks. One reminder per completed check."""

from __future__ import annotations

from bioverse.jobs import job
from bioverse.notify import notify, patient_user

NAMES = {"phq9": "mood check", "gad7": "anxiety check"}


@job("mind_retest_reminders", every_minutes=12 * 60, description="Remind opted-in patients to retake mood and anxiety checks")
def run(conn, now):
    from bioverse.routers.mind import retest_due

    sent = 0
    for r in retest_due(conn, now):
        uid = patient_user(conn, r["patient_id"])
        if uid and notify(conn, user_id=uid, kind="mind_retest", title="Time for your wellbeing check-in",
                          body=f"It's been {r['retest_weeks']} weeks since your last {NAMES[r['instrument']]}. "
                               "It takes about two minutes.",
                          link="/mind", patient_id=r["patient_id"], dedupe_key=f"mind_retest:{r['response_id']}"):
            sent += 1
    return {"reminders": sent}
