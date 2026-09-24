"""Re-check coverage before visits: every day, for appointments in the next three days.

Each booked appointment's patient gets a 270/271 check (one per patient per day). When coverage comes
back inactive, not found or unchecked, the organization's front desk is notified. Idempotent: a patient
already checked by this job in the last 20 hours is not checked again, and flags use dedupe keys.
"""

from __future__ import annotations

from datetime import timedelta

from bioverse.config import clinic_tz
from bioverse.jobs import job
from bioverse.notify import notify
from bioverse.payers import services as svc


@job("insurance_eligibility", every_minutes=24 * 60,
     description="Check insurance eligibility for appointments in the next 3 days and flag problems to the front desk")
def run(conn, now):
    appointments = conn.execute(
        """
        SELECT a.id::text, a.patient_id::text, s.starts_at, p.organization_id::text
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN patients p ON p.id = a.patient_id
        WHERE a.status = 'booked' AND s.starts_at BETWEEN %s AND %s
        ORDER BY s.starts_at
        """,
        (now, now + timedelta(days=3)),
    ).fetchall()
    counts = {"appointments": len(appointments), "checked": 0, "reused": 0, "flagged": 0}
    by_patient: dict[str, dict] = {}
    for appt in appointments:
        day = appt["starts_at"].astimezone(clinic_tz()).date()
        pid = appt["patient_id"]
        if pid not in by_patient:
            recent = conn.execute(
                """
                SELECT status, coverage_id::text FROM insurance_eligibility_checks
                WHERE patient_id = %s AND trigger = 'job' AND checked_at > %s ORDER BY checked_at DESC LIMIT 1
                """,
                (pid, now - timedelta(hours=20)),
            ).fetchone()
            if recent:
                by_patient[pid] = recent
                counts["reused"] += 1
            else:
                cov = svc._active_coverage_on(conn, pid, day)
                if cov is None:
                    by_patient[pid] = {"status": "no_coverage", "coverage_id": None}
                else:
                    check = svc.check_coverage(conn, cov["id"], trigger="job", appointment_id=appt["id"],
                                               date_of_service=day)
                    by_patient[pid] = {"status": check["status"], "coverage_id": cov["id"]}
                    counts["checked"] += 1
        outcome = by_patient[pid]["status"]
        if outcome == "active":
            continue
        staff = conn.execute(
            "SELECT id::text FROM users WHERE organization_id = %s AND role = 'staff' "
            "AND coalesce(team, 'front_desk') = 'front_desk'", (appt["organization_id"],)
        ).fetchall()
        wording = {"inactive": "came back inactive", "not_found": "wasn't found by the payer",
                   "no_coverage": "isn't on file", "error": "couldn't be checked"}.get(outcome, "needs review")
        for s in staff:
            # No patient name here: titles and bodies can leave the app by email or text.
            created = notify(
                conn, user_id=s["id"], kind="insurance_coverage_flag", priority="high", link="/insurance/front-desk",
                title="Coverage needs attention before a visit",
                body=f"A patient's insurance {wording} for a visit on {day:%b %-d}. Open Coverage & cards to review.",
                dedupe_key=f"insurance-elig:{appt['id']}:{outcome}",
            )
            if created:
                counts["flagged"] += 1
    return counts
