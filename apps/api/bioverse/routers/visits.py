"""Appointment and Visit Navigator: before, during and after a visit.

Before: upcoming visits with a pre-visit checklist that persists, questions to ask, and location details.
During: patient check-in (from 60 minutes before the start, on the day), queue position and estimated wait,
        and the clinic queue where clinicians and staff room, start, complete or mark a no-show.
After:  the clinician's after-visit summary, published directly (the clinician is the author).

Day-of-visit status lives in `appointment_encounters`; no row means "booked". Completing a visit marks the
appointment 'fulfilled' and writes an `encounters` row, so it shows up as a past visit everywhere.
"""

from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Clinician, CurrentUser, Patient, User, Workforce, assert_patient_access
from bioverse.db import DbConn
from bioverse.safety import red_flags

router = APIRouter(prefix="/api/visits", tags=["visits"])

Conn = DbConn

CHECK_IN_OPENS_MIN = 60           # patients can check in from this many minutes before the start
DEFAULT_VISIT_MINUTES = 20        # per-visit estimate when a slot has no duration
IN_PROGRESS_MIN_REMAINING = 5     # a visit in progress is assumed to need at least this long

ACTIVE = ("arrived", "roomed", "in_progress")

# Allowed day-of-visit transitions. "booked" means no encounter row yet.
TRANSITIONS: dict[str, set[str]] = {
    "booked": {"arrived", "no_show"},
    "arrived": {"roomed", "in_progress"},   # arrived -> in_progress only for video visits (no room)
    "roomed": {"in_progress"},
    "in_progress": {"completed"},
    "completed": set(),
    "no_show": set(),
}

STATUS_LABEL = {
    "booked": "Booked",
    "arrived": "Checked in",
    "roomed": "In a room",
    "in_progress": "With clinician",
    "completed": "Completed",
    "no_show": "No-show",
}

_FASTING = re.compile(
    r"\b(fasting|fast\b|lipid|cholesterol|blood (?:test|work|draw)|glucose|a1c|lab work)", re.IGNORECASE
)


def clinic_tz() -> str:
    return os.getenv("BIOVERSE_CLINIC_TZ", "America/New_York")


def clinic_today(conn: Connection) -> date:
    return conn.execute("SELECT (now() AT TIME ZONE %s)::date AS d", (clinic_tz(),)).fetchone()["d"]


def _now(conn: Connection) -> datetime:
    return conn.execute("SELECT now() AS t").fetchone()["t"]


# --- Checklist -------------------------------------------------------------------------------------


def checklist_template(appt: dict) -> list[tuple[str, str, str | None]]:
    """(key, label, detail) for one appointment. Depends on visit mode and the reason for the visit."""
    video = appt.get("mode") == "video" or appt.get("location_name") == "Video visit"
    items: list[tuple[str, str, str | None]] = [
        ("medications", "Confirm your medication list",
         "Check the medicines we have on file, and note anything you have started, stopped or changed."),
    ]
    if video:
        items += [
            ("tech_check", "Test your camera, microphone and internet",
             "Open the join link 15 minutes early so there is time to fix any problems."),
            ("private_space", "Find a quiet, private place", "Somewhere you can talk openly, with good light."),
            ("insurance", "Have your insurance card and photo ID nearby",
             "The team may ask you to hold them up to the camera."),
        ]
    else:
        items += [
            ("insurance", "Bring your insurance card and photo ID", None),
            ("arrive_early", "Arrive 15 minutes early", "This leaves time for parking and check-in."),
        ]
    if _FASTING.search(appt.get("reason") or ""):
        items.append((
            "fasting", "Fast before your visit",
            "Have nothing to eat or drink except water for 8 to 12 hours before, unless your care team told you "
            "otherwise. Keep taking your usual medicines with water.",
        ))
    items.append((
        "questions", "Answer your clinician's questions and write down your own",
        "You can add questions below. Your clinician will see them before the visit.",
    ))
    return items


def ensure_checklist(conn: Connection, appt: dict) -> None:
    """Create any missing checklist items for an appointment. Existing items (and their ticks) are kept."""
    for pos, (key, label, detail) in enumerate(checklist_template(appt), start=1):
        conn.execute(
            """
            INSERT INTO appointment_checklist_items (appointment_id, patient_id, item_key, position, label, detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (appointment_id, item_key) DO NOTHING
            """,
            (appt["id"], appt["patient_id"], key, pos, label, detail),
        )


# --- Queue and wait estimate -----------------------------------------------------------------------


def _minutes(delta: timedelta) -> int:
    return math.ceil(delta.total_seconds() / 60)


def estimate_wait(rows: list[dict], me: dict, now: datetime) -> dict:
    """Queue position and estimated wait for one arrived patient.

    rows: every active (arrived / roomed / in_progress) appointment in the same clinician's queue that day,
    each with appointment_id, status, arrived_at, started_at, starts_at and duration_min.

    Position counts patients still waiting who arrived earlier. The wait adds each visit ahead (waiting or
    in a room) at its booked length, and what is left of any visit in progress. Nobody is seen before their
    booked time, so the wait is never shorter than the time left until the appointment starts.
    """
    if me["status"] != "arrived":
        return {"position": None, "ahead": 0, "wait_minutes": 0}
    key = (me["arrived_at"], me["appointment_id"])
    waiting_ahead = [r for r in rows if r["status"] == "arrived" and (r["arrived_at"], r["appointment_id"]) < key]
    being_seen = [r for r in rows if r["status"] in ("roomed", "in_progress") and r["appointment_id"] != me["appointment_id"]]
    minutes = 0
    for r in waiting_ahead:
        minutes += r["duration_min"] or DEFAULT_VISIT_MINUTES
    for r in being_seen:
        length = r["duration_min"] or DEFAULT_VISIT_MINUTES
        if r["status"] == "in_progress" and r["started_at"]:
            minutes += max(length - _minutes(now - r["started_at"]), IN_PROGRESS_MIN_REMAINING)
        else:
            minutes += length
    until_start = _minutes(me["starts_at"] - now)
    return {
        "position": len(waiting_ahead) + 1,
        "ahead": len(waiting_ahead) + len(being_seen),
        "wait_minutes": max(minutes, until_start, 0),
    }


def _active_rows(conn: Connection, practitioner_id: str, day: date) -> list[dict]:
    return conn.execute(
        """
        SELECT e.appointment_id::text, e.status, e.arrived_at, e.started_at, s.starts_at, s.duration_min
        FROM appointment_encounters e
        JOIN appointments a ON a.id = e.appointment_id
        JOIN slots s ON s.id = a.slot_id
        WHERE e.practitioner_id = %s AND e.status IN ('arrived', 'roomed', 'in_progress')
          AND (s.starts_at AT TIME ZONE %s)::date = %s
        """,
        (practitioner_id, clinic_tz(), day),
    ).fetchall()


def live_status(conn: Connection, appt: dict, now: datetime) -> dict:
    """What the patient sees on the day: status, room, queue position and estimated wait."""
    st = appt["visit_status"] or "booked"
    out = {
        "status": st,
        "label": STATUS_LABEL[st],
        "room": appt.get("room"),
        "arrived_at": appt.get("arrived_at"),
        "position": None,
        "ahead": 0,
        "wait_minutes": None,
    }
    if st == "arrived":
        rows = _active_rows(conn, appt["practitioner_id"], appt["clinic_date"])
        me = next(r for r in rows if r["appointment_id"] == appt["id"])
        out.update(estimate_wait(rows, me, now))
    return out


def check_in_window(appt: dict, now: datetime, today: date) -> dict:
    """Check-in opens 60 minutes before the start and stays open for the rest of that clinic day."""
    opens_at = appt["starts_at"] - timedelta(minutes=CHECK_IN_OPENS_MIN)
    if (appt["visit_status"] or "booked") != "booked":
        return {"allowed": False, "code": "already_checked_in", "opens_at": opens_at}
    if now < opens_at:
        return {"allowed": False, "code": "too_early", "opens_at": opens_at}
    if today > appt["clinic_date"]:
        return {"allowed": False, "code": "missed", "opens_at": opens_at}
    return {"allowed": True, "code": "open", "opens_at": opens_at}


# --- Loading ----------------------------------------------------------------------------------------

_APPT_SQL = """
    SELECT a.id::text, a.patient_id::text, a.status AS appointment_status, a.reason, a.created_at,
           s.starts_at, s.duration_min, s.mode, (s.starts_at AT TIME ZONE %(tz)s)::date AS clinic_date,
           pr.id::text AS practitioner_id, pr.name AS practitioner_name, pr.specialty, pr.location_name,
           pr.organization_id::text AS organization_id,
           e.status AS visit_status, e.room, e.arrived_at, e.roomed_at, e.started_at, e.completed_at,
           e.encounter_id::text
    FROM appointments a
    JOIN slots s ON s.id = a.slot_id
    JOIN practitioners pr ON pr.id = a.practitioner_id
    LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
"""


def valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _load_appt(conn: Connection, appointment_id: str, lock: bool = False) -> dict:
    row = None
    if valid_uuid(appointment_id):
        row = conn.execute(
            _APPT_SQL + " WHERE a.id = %(id)s" + (" FOR UPDATE OF a" if lock else ""),
            {"tz": clinic_tz(), "id": appointment_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return row


def _location(conn: Connection, organization_id: str, name: str) -> dict | None:
    return conn.execute(
        """
        SELECT name, mode, address, phone, parking, directions, accessibility, join_url, tech_check
        FROM locations WHERE organization_id = %s AND name = %s
        """,
        (organization_id, name),
    ).fetchone()


def _checklist(conn: Connection, appointment_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT id::text, item_key, label, detail, done_at IS NOT NULL AS done, done_at
        FROM appointment_checklist_items WHERE appointment_id = %s ORDER BY position
        """,
        (appointment_id,),
    ).fetchall()


def _questions(conn: Connection, appointment_id: str) -> list[dict]:
    return conn.execute(
        "SELECT id::text, text, created_at FROM appointment_questions WHERE appointment_id = %s ORDER BY created_at",
        (appointment_id,),
    ).fetchall()


def _clinician_questions(conn: Connection, practitioner_id: str) -> list[str]:
    row = conn.execute(
        "SELECT active, previsit_questions FROM doctor_agent_configs WHERE practitioner_id = %s", (practitioner_id,)
    ).fetchone()
    if not row or not row["active"]:
        return []
    return [q["text"] for q in row["previsit_questions"] if q.get("enabled")]


def _suggested_questions(conn: Connection, patient_id: str) -> list[str]:
    """Questions suggested alongside the patient's latest clinician-approved result explanation."""
    row = conn.execute(
        """
        SELECT x.questions FROM result_explanations x JOIN diagnostic_reports r ON r.id = x.report_id
        WHERE r.patient_id = %s AND x.status = 'approved' AND jsonb_array_length(x.questions) > 0
        ORDER BY r.collected_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    return list(row["questions"]) if row else []


def _patient_id_for(user: User, patient_id: str | None) -> str:
    if user.role == "patient":
        return user.patient_id  # type: ignore[return-value]
    if not patient_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
    return patient_id


def _visit_view(conn: Connection, appt: dict, now: datetime, today: date, suggested: list[str]) -> dict:
    ensure_checklist(conn, appt)
    questions = _questions(conn, appt["id"])
    asked = {q["text"].strip().lower() for q in questions}
    return {
        "id": appt["id"],
        "starts_at": appt["starts_at"],
        "duration_min": appt["duration_min"],
        "mode": appt["mode"],
        "reason": appt["reason"],
        "is_today": appt["clinic_date"] == today,
        "practitioner": {"id": appt["practitioner_id"], "name": appt["practitioner_name"], "specialty": appt["specialty"]},
        "location": _location(conn, appt["organization_id"], appt["location_name"]) or {"name": appt["location_name"]},
        "checklist": _checklist(conn, appt["id"]),
        "questions": questions,
        "suggested_questions": [q for q in suggested if q.strip().lower() not in asked],
        "clinician_questions": _clinician_questions(conn, appt["practitioner_id"]),
        "check_in": check_in_window(appt, now, today),
        "live": live_status(conn, appt, now),
        "reschedule_to": f"/care/find?specialty={quote(appt['specialty'])}",
    }


# --- Patient: before and during -------------------------------------------------------------------


@router.get("")
def my_visits(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    """Upcoming visits (with checklist, location, check-in and live status) and past visits (with summaries)."""
    pid = _patient_id_for(user, patient_id)
    assert_patient_access(conn, user, pid)
    now, today = _now(conn), clinic_today(conn)

    upcoming = conn.execute(
        _APPT_SQL
        + """
        WHERE a.patient_id = %(p)s AND a.status = 'booked'
          AND coalesce(e.status, 'booked') NOT IN ('completed', 'no_show')
          AND (s.starts_at > now() OR (s.starts_at AT TIME ZONE %(tz)s)::date = %(today)s)
        ORDER BY s.starts_at
        """,
        {"tz": clinic_tz(), "p": pid, "today": today},
    ).fetchall()
    suggested = _suggested_questions(conn, pid)

    past = conn.execute(
        """
        SELECT e.id::text, e.occurred_at AS at, e.kind, e.summary,
               pr.name AS practitioner_name, pr.specialty, pr.location_name,
               avs.id::text AS summary_id, avs.instructions, avs.follow_up, avs.prescriptions, avs.published_at,
               u.display_name AS author
        FROM encounters e
        LEFT JOIN practitioners pr ON pr.id = e.practitioner_id
        LEFT JOIN after_visit_summaries avs ON avs.encounter_id = e.id
        LEFT JOIN users u ON u.id = avs.author_user_id
        WHERE e.patient_id = %s
        ORDER BY e.occurred_at DESC
        LIMIT 30
        """,
        (pid,),
    ).fetchall()
    missed = conn.execute(
        """
        SELECT a.id::text, s.starts_at AS at, pr.name AS practitioner_name, pr.specialty, pr.location_name
        FROM appointment_encounters e
        JOIN appointments a ON a.id = e.appointment_id
        JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE e.patient_id = %s AND e.status = 'no_show'
        """,
        (pid,),
    ).fetchall()

    past_visits = [
        {
            "id": r["id"], "kind": "visit", "at": r["at"], "title": r["kind"], "note": r["summary"],
            "practitioner_name": r["practitioner_name"], "specialty": r["specialty"], "location_name": r["location_name"],
            "summary": None if not r["summary_id"] else {
                "instructions": r["instructions"], "follow_up": r["follow_up"], "prescriptions": r["prescriptions"],
                "published_at": r["published_at"], "author": r["author"],
            },
        }
        for r in past
    ] + [
        {
            "id": r["id"], "kind": "missed", "at": r["at"], "title": f"Missed visit · {r['specialty']}", "note": None,
            "practitioner_name": r["practitioner_name"], "specialty": r["specialty"], "location_name": r["location_name"],
            "summary": None,
        }
        for r in missed
    ]
    past_visits.sort(key=lambda v: v["at"], reverse=True)

    return {
        "upcoming": [_visit_view(conn, a, now, today, suggested) for a in upcoming],
        "past": past_visits,
        "check_in_opens_minutes": CHECK_IN_OPENS_MIN,
    }


def _own_appointment(conn: Connection, user: User, appointment_id: str, lock: bool = False) -> dict:
    appt = _load_appt(conn, appointment_id, lock=lock)
    if user.role == "patient" and appt["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    assert_patient_access(conn, user, appt["patient_id"])
    return appt


class ChecklistUpdate(BaseModel):
    done: bool


@router.patch("/checklist/{item_id}")
def tick(item_id: str, body: ChecklistUpdate, conn: Conn, user: CurrentUser) -> dict:
    item = None
    if valid_uuid(item_id):
        item = conn.execute(
            "SELECT id::text, patient_id::text, appointment_id::text FROM appointment_checklist_items WHERE id = %s",
            (item_id,),
        ).fetchone()
    if item is None or (user.role == "patient" and item["patient_id"] != user.patient_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")
    assert_patient_access(conn, user, item["patient_id"])
    row = conn.execute(
        """
        UPDATE appointment_checklist_items
        SET done_at = CASE WHEN %(done)s THEN coalesce(done_at, now()) ELSE NULL END,
            done_by = CASE WHEN %(done)s THEN %(u)s::uuid ELSE NULL END
        WHERE id = %(id)s
        RETURNING id::text, item_key, label, detail, done_at IS NOT NULL AS done, done_at
        """,
        {"done": body.done, "u": user.id, "id": item_id},
    ).fetchone()
    audit.record(conn, action="visit_checklist_" + ("done" if body.done else "undone"), entity_type="appointment",
                 entity_id=item["appointment_id"], actor=user, patient_id=item["patient_id"],
                 detail={"item": row["item_key"]})
    return row


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/{appointment_id}/questions", status_code=status.HTTP_201_CREATED)
def add_question(appointment_id: str, body: QuestionIn, conn: Conn, user: Patient) -> dict:
    appt = _own_appointment(conn, user, appointment_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Write a question first")
    if appt["appointment_status"] != "booked" or (appt["visit_status"] or "booked") in ("completed", "no_show"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This visit is over. Ask Bioverse or message your care team instead.")

    # Free text from a patient: screen for red flags before anything else.
    screen = red_flags.screen(text)
    if screen.level in ("emergency", "crisis"):
        conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
            VALUES ('red_flag', %s, %s, %s, %s, %s, 'urgent', '/clinician/queue')
            """,
            (appt["patient_id"], appt["practitioner_id"], appt["id"],
             f"Red flag · {', '.join(screen.flags)}",
             f"Written as a pre-visit question. Patient was advised to seek emergency care. They wrote: \"{text}\""),
        )
        audit.record(conn, action="red_flag_escalation", entity_type="appointment", entity_id=appt["id"], actor=user,
                     patient_id=appt["patient_id"], agent="safety/red-flags",
                     detail={"flags": screen.flags, "level": screen.level, "ruleset": screen.ruleset, "source": "visit_question"})
        # Commit the escalation, then stop routine flow: the question is not saved as a routine question.
        conn.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "emergency",
                "message": red_flags.emergency_message(screen),
                "emergency_number": red_flags.EMERGENCY_NUMBER,
                "crisis_line": red_flags.CRISIS_LINE if screen.level == "crisis" else None,
            },
        )

    row = conn.execute(
        """
        INSERT INTO appointment_questions (appointment_id, patient_id, text) VALUES (%s, %s, %s)
        RETURNING id::text, text, created_at
        """,
        (appt["id"], appt["patient_id"], text),
    ).fetchone()
    audit.record(conn, action="visit_question_added", entity_type="appointment", entity_id=appt["id"], actor=user,
                 patient_id=appt["patient_id"])
    notice = None
    if screen.level == "screen":
        notice = (
            "If you have these symptoms right now, don't wait for your visit. Use Ask Bioverse for a quick safety "
            f"check, or call {red_flags.EMERGENCY_NUMBER} in an emergency."
        )
    return {**row, "safety_notice": notice}


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(question_id: str, conn: Conn, user: Patient) -> None:
    row = None
    if valid_uuid(question_id):
        row = conn.execute(
            "DELETE FROM appointment_questions WHERE id = %s AND patient_id = %s RETURNING appointment_id::text",
            (question_id, user.patient_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    audit.record(conn, action="visit_question_removed", entity_type="appointment", entity_id=row["appointment_id"],
                 actor=user, patient_id=user.patient_id)


def _set_status(conn: Connection, appt: dict, new: str, user: User, room: str | None = None) -> None:
    now_sql = {"arrived": "arrived_at", "roomed": "roomed_at", "in_progress": "started_at",
               "completed": "completed_at", "no_show": "no_show_at"}[new]
    conn.execute(
        f"""
        INSERT INTO appointment_encounters (appointment_id, patient_id, practitioner_id, status, room, {now_sql}, updated_by)
        VALUES (%(a)s, %(p)s, %(pr)s, %(st)s, %(room)s, now(), %(u)s)
        ON CONFLICT (appointment_id) DO UPDATE
        SET status = EXCLUDED.status, room = coalesce(EXCLUDED.room, appointment_encounters.room),
            {now_sql} = now(), updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        {"a": appt["id"], "p": appt["patient_id"], "pr": appt["practitioner_id"], "st": new, "room": room, "u": user.id},
    )


@router.post("/{appointment_id}/check-in")
def check_in(appointment_id: str, conn: Conn, user: Patient) -> dict:
    """The patient taps "I'm here". Allowed on the day, from 60 minutes before the start."""
    appt = _own_appointment(conn, user, appointment_id, lock=True)
    if appt["appointment_status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "not_active", "message": "This appointment is not active."})
    now, today = _now(conn), clinic_today(conn)
    window = check_in_window(appt, now, today)
    if not window["allowed"]:
        messages = {
            "already_checked_in": "You're already checked in.",
            "too_early": f"Check-in opens {CHECK_IN_OPENS_MIN} minutes before your appointment.",
            "missed": "This appointment has passed. Please book a new time.",
        }
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": window["code"], "message": messages[window["code"]],
                                                       "opens_at": window["opens_at"].isoformat()})
    _set_status(conn, appt, "arrived", user)
    audit.record(conn, action="visit_arrived", entity_type="appointment", entity_id=appt["id"], actor=user,
                 patient_id=appt["patient_id"], detail={"by": "patient"})
    fresh = _load_appt(conn, appointment_id)
    return _visit_view(conn, fresh, now, today, _suggested_questions(conn, appt["patient_id"]))


# --- Clinic queue ----------------------------------------------------------------------------------


def _age(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _queue_rows(conn: Connection, practitioner_id: str, day: date, now: datetime, today: date,
                appointment_id: str | None = None) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.id::text, a.reason, a.status AS appointment_status, s.starts_at, s.duration_min, s.mode,
               p.id::text AS patient_id, p.name AS patient_name, p.birth_date, p.pronouns, p.preferred_language,
               coalesce(e.status, 'booked') AS status, e.room, e.arrived_at, e.roomed_at, e.started_at,
               e.completed_at, e.no_show_at,
               avs.id IS NOT NULL AS has_summary, avs.instructions, avs.follow_up, avs.prescriptions,
               (SELECT coalesce(json_agg(q.text ORDER BY q.created_at), '[]'::json)
                  FROM appointment_questions q WHERE q.appointment_id = a.id) AS questions
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN patients p ON p.id = a.patient_id
        LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
        LEFT JOIN after_visit_summaries avs ON avs.appointment_id = a.id
        WHERE a.practitioner_id = %(pr)s AND a.status IN ('booked', 'fulfilled')
          AND (s.starts_at AT TIME ZONE %(tz)s)::date = %(day)s
          AND (%(appt)s::uuid IS NULL OR a.id = %(appt)s::uuid)
        ORDER BY s.starts_at
        """,
        {"pr": practitioner_id, "tz": clinic_tz(), "day": day, "appt": appointment_id},
    ).fetchall()
    active = [
        {"appointment_id": r["id"], "status": r["status"], "arrived_at": r["arrived_at"], "started_at": r["started_at"],
         "starts_at": r["starts_at"], "duration_min": r["duration_min"]}
        for r in rows if r["status"] in ACTIVE
    ]
    if appointment_id:
        active = _active_rows(conn, practitioner_id, day)
    out = []
    for r in rows:
        r["age"] = _age(r.pop("birth_date"), today)
        r["label"] = STATUS_LABEL[r["status"]]
        r["actions"] = sorted(_allowed(r["status"], r["mode"]))
        r["wait"] = None
        if r["status"] == "arrived":
            me = next(a for a in active if a["appointment_id"] == r["id"])
            r["wait"] = estimate_wait(active, me, now)
        out.append(r)
    return out


def _allowed(current: str, mode: str) -> set[str]:
    allowed = set(TRANSITIONS[current])
    if current == "arrived" and mode != "video":
        allowed.discard("in_progress")
    return allowed


@router.get("/queue")
def queue(conn: Conn, user: Workforce, practitioner_id: str | None = None, day: date | None = None) -> dict:
    """Today's appointments for one clinician (the signed-in clinician by default) with live status."""
    today, now = clinic_today(conn), _now(conn)
    day = day or today
    practitioners = conn.execute(
        """
        SELECT pr.id::text, pr.name, pr.specialty,
               (SELECT count(*) FROM appointments a JOIN slots s ON s.id = a.slot_id
                 WHERE a.practitioner_id = pr.id AND a.status IN ('booked', 'fulfilled')
                   AND (s.starts_at AT TIME ZONE %s)::date = %s) AS appointments
        FROM practitioners pr WHERE pr.organization_id = %s
        ORDER BY pr.name
        """,
        (clinic_tz(), day, user.organization_id),
    ).fetchall()
    pid = practitioner_id or user.practitioner_id
    if pid is None:
        return {"day": day, "today": today, "practitioner": None, "practitioners": practitioners, "appointments": [],
                "counts": {}}
    current = next((p for p in practitioners if p["id"] == pid), None)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinician not found")
    rows = _queue_rows(conn, pid, day, now, today)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_LABEL}
    return {"day": day, "today": today, "practitioner": current, "practitioners": practitioners,
            "appointments": rows, "counts": counts, "refreshed_at": now}


class StatusIn(BaseModel):
    status: Literal["arrived", "roomed", "in_progress", "completed", "no_show"]
    room: str | None = Field(default=None, max_length=40)


@router.post("/queue/{appointment_id}/status")
def set_status(appointment_id: str, body: StatusIn, conn: Conn, user: Workforce) -> dict:
    appt = _load_appt(conn, appointment_id, lock=True)
    if appt["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    assert_patient_access(conn, user, appt["patient_id"])
    if appt["appointment_status"] == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "This appointment was cancelled")

    current = appt["visit_status"] or "booked"
    if body.status not in _allowed(current, appt["mode"]):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "invalid_transition",
             "message": f"Can't go from {STATUS_LABEL[current].lower()} to {STATUS_LABEL[body.status].lower()}."},
        )
    now, today = _now(conn), clinic_today(conn)
    if body.status == "arrived" and appt["clinic_date"] != today:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "not_today", "message": "Only today's patients can be checked in."})
    if body.status == "no_show" and now < appt["starts_at"]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "too_early", "message": "A visit can be marked as a no-show only after its start time."})
    room = (body.room or "").strip() or None
    if body.status == "roomed" and not room:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a room")

    _set_status(conn, appt, body.status, user, room if body.status == "roomed" else None)

    if body.status == "completed":
        # The visit happened: the appointment is fulfilled and becomes a past visit in the record.
        conn.execute("UPDATE appointments SET status = 'fulfilled' WHERE id = %s", (appt["id"],))
        enc = conn.execute(
            """
            INSERT INTO encounters (patient_id, practitioner_id, occurred_at, kind, summary)
            VALUES (%s, %s, coalesce(%s, now()), %s, %s) RETURNING id::text
            """,
            (appt["patient_id"], appt["practitioner_id"], appt["started_at"], f"{appt['specialty']} visit",
             appt["reason"] or "Visit completed."),
        ).fetchone()
        conn.execute("UPDATE appointment_encounters SET encounter_id = %s WHERE appointment_id = %s", (enc["id"], appt["id"]))
        from bioverse.routers import referrals

        referrals.refresh(conn, patient_id=appt["patient_id"])

    audit.record(conn, action=f"visit_{body.status}", entity_type="appointment", entity_id=appt["id"], actor=user,
                 patient_id=appt["patient_id"], detail={"from": current, "room": room})
    return _queue_rows(conn, appt["practitioner_id"], appt["clinic_date"], now, today, appointment_id=appt["id"])[0]


class SummaryIn(BaseModel):
    instructions: str = Field(min_length=3, max_length=4000)
    follow_up: str | None = Field(default=None, max_length=2000)
    prescriptions: str | None = Field(default=None, max_length=2000)


@router.put("/queue/{appointment_id}/summary")
def write_summary(appointment_id: str, body: SummaryIn, conn: Conn, user: Clinician) -> dict:
    """The treating clinician writes the after-visit summary. They are the author, so it publishes directly."""
    appt = _load_appt(conn, appointment_id, lock=True)
    if appt["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    assert_patient_access(conn, user, appt["patient_id"])
    if appt["practitioner_id"] != user.practitioner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the clinician who saw the patient can write this summary")
    if appt["visit_status"] != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Complete the visit before writing its summary")
    instructions = body.instructions.strip()
    if len(instructions) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Write the instructions for the patient")
    follow_up = (body.follow_up or "").strip() or None
    prescriptions = (body.prescriptions or "").strip() or None

    row = conn.execute(
        """
        INSERT INTO after_visit_summaries (patient_id, practitioner_id, appointment_id, encounter_id,
                                           instructions, follow_up, prescriptions, author_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (appointment_id) DO UPDATE
        SET instructions = EXCLUDED.instructions, follow_up = EXCLUDED.follow_up,
            prescriptions = EXCLUDED.prescriptions, author_user_id = EXCLUDED.author_user_id, updated_at = now()
        RETURNING id::text, instructions, follow_up, prescriptions, published_at, updated_at,
                  (xmax <> 0) AS edited
        """,
        (appt["patient_id"], appt["practitioner_id"], appt["id"], appt["encounter_id"],
         instructions, follow_up, prescriptions, user.id),
    ).fetchone()
    audit.record(conn, action="after_visit_summary_" + ("updated" if row["edited"] else "published"),
                 entity_type="after_visit_summary", entity_id=row["id"], actor=user, patient_id=appt["patient_id"],
                 detail={"appointment_id": appt["id"]})
    row.pop("edited")
    return row
