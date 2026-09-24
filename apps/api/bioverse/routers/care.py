"""Care navigator and scheduling."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection
from pydantic import BaseModel

from bioverse import audit
from bioverse.auth import CurrentUser, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.safety.red_flags import EMERGENCY_NUMBER

router = APIRouter(prefix="/api", tags=["care"])

Conn = DbConn


def _patient_id_for(user: User, patient_id: str | None) -> str:
    if user.role == "patient":
        return user.patient_id  # type: ignore[return-value]
    if not patient_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
    return patient_id


@router.get("/care/options")
def care_options(
    conn: Conn,
    user: CurrentUser,
    specialty: str | None = None,
    intake_id: str | None = None,
    patient_id: str | None = None,
) -> dict:
    """Best three matches for a specialty, ranked by language, coverage, then earliest availability."""
    pid = _patient_id_for(user, patient_id)
    assert_patient_access(conn, user, pid)

    urgency = "routine"
    if intake_id:
        intake = conn.execute(
            "SELECT specialty, urgency FROM intakes WHERE id = %s AND patient_id = %s", (intake_id, pid)
        ).fetchone()
        if intake is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        urgency = intake["urgency"]
        specialty = specialty or intake["specialty"]
        # Never offer a lower level of care than the intake called for.
        if urgency == "emergency":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "emergency", "message": f"This needs emergency care. Call {EMERGENCY_NUMBER} now.",
                 "emergency_number": EMERGENCY_NUMBER},
            )
    if not specialty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "specialty or intake_id is required")

    patient = conn.execute(
        "SELECT preferred_language, insurance_plan, organization_id FROM patients WHERE id = %s", (pid,)
    ).fetchone()

    rows = conn.execute(
        """
        SELECT pr.id::text, pr.name, pr.specialty, pr.location_name, pr.distance_km, pr.languages,
               pr.accessibility, pr.offers_telehealth,
               %(lang)s = ANY(pr.languages) AS language_match,
               %(plan)s = ANY(pr.accepted_plans) AS in_network,
               nxt.id::text AS slot_id, nxt.starts_at, nxt.mode
        FROM practitioners pr
        JOIN LATERAL (
            SELECT s.id, s.starts_at, s.mode FROM slots s
            WHERE s.practitioner_id = pr.id AND s.status = 'free' AND s.starts_at > now()
            ORDER BY s.starts_at LIMIT 1
        ) nxt ON true
        WHERE pr.organization_id = %(org)s AND lower(pr.specialty) = lower(%(spec)s)
        """,
        {"lang": patient["preferred_language"], "plan": patient["insurance_plan"],
         "org": patient["organization_id"], "spec": specialty},
    ).fetchall()

    if urgency == "urgent":
        rows.sort(key=lambda r: r["starts_at"])
    else:
        rows.sort(key=lambda r: (not r["language_match"], not r["in_network"], r["starts_at"]))
    top = rows[:3]
    earliest_id = min(top, key=lambda r: r["starts_at"])["id"] if top else None

    options = []
    for i, r in enumerate(top):
        reasons = []
        if r["mode"] != "video":
            reasons.append(f"{r['distance_km']:.1f} km")
        if r["in_network"]:
            reasons.append("In network")
        if r["language_match"] and patient["preferred_language"] != "English":
            reasons.append(f"Speaks {patient['preferred_language']}")
        reasons.extend(a for a in r["accessibility"] if a != "Remote")
        badges = []
        if i == 0:
            badges.append("Best match")
        if r["id"] == earliest_id:
            badges.append("Earliest")
        options.append({
            "practitioner_id": r["id"],
            "name": r["name"],
            "specialty": r["specialty"],
            "location": r["location_name"],
            "reasons": reasons,
            "badges": badges,
            "next_slot": {"id": r["slot_id"], "starts_at": r["starts_at"], "mode": r["mode"]},
        })

    matched_on = ["specialty", "coverage", "language", "availability"]
    return {
        "specialty": specialty,
        "urgency": urgency,
        "preferred_language": patient["preferred_language"],
        "matched_on": matched_on,
        "options": options,
    }


@router.get("/practitioners/{practitioner_id}/slots")
def practitioner_slots(practitioner_id: str, conn: Conn, user: CurrentUser, limit: int = Query(8, le=30)) -> list[dict]:
    return conn.execute(
        """
        SELECT s.id::text, s.starts_at, s.mode, s.duration_min
        FROM slots s JOIN practitioners pr ON pr.id = s.practitioner_id
        WHERE s.practitioner_id = %s AND pr.organization_id = %s AND s.status = 'free' AND s.starts_at > now()
        ORDER BY s.starts_at LIMIT %s
        """,
        (practitioner_id, user.organization_id, limit),
    ).fetchall()


class BookIn(BaseModel):
    slot_id: str
    intake_id: str | None = None
    care_plan_task_id: str | None = None
    reason: str | None = None


def _appointment(conn: Connection, appointment_id: str) -> dict:
    return conn.execute(
        """
        SELECT a.id::text, a.status, a.reason, s.starts_at, s.mode, s.duration_min,
               pr.id::text AS practitioner_id, pr.name AS practitioner_name, pr.specialty, pr.location_name
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.id = %s
        """,
        (appointment_id,),
    ).fetchone()


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
def book(body: BookIn, conn: Conn, user: CurrentUser) -> dict:
    if user.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only patients book their own appointments in this demo")
    pid = user.patient_id

    if body.intake_id:
        intake = conn.execute("SELECT urgency FROM intakes WHERE id = %s AND patient_id = %s", (body.intake_id, pid)).fetchone()
        if intake is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        if intake["urgency"] == "emergency":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "emergency", "message": f"Call {EMERGENCY_NUMBER} now.", "emergency_number": EMERGENCY_NUMBER},
            )

    # Lock the slot row: two patients cannot take the same time.
    slot = conn.execute(
        """
        SELECT s.id::text, s.practitioner_id::text, s.status, s.starts_at > now() AS in_future
        FROM slots s JOIN practitioners pr ON pr.id = s.practitioner_id
        WHERE s.id = %s AND pr.organization_id = %s
        FOR UPDATE OF s
        """,
        (body.slot_id, user.organization_id),
    ).fetchone()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    if slot["status"] != "free" or not slot["in_future"]:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "slot_taken", "message": "That time was just taken. Please pick another."})

    conn.execute("UPDATE slots SET status = 'booked' WHERE id = %s", (slot["id"],))
    appt = conn.execute(
        """
        INSERT INTO appointments (patient_id, practitioner_id, slot_id, intake_id, reason)
        VALUES (%s, %s, %s, %s, %s) RETURNING id::text
        """,
        (pid, slot["practitioner_id"], slot["id"], body.intake_id, body.reason),
    ).fetchone()

    completed_task = None
    if body.care_plan_task_id:
        completed_task = conn.execute(
            """
            UPDATE care_plan_tasks t SET status = 'done', completed_at = now()
            FROM care_plans c
            WHERE t.id = %s AND t.care_plan_id = c.id AND c.patient_id = %s AND t.kind = 'appointment'
            RETURNING t.id::text
            """,
            (body.care_plan_task_id, pid),
        ).fetchone()

    audit.record(
        conn,
        action="appointment_booked",
        entity_type="appointment",
        entity_id=appt["id"],
        actor=user,
        agent="scheduling-agent",
        detail={"slot_id": slot["id"], "intake_id": body.intake_id, "care_plan_task_id": body.care_plan_task_id},
    )
    result = _appointment(conn, appt["id"])
    result["completed_task_id"] = completed_task["id"] if completed_task else None
    return result


@router.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: str, conn: Conn, user: CurrentUser) -> dict:
    row = conn.execute(
        "SELECT id::text, slot_id::text, status FROM appointments WHERE id = %s AND patient_id = %s FOR UPDATE",
        (appointment_id, user.patient_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if row["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is not active")
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (appointment_id,))
    conn.execute("UPDATE slots SET status = 'free' WHERE id = %s", (row["slot_id"],))
    audit.record(conn, action="appointment_cancelled", entity_type="appointment", entity_id=appointment_id, actor=user)
    return _appointment(conn, appointment_id)


@router.get("/patients/{patient_id}/appointments")
def upcoming(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    assert_patient_access(conn, user, patient_id)
    ids = conn.execute(
        """
        SELECT a.id::text FROM appointments a JOIN slots s ON s.id = a.slot_id
        WHERE a.patient_id = %s AND a.status = 'booked' AND s.starts_at > now()
        ORDER BY s.starts_at
        """,
        (patient_id,),
    ).fetchall()
    return [_appointment(conn, r["id"]) for r in ids]
