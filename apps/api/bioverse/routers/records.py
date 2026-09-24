"""Results, care plan, and My Health Story."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel

from bioverse import audit
from bioverse.auth import CurrentUser, assert_patient_access
from bioverse.db import DbConn
from bioverse.services import timeline

router = APIRouter(prefix="/api", tags=["records"])

Conn = DbConn


# --- Results ---------------------------------------------------------------------------------


@router.get("/patients/{patient_id}/reports")
def list_reports(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    assert_patient_access(conn, user, patient_id)
    return conn.execute(
        """
        SELECT r.id::text, r.name, r.lab_name, r.collected_at, r.source,
               (SELECT count(*) FROM observations o WHERE o.report_id = r.id AND o.interpretation <> 'N') AS abnormal_count,
               coalesce(x.status, 'none') AS explanation_status
        FROM diagnostic_reports r
        LEFT JOIN result_explanations x ON x.report_id = r.id
        WHERE r.patient_id = %s
        ORDER BY r.collected_at DESC
        """,
        (patient_id,),
    ).fetchall()


@router.get("/reports/{report_id}")
def get_report(report_id: str, conn: Conn, user: CurrentUser) -> dict:
    report = conn.execute(
        """
        SELECT r.id::text, r.patient_id::text, r.name, r.lab_name, r.collected_at, r.source,
               pr.name AS responsible_clinician
        FROM diagnostic_reports r LEFT JOIN practitioners pr ON pr.id = r.responsible_practitioner_id
        WHERE r.id = %s
        """,
        (report_id,),
    ).fetchone()
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    assert_patient_access(conn, user, report["patient_id"])

    observations = conn.execute(
        """
        SELECT o.id::text, o.loinc_code, o.display, o.value, o.unit, o.ref_low, o.ref_high, o.interpretation,
               (SELECT json_agg(json_build_object('value', h.value, 'at', h.effective_at) ORDER BY h.effective_at)
                FROM observations h
                WHERE h.patient_id = o.patient_id AND h.loinc_code = o.loinc_code AND h.effective_at <= o.effective_at
               ) AS history
        FROM observations o WHERE o.report_id = %s
        ORDER BY (o.interpretation <> 'N') DESC, o.display
        """,
        (report_id,),
    ).fetchall()

    x = conn.execute(
        """
        SELECT x.status, x.draft_text, x.final_text, x.questions, x.produced_by, x.reviewed_at,
               u.display_name AS reviewed_by
        FROM result_explanations x LEFT JOIN users u ON u.id = x.reviewed_by
        WHERE x.report_id = %s
        """,
        (report_id,),
    ).fetchone()

    explanation = None
    if x:
        # Patients only see clinician-approved text. The draft never reaches them.
        approved = x["status"] == "approved"
        explanation = {
            "status": x["status"],
            "text": x["final_text"] if approved else None,
            "questions": x["questions"] if approved else [],
            "reviewed_by": x["reviewed_by"],
            "reviewed_at": x["reviewed_at"],
        }
        if user.role == "clinician":
            explanation["draft_text"] = x["draft_text"]
            explanation["produced_by"] = x["produced_by"]

    audit.record(conn, action="report_viewed", entity_type="diagnostic_report", entity_id=report_id, actor=user,
                 patient_id=report["patient_id"])
    return {**report, "observations": observations, "explanation": explanation}


# --- Care plan -------------------------------------------------------------------------------


@router.get("/patients/{patient_id}/care-plan")
def care_plan(patient_id: str, conn: Conn, user: CurrentUser) -> dict | None:
    assert_patient_access(conn, user, patient_id)
    plan = conn.execute(
        """
        SELECT c.id::text, c.title, c.started_at, c.status,
               pr.id::text AS practitioner_id, pr.name AS practitioner_name, pr.specialty
        FROM care_plans c JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s AND c.status = 'active'
        ORDER BY c.started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if plan is None:
        return None
    tasks = conn.execute(
        """
        SELECT id::text, position, kind, title, detail, specialty, due_on, status, completed_at
        FROM care_plan_tasks WHERE care_plan_id = %s ORDER BY position
        """,
        (plan["id"],),
    ).fetchall()
    today = date.today()
    for t in tasks:
        t["overdue"] = t["status"] == "todo" and t["due_on"] is not None and t["due_on"] < today
        t["due_today"] = t["status"] == "todo" and t["due_on"] == today
    todo = [t for t in tasks if t["status"] == "todo"]
    nxt = min(todo, key=lambda t: (t["due_on"] or date.max, t["position"])) if todo else None
    return {
        **plan,
        "tasks": tasks,
        "done_count": len(tasks) - len(todo),
        "total_count": len(tasks),
        "next_task_id": nxt["id"] if nxt else None,
    }


class TaskUpdate(BaseModel):
    status: Literal["todo", "done"]


@router.patch("/care-plan-tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate, conn: Conn, user: CurrentUser) -> dict:
    row = conn.execute(
        """
        SELECT t.id::text, c.patient_id::text FROM care_plan_tasks t
        JOIN care_plans c ON c.id = t.care_plan_id WHERE t.id = %s
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    assert_patient_access(conn, user, row["patient_id"])
    updated = conn.execute(
        """
        UPDATE care_plan_tasks
        SET status = %s, completed_at = CASE WHEN %s = 'done' THEN now() ELSE NULL END
        WHERE id = %s
        RETURNING id::text, status, completed_at
        """,
        (body.status, body.status, task_id),
    ).fetchone()
    audit.record(conn, action=f"task_{body.status}", entity_type="care_plan_task", entity_id=task_id, actor=user,
                 patient_id=row["patient_id"])
    return updated


# --- My Health Story -------------------------------------------------------------------------


def _month(d: datetime) -> str:
    return d.strftime("%B")


@router.get("/patients/{patient_id}/story")
def story(patient_id: str, conn: Conn, user: CurrentUser, year: int | None = None) -> dict:
    """A plain-language year in review, assembled only from the record. Nothing is inferred."""
    assert_patient_access(conn, user, patient_id)
    year = year or date.today().year
    since = datetime(year, 1, 1, tzinfo=timezone.utc)

    events = timeline.events(conn, patient_id, since=since)
    counts = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM encounters WHERE patient_id = %(p)s AND occurred_at >= %(s)s) AS visits,
          (SELECT count(*) FROM diagnostic_reports WHERE patient_id = %(p)s AND collected_at >= %(s)s) AS lab_panels,
          (SELECT count(*) FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
             WHERE c.patient_id = %(p)s AND t.kind = 'medication' AND c.started_at >= %(s)s) AS new_medicines,
          (SELECT count(*) FROM care_gaps WHERE patient_id = %(p)s AND status = 'open') AS care_gaps
        """,
        {"p": patient_id, "s": since},
    ).fetchone()
    gaps = conn.execute(
        "SELECT id::text, title, detail, specialty FROM care_gaps WHERE patient_id = %s AND status = 'open'",
        (patient_id,),
    ).fetchall()
    trends = timeline.abnormal_trends(conn, patient_id)
    plans = conn.execute(
        """
        SELECT c.title, c.started_at, pr.name AS practitioner FROM care_plans c
        JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s AND c.started_at >= %s ORDER BY c.started_at
        """,
        (patient_id, since),
    ).fetchall()
    vaccines = conn.execute(
        "SELECT vaccine FROM immunizations WHERE patient_id = %s AND occurred_at >= %s", (patient_id, since)
    ).fetchall()

    sentences = []
    if trends:
        t = trends[0]
        direction = ""
        hist = t["history"] or []
        if len(hist) >= 2:
            direction = " and has been rising" if hist[-1]["value"] > hist[0]["value"] else " and has been falling"
        sentences.append(f"Your latest {t['display']} is outside the target range{direction}.")
    for p in plans:
        sentences.append(f"In {_month(p['started_at'])} you started a care plan with {p['practitioner']}: {p['title'].lower()}.")
    for v in vaccines:
        sentences.append(f"Your {v['vaccine'].lower()} is up to date.")
    if gaps:
        sentences.append(f"One thing is overdue: {gaps[0]['title'].lower()}." if len(gaps) == 1
                         else f"{len(gaps)} things are overdue.")
    if not sentences:
        sentences.append("It's been a quiet year in your record so far.")

    return {
        "year": year,
        "counts": counts,
        "summary": " ".join(sentences),
        "summary_source": "record",
        "events": events,
        "gaps": gaps,
    }
