"""Analytics and intelligence, by audience.

Administrators: 13-week organization trends and referral leakage (aggregates, from hospital_agent metrics).
Clinicians: their own panel only - care-plan adherence, overdue tasks, open care gaps and abnormal results
without an approved explanation. Patient analytics live elsewhere.
"""

from __future__ import annotations

from fastapi import APIRouter
from psycopg import Connection

from bioverse import audit
from bioverse.agents import hospital_agent as ha
from bioverse.auth import Admin, Clinician
from bioverse.db import DbConn
from bioverse.services import timeline

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

PANEL_DEFINITION = (
    "Your panel: patients with an active care plan with you, an appointment with you in the last 90 days "
    "or upcoming, or an open item in your review queue."
)


def panel_patient_ids(conn: Connection, practitioner_id: str, organization_id: str) -> list[str]:
    rows = conn.execute(
        """
        WITH mine AS (
            SELECT patient_id FROM care_plans WHERE practitioner_id = %(pr)s AND status = 'active'
            UNION
            SELECT a.patient_id FROM appointments a JOIN slots s ON s.id = a.slot_id
            WHERE a.practitioner_id = %(pr)s AND a.status <> 'cancelled' AND s.starts_at >= now() - interval '90 days'
            UNION
            SELECT patient_id FROM review_items WHERE practitioner_id = %(pr)s AND status = 'open'
        )
        SELECT p.id::text FROM patients p JOIN mine m ON m.patient_id = p.id
        WHERE p.organization_id = %(org)s AND p.merged_into IS NULL ORDER BY p.name
        """,
        {"pr": practitioner_id, "org": organization_id},
    ).fetchall()
    return [r["id"] for r in rows]


@router.get("/organization")
def organization(conn: DbConn, user: Admin) -> dict:
    clk = ha.clock()
    return {
        "generated_at": clk.now,
        "trends": ha.weekly_trends(conn, user.organization_id, clk=clk),
        "leakage": ha.referral_leakage(conn, user.organization_id, 90, clk=clk),
    }


@router.get("/clinician")
def clinician(conn: DbConn, user: Clinician) -> dict:
    """Always the signed-in clinician's own panel; there is no parameter to ask for someone else's."""
    today = ha.clock().today  # clinic-local date, the same one care-plan due dates are set in
    ids = panel_patient_ids(conn, user.practitioner_id, user.organization_id)
    patients = conn.execute(
        """
        SELECT p.id::text, p.name, p.birth_date,
               (SELECT c.title FROM care_plans c WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s
                  AND c.status = 'active' ORDER BY c.started_at DESC LIMIT 1) AS plan_title,
               (SELECT count(*) FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
                 WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s AND c.status = 'active'
                   AND t.due_on <= %(today)s) AS tasks_due,
               (SELECT count(*) FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
                 WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s AND c.status = 'active'
                   AND t.due_on <= %(today)s AND t.status = 'done') AS tasks_done,
               (SELECT count(*) FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
                 WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s AND c.status = 'active'
                   AND t.due_on < %(today)s AND t.status = 'todo') AS tasks_overdue,
               (SELECT count(*) FROM care_gaps g WHERE g.patient_id = p.id AND g.status = 'open') AS open_gaps,
               (SELECT count(*) FROM diagnostic_reports r
                 LEFT JOIN result_explanations x ON x.report_id = r.id
                 WHERE r.patient_id = p.id AND r.responsible_practitioner_id = %(pr)s
                   AND coalesce(x.status, 'none') <> 'approved'
                   AND EXISTS (SELECT 1 FROM observations o WHERE o.report_id = r.id AND o.interpretation <> 'N')
               ) AS unexplained_abnormal
        FROM patients p WHERE p.id = ANY(%(ids)s::uuid[])
        ORDER BY p.name
        """,
        {"pr": user.practitioner_id, "today": today, "ids": ids},
    ).fetchall()
    for p in patients:
        p["age"] = timeline.age(p.pop("birth_date"))
        p["adherence_pct"] = ha._pct(p["tasks_done"], p["tasks_due"])

    overdue = conn.execute(
        """
        SELECT t.id::text, t.title, t.kind, t.due_on, p.id::text AS patient_id, p.name AS patient_name
        FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id JOIN patients p ON p.id = c.patient_id
        WHERE c.practitioner_id = %(pr)s AND c.status = 'active' AND t.status = 'todo' AND t.due_on < %(today)s
          AND c.patient_id = ANY(%(ids)s::uuid[])
        ORDER BY t.due_on, p.name
        """,
        {"pr": user.practitioner_id, "today": today, "ids": ids},
    ).fetchall()
    gaps = conn.execute(
        """
        SELECT g.id::text, g.title, g.specialty, p.id::text AS patient_id, p.name AS patient_name
        FROM care_gaps g JOIN patients p ON p.id = g.patient_id
        WHERE g.status = 'open' AND g.patient_id = ANY(%(ids)s::uuid[]) ORDER BY p.name, g.title
        """,
        {"ids": ids},
    ).fetchall()
    unexplained = conn.execute(
        """
        SELECT r.id::text, r.name, r.collected_at, coalesce(x.status, 'none') AS explanation_status,
               p.id::text AS patient_id, p.name AS patient_name
        FROM diagnostic_reports r JOIN patients p ON p.id = r.patient_id
        LEFT JOIN result_explanations x ON x.report_id = r.id
        WHERE r.responsible_practitioner_id = %(pr)s AND r.patient_id = ANY(%(ids)s::uuid[])
          AND coalesce(x.status, 'none') <> 'approved'
          AND EXISTS (SELECT 1 FROM observations o WHERE o.report_id = r.id AND o.interpretation <> 'N')
        ORDER BY r.collected_at DESC
        """,
        {"pr": user.practitioner_id, "ids": ids},
    ).fetchall()

    due = sum(p["tasks_due"] for p in patients)
    done = sum(p["tasks_done"] for p in patients)
    for pid in ids:
        audit.record(conn, action="panel_analytics_viewed", entity_type="patient", entity_id=pid, actor=user,
                     patient_id=pid)
    return {
        "as_of": today,
        "summary": {
            "patients": len(ids),
            "tasks_due": due,
            "tasks_done": done,
            "adherence_pct": ha._pct(done, due),
            "overdue_tasks": len(overdue),
            "open_care_gaps": len(gaps),
            "unexplained_abnormal_results": len(unexplained),
        },
        "patients": patients,
        "overdue_tasks": overdue,
        "care_gaps": gaps,
        "unexplained_results": unexplained,
        "definitions": {
            "panel": PANEL_DEFINITION,
            "adherence": "Tasks marked done out of tasks due by today, in active care plans you own.",
            "overdue": "Tasks not done whose due date has passed.",
            "unexplained": "Reports you are responsible for with an abnormal value and no clinician-approved "
                           "explanation yet.",
        },
    }
