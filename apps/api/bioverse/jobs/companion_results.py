"""Results-ready nudges.

A result is released to the patient when its explanation is approved by a clinician (`result_explanations`
status 'approved', see routers/clinician.py): until then the patient sees neither the draft nor a nudge.
One notification per report (dedupe `result:<report id>`), for releases in the last three days.
"""

from __future__ import annotations

from datetime import timedelta

from bioverse import audit, companion
from bioverse.jobs import job
from bioverse.notify import notify

LOOKBACK = timedelta(days=3)


@job("companion_results", every_minutes=30, description="Tell patients when reviewed results are ready")
def run(conn, now):
    rows = conn.execute(
        """
        SELECT r.id::text AS report_id, r.patient_id::text, p.user_id::text, x.reviewed_at
        FROM result_explanations x
        JOIN diagnostic_reports r ON r.id = x.report_id
        JOIN patients p ON p.id = r.patient_id
        WHERE x.status = 'approved' AND x.reviewed_at IS NOT NULL AND p.user_id IS NOT NULL
          AND x.reviewed_at <= %s AND x.reviewed_at > %s
        ORDER BY x.reviewed_at
        """,
        (now, now - LOOKBACK),
    ).fetchall()
    settings = companion.settings_for(conn, sorted({r["patient_id"] for r in rows}))
    created = 0
    for r in rows:
        if not settings[r["patient_id"]]["results_ready"]:
            continue
        row = notify(conn, user_id=r["user_id"], patient_id=r["patient_id"], kind="results_ready",
                     title="New results are ready",
                     body="Your care team has reviewed them. Open Bioverse One to read them with their note.",
                     link=f"/results/{r['report_id']}", due_at=max(r["reviewed_at"], now - LOOKBACK),
                     dedupe_key=f"result:{r['report_id']}")
        if row is not None:
            created += 1
            audit.record(conn, action="results_ready_notified", entity_type="diagnostic_report",
                         entity_id=r["report_id"], agent="companion/jobs", patient_id=r["patient_id"])
    return {"created": created, "released": len(rows)}
