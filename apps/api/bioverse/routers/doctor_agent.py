"""Doctor Agent runtime endpoints (module 8): pre-visit interviews, follow-up check-ins, approved content.

The per-clinician configuration itself is edited in the clinician router (`/api/clinician/agent-config`);
these endpoints only run it. Patient answers arrive through `/api/messages/threads/{id}/messages`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection

from bioverse import audit
from bioverse.agents import doctor_agent as agent
from bioverse.auth import CurrentUser, User, Workforce, assert_patient_access
from bioverse.db import DbConn

router = APIRouter(prefix="/api/doctor-agent", tags=["doctor agent"])

Conn = DbConn


def _appointment(conn: Connection, user: User, appointment_id: str) -> dict:
    try:
        UUID(appointment_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found") from None
    row = conn.execute(
        """
        SELECT a.id::text, a.patient_id::text, a.practitioner_id::text, a.status, s.starts_at, pr.name AS practitioner_name
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.id = %s
        """,
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if user.role == "patient":
        if row["patient_id"] != user.patient_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    elif user.role in ("clinician", "staff"):
        assert_patient_access(conn, user, row["patient_id"])
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for this role")
    return row


def _enabled_questions(conn: Connection, practitioner_id: str) -> list[dict] | None:
    """Enabled pre-visit questions, or None when the clinician's agent is off or not configured."""
    config = agent.load_config(conn, practitioner_id)
    if not config or not config["active"]:
        return None
    return [q for q in config["previsit_questions"] if q["enabled"]]


@router.get("/previsit")
def list_previsit(conn: Conn, user: CurrentUser) -> list[dict]:
    """Upcoming appointments whose clinician runs a pre-visit interview, with its status."""
    if user.role == "patient":
        where, params = "a.patient_id = %s", (user.patient_id,)
    elif user.role == "clinician":
        where, params = "a.practitioner_id = %s", (user.practitioner_id,)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for this role")
    rows = conn.execute(
        f"""
        SELECT a.id::text AS appointment_id, s.starts_at, pr.name AS practitioner_name, p.name AS patient_name,
               a.patient_id::text, t.id::text AS thread_id, t.agent_state->'previsit'->>'status' AS status,
               (SELECT count(*) FROM jsonb_array_elements(d.previsit_questions) q WHERE (q->>'enabled')::boolean) AS questions
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        JOIN patients p ON p.id = a.patient_id
        JOIN doctor_agent_configs d ON d.practitioner_id = a.practitioner_id AND d.active
        LEFT JOIN communication_threads t ON t.appointment_id = a.id AND t.kind = 'previsit'
        WHERE {where} AND a.status = 'booked' AND s.starts_at > now()
        ORDER BY s.starts_at
        """,
        params,
    ).fetchall()
    return [
        {**r, "status": r["status"] or "not_started", "practitioner_label": agent.short_name(r["practitioner_name"])}
        for r in rows
        if r["questions"] > 0
    ]


@router.post("/previsit/{appointment_id}/start", status_code=status.HTTP_201_CREATED)
def start_previsit(appointment_id: str, conn: Conn, user: CurrentUser) -> dict:
    """Start (or return) the pre-visit interview for an upcoming appointment with a configured clinician."""
    appt = _appointment(conn, user, appointment_id)
    if user.role == "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The patient or their clinician starts the interview")
    if user.role == "clinician" and appt["practitioner_id"] != user.practitioner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient's own clinician can start this")
    if appt["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "This appointment is not booked")
    if appt["starts_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_409_CONFLICT, "This appointment has already started")
    questions = _enabled_questions(conn, appt["practitioner_id"])
    if not questions:
        raise HTTPException(status.HTTP_409_CONFLICT, "This clinician has no pre-visit questions switched on")
    conn.execute("SELECT 1 FROM appointments WHERE id = %s FOR UPDATE", (appointment_id,))
    thread = agent.start_previsit(conn, user, appt)
    return {"thread_id": thread["id"], "status": thread["agent_state"]["previsit"]["status"],
            "questions": len(thread["agent_state"]["previsit"]["questions"])}


@router.get("/previsit/{appointment_id}/answers")
def previsit_answers(appointment_id: str, conn: Conn, user: CurrentUser) -> dict:
    appt = _appointment(conn, user, appointment_id)
    rows = conn.execute(
        """
        SELECT id::text, question_id, question_text, answer_text, mentions_symptoms, created_at
        FROM questionnaire_responses WHERE appointment_id = %s ORDER BY created_at
        """,
        (appointment_id,),
    ).fetchall()
    if user.role != "patient":
        audit.record(conn, action="previsit_answers_viewed", entity_type="appointment", entity_id=appointment_id,
                     actor=user, patient_id=appt["patient_id"])
    return {"appointment_id": appointment_id, "answers": rows}


@router.post("/followups/materialize")
def materialize(conn: Conn, user: CurrentUser) -> dict:
    """Send due follow-up check-ins now. Idempotent; the messages screens also call this implicitly."""
    if user.role == "patient":
        ids = [user.patient_id]
    elif user.role == "clinician":
        ids = [r["patient_id"] for r in conn.execute(
            "SELECT DISTINCT patient_id::text FROM care_plans WHERE practitioner_id = %s AND status = 'active'",
            (user.practitioner_id,),
        ).fetchall()]
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for this role")
    return {"sent": agent.materialize_followups(conn, patient_ids=ids, actor=user)}


@router.get("/followups")
def list_followups(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> list[dict]:
    """Scheduled and sent check-ins for a patient (patients: their own)."""
    if user.role == "patient":
        patient_id = user.patient_id
    elif user.role in ("clinician", "staff"):
        if not patient_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "patient_id is required")
        try:
            UUID(patient_id)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found") from None
        assert_patient_access(conn, user, patient_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for this role")
    return conn.execute(
        """
        SELECT r.id::text, r.step_day, r.action, r.due_on, r.status, r.sent_at, t.title AS task_title,
               ct.id::text AS thread_id
        FROM communication_requests r
        JOIN care_plan_tasks t ON t.id = r.task_id
        LEFT JOIN communication_threads ct ON ct.care_plan_id = r.care_plan_id AND ct.kind = 'followup'
        WHERE r.patient_id = %s ORDER BY r.due_on, r.step_day
        """,
        (patient_id,),
    ).fetchall()


@router.get("/content")
def education_content(conn: Conn, user: Workforce) -> list[dict]:
    """The approved education library the Doctor Agent may quote from."""
    return conn.execute(
        """
        SELECT e.id::text, e.topic, e.title, e.body, e.medications, e.symptoms, e.approved_at, u.display_name AS approved_by
        FROM education_content e LEFT JOIN users u ON u.id = e.approved_by
        WHERE e.organization_id = %s AND e.status = 'approved' ORDER BY e.topic DESC, e.title
        """,
        (user.organization_id,),
    ).fetchall()
