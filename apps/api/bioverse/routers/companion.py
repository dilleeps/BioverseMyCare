"""Health companion: today's doses, check-ins, adherence and settings for patients; "between visits" for clinicians.

Access: patients reach only their own companion. Clinicians reach patients in their organization, read-only,
and resolve the check-in escalations routed to them. Every write and every clinician read is audited.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bioverse import audit, companion
from bioverse.auth import Clinician, CurrentUser, Patient, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.notify import cancel
from bioverse.safety import red_flags

router = APIRouter(prefix="/api/companion", tags=["companion"])

Conn = DbConn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: str, what: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found") from None


def _scope(conn: Connection, user: User, patient_id: str | None) -> str:
    """Patients: themselves. Clinicians: a patient in their organization (patient_id required)."""
    if user.role == "patient" and user.patient_id:
        if patient_id and patient_id != user.patient_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record")
        return user.patient_id
    if user.role == "clinician" and user.practitioner_id:
        if not patient_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
        pid = _uuid(patient_id, "Patient")
        assert_patient_access(conn, user, pid)
        return pid
    raise HTTPException(status.HTTP_403_FORBIDDEN, "The companion is available to patients and their clinicians")


# --- Today -----------------------------------------------------------------------------------------


def _appointments(conn: Connection, patient_id: str, now: datetime, days: int = 14) -> list[dict]:
    return conn.execute(
        """
        SELECT a.id::text, s.starts_at, s.mode, a.reason, pr.name AS practitioner_name, pr.specialty,
               pr.location_name
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN practitioners pr ON pr.id = a.practitioner_id
        LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
        WHERE a.patient_id = %s AND a.status = 'booked' AND coalesce(e.status, 'booked') NOT IN ('completed', 'no_show')
          AND s.starts_at > %s AND s.starts_at < %s
        ORDER BY s.starts_at LIMIT 5
        """,
        (patient_id, now - timedelta(hours=1), now + timedelta(days=days)),
    ).fetchall()


def _checkin_out(c: dict) -> dict:
    return {k: c[k] for k in ("id", "kind", "subject", "prompt", "status", "response", "note", "escalation",
                              "due_at", "answered_at") if k in c}


@router.get("/today")
def today(conn: Conn, user: Patient) -> dict:
    pid, now = user.patient_id, _now()
    tz = companion.patient_tz(conn, pid)
    settings = companion.load_settings(conn, pid)
    meds = companion.load_meds(conn, pid)
    day = now.astimezone(tz).date()
    records = companion.dose_records(conn, pid, datetime.combine(day - timedelta(days=1), time(0)))
    logs = companion.pharmacy_logs(conn, pid, day - timedelta(days=1))

    doses, earlier, waiting = [], [], []
    for med in meds:
        if med.start is None:
            waiting.append({"rx_id": med.id, "medication": med.label, "schedule": med.freq.text})
            continue
        for d in companion.doses_on(med, settings, tz, day):
            doses.append(companion.dose_state(d, med, records, logs, now, day))
        for d in companion.doses_on(med, settings, tz, day - timedelta(days=1)):
            s = companion.dose_state(d, med, records, logs, now, day)
            if s["status"] == "missed":
                earlier.append(s)
    doses.sort(key=lambda s: (s["local"], s["medication"]))
    unscheduled = [{"rx_id": m.id, "medication": m.label, "schedule": m.freq.text}
                   for m in meds if m.start is not None and not companion.dose_times(m.freq, settings, m.id)]

    open_checkins = conn.execute(
        """
        SELECT id::text, kind, subject, prompt, status, due_at FROM companion_checkins
        WHERE patient_id = %s AND status = 'open' AND due_at <= %s ORDER BY due_at
        """,
        (pid, now),
    ).fetchall()
    return {
        "date": day,
        "timezone": tz.key,
        "first_name": companion.first_name(user.display_name),
        "doses": doses,
        "earlier": earlier,
        "waiting_for_pickup": waiting,
        "unscheduled": unscheduled,
        "checkins": open_checkins,
        "appointments": _appointments(conn, pid, now),
        "tip": companion.tip_for(day),
        "skip_reasons": [{"id": k, "label": v} for k, v in companion.SKIP_REASONS.items()],
    }


@router.get("/adherence")
def adherence(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _scope(conn, user, patient_id)
    out = companion.adherence(conn, pid, _now())
    if user.role != "patient":
        audit.record(conn, action="companion_adherence_viewed", entity_type="patient", entity_id=pid, actor=user,
                     patient_id=pid)
    return out


# --- Doses -----------------------------------------------------------------------------------------


class DoseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    medication_request_id: str
    local_time: str = Field(description="The dose time on the patient's clock, YYYY-MM-DDTHH:MM")
    status: Literal["taken", "skipped"]
    reason: Literal["forgot", "side_effects", "ran_out", "felt_unwell", "away_from_home", "other"] | None = None


@router.post("/doses", status_code=status.HTTP_201_CREATED)
def record_dose(body: DoseIn, conn: Conn, user: Patient) -> dict:
    rx_id = _uuid(body.medication_request_id, "Prescription")
    med = companion.load_med(conn, rx_id)
    if med is None or med.patient_id != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prescription not found")
    if med.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This prescription isn't active any more")
    try:
        local = datetime.strptime(body.local_time, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use a time like 2026-09-24T20:00") from None
    if body.status == "taken" and body.reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A reason goes with a skipped dose only")

    now = _now()
    tz = companion.patient_tz(conn, user.patient_id)
    settings = companion.load_settings(conn, user.patient_id)
    today = now.astimezone(tz).date()
    if local.date() > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't mark a dose for a future day")
    if local.date() < today - timedelta(days=companion.MARK_WINDOW_DAYS - 1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can mark doses from the last 7 days only")
    dose = companion.find_dose(med, settings, tz, local)
    if dose is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no scheduled dose of this medicine at that time")

    row = conn.execute(
        """
        INSERT INTO medication_doses (patient_id, medication_request_id, scheduled_at, scheduled_local, status, reason,
                                      recorded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (medication_request_id, scheduled_local) DO UPDATE
          SET status = EXCLUDED.status, reason = EXCLUDED.reason, recorded_by = EXCLUDED.recorded_by,
              recorded_at = clock_timestamp()
        RETURNING id::text, status, reason, scheduled_at, scheduled_local, recorded_at
        """,
        (user.patient_id, rx_id, dose.at, dose.local, body.status, body.reason, user.id),
    ).fetchone()
    companion.mirror_to_pharmacy_log(conn, med, dose, body.status)
    # The reminder has done its job: cancel it if it hasn't fired, mark it read if it has.
    cancel(conn, user_id=user.id, dedupe_prefix=dose.key)
    conn.execute("UPDATE notifications SET read_at = coalesce(read_at, now()) WHERE user_id = %s AND dedupe_key = %s",
                 (user.id, dose.key))
    audit.record(conn, action=f"medication_dose_{body.status}", entity_type="medication_request", entity_id=rx_id,
                 actor=user, patient_id=user.patient_id,
                 detail={"dose": dose.local.isoformat(timespec="minutes"), "reason": body.reason})
    note = None
    if body.reason == "side_effects":
        note = ("If side effects are bothering you, tell your care team in Messages. Please don't stop a medicine "
                "without talking to them first.")
    return {**row, "local": dose.local.strftime("%Y-%m-%dT%H:%M"), "medication": med.label, "note": note}


@router.delete("/doses/{dose_id}")
def undo_dose(dose_id: str, conn: Conn, user: Patient) -> dict:
    dose_id = _uuid(dose_id, "Dose")
    row = conn.execute(
        """
        DELETE FROM medication_doses WHERE id = %s AND patient_id = %s
        RETURNING medication_request_id::text AS rx_id, scheduled_local, status
        """,
        (dose_id, user.patient_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dose not found")
    med = companion.load_med(conn, row["rx_id"])
    if med and row["status"] == "taken":
        companion.mirror_to_pharmacy_log(conn, med, companion.Dose(med.id, row["scheduled_local"], _now()), "undone")
    audit.record(conn, action="medication_dose_undone", entity_type="medication_request", entity_id=row["rx_id"],
                 actor=user, patient_id=user.patient_id,
                 detail={"dose": row["scheduled_local"].isoformat(timespec="minutes")})
    return {"id": dose_id, "undone": True}


# --- Check-ins -------------------------------------------------------------------------------------


@router.get("/checkins")
def checkins(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _scope(conn, user, patient_id)
    rows = conn.execute(
        """
        SELECT id::text, kind, subject, prompt, status, response, note, screen_level, escalation, due_at, answered_at
        FROM companion_checkins WHERE patient_id = %s AND due_at <= %s ORDER BY due_at DESC LIMIT 50
        """,
        (pid, _now()),
    ).fetchall()
    if user.role != "patient":
        audit.record(conn, action="companion_checkins_viewed", entity_type="patient", entity_id=pid, actor=user,
                     patient_id=pid)
    return {"open": [r for r in rows if r["status"] == "open"], "history": [r for r in rows if r["status"] != "open"]}


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: Literal["better", "same", "worse"]
    note: str | None = Field(default=None, max_length=1000)


REPLIES = {
    "better": "That's good to hear. Thanks for letting us know.",
    "same": "Thanks for letting us know. If anything changes, you can tell us here or message your care team.",
}


def _review_item(conn: Connection, *, c: dict, practitioner_id: str, kind: str, priority: str, title: str,
                 body: str) -> str:
    return conn.execute(
        """
        INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (kind, c["patient_id"], practitioner_id, c["id"], title, body, priority,
         f"/clinician/companion?patient={c['patient_id']}"),
    ).fetchone()["id"]


@router.post("/checkins/{checkin_id}/answer")
def answer(checkin_id: str, body: AnswerIn, conn: Conn, user: Patient) -> dict:
    checkin_id = _uuid(checkin_id, "Check-in")
    c = conn.execute(
        """
        SELECT c.id::text, c.patient_id::text, c.kind, c.ref_id::text, c.subject, c.status, c.practitioner_id::text,
               m.drug_code
        FROM companion_checkins c
        LEFT JOIN medication_requests m ON c.kind = 'new_medication' AND m.id = c.ref_id
        WHERE c.id = %s FOR UPDATE OF c
        """,
        (checkin_id,),
    ).fetchone()
    if c is None or c["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check-in not found")
    if c["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "This check-in has already been answered or has closed")

    note = (body.note or "").strip() or None
    # Free text from a patient: screen it before anything else.
    screen = red_flags.screen(note) if note else red_flags.ScreenResult(level="none")
    practitioner = companion.care_team_member(conn, c["patient_id"], c["practitioner_id"])
    escalation, reason, item_id = None, None, None
    quoted = f' They wrote: "{note}"' if note else ""

    if screen.level in ("emergency", "crisis"):
        escalation, reason = "urgent", f"Red flag: {', '.join(screen.flags)}"
        if practitioner:
            item_id = _review_item(
                conn, c=c, practitioner_id=practitioner, kind="red_flag", priority="urgent",
                title=f"Red flag · {', '.join(screen.flags)}",
                body=f"Written in a companion check-in about {c['subject']}. The patient was shown emergency "
                     f"guidance.{quoted}",
            )
            companion.notify_clinician(conn, practitioner, c["patient_id"], True, c["id"])
        audit.record(conn, action="red_flag_escalation", entity_type="companion_checkin", entity_id=c["id"],
                     actor=user, agent="safety/red-flags", patient_id=c["patient_id"],
                     detail={"flags": screen.flags, "level": screen.level, "ruleset": screen.ruleset,
                             "source": "companion_checkin", "review_item_id": item_id})
    else:
        side_effects = companion.mentions_side_effect(conn, note or "", c["drug_code"]) \
            if c["kind"] == "new_medication" else []
        reasons = []
        if body.response == "worse":
            reasons.append("feeling worse")
        if side_effects:
            reasons.append("possible side effect: " + ", ".join(side_effects))
        if screen.level == "screen":
            reasons.append(f"mentions {screen.topic} symptoms")
        if reasons:
            escalation, reason = "routine", "; ".join(reasons)
            if practitioner:
                item_id = _review_item(
                    conn, c=c, practitioner_id=practitioner, kind="companion_checkin", priority="routine",
                    title=f"Check-in · {reasons[0]}",
                    body=f"Answered \"{companion.RESPONSE_WORD[body.response]}\" to a check-in about {c['subject']}."
                         f"{quoted}",
                )
                companion.notify_clinician(conn, practitioner, c["patient_id"], False, c["id"])

    conn.execute(
        """
        UPDATE companion_checkins
        SET status = 'answered', response = %s, note = %s, screen_level = %s, screen_flags = %s, escalation = %s,
            escalation_reason = %s, review_item_id = %s, answered_at = now()
        WHERE id = %s
        """,
        (body.response, note, screen.level, screen.flags, escalation, reason, item_id, c["id"]),
    )
    conn.execute("UPDATE notifications SET read_at = coalesce(read_at, now()) WHERE user_id = %s AND dedupe_key = %s",
                 (user.id, f"checkin:{c['id']}"))
    audit.record(conn, action="companion_checkin_answered", entity_type="companion_checkin", entity_id=c["id"],
                 actor=user, patient_id=c["patient_id"],
                 detail={"response": body.response, "escalation": escalation, "screen": screen.level})

    if escalation == "urgent":
        return {
            "status": "answered", "escalation": "urgent",
            "emergency": {
                "message": red_flags.emergency_message(screen),
                "emergency_number": red_flags.EMERGENCY_NUMBER,
                "crisis_line": red_flags.CRISIS_LINE if screen.level == "crisis" else None,
                "flags": screen.flags,
                "care_team_notified": item_id is not None,
            },
        }
    if escalation == "routine":
        message = ("Thank you for telling us. We've passed this to your care team and someone will follow up. "
                   f"If you feel much worse or have warning signs, call {red_flags.EMERGENCY_NUMBER}.")
        if screen.level == "screen":
            message += " For a quick safety check on these symptoms, use Ask Bioverse."
        return {"status": "answered", "escalation": "routine", "message": message}
    return {"status": "answered", "escalation": None, "message": REPLIES[body.response]}


# --- Settings --------------------------------------------------------------------------------------


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    medication_reminders: bool = True
    appointment_reminders: bool = True
    checkins: bool = True
    results_ready: bool = True
    care_gap_nudges: bool = True
    daily_brief: bool = False
    daily_brief_time: str = "07:30"
    dose_times: dict[str, str] = {}
    medication_times: dict[str, list[str]] = {}

    @field_validator("daily_brief_time")
    @classmethod
    def brief_time(cls, v: str) -> str:
        return companion.fmt_hhmm(companion.parse_hhmm(v))

    @field_validator("dose_times")
    @classmethod
    def slots(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if k not in companion.SLOTS]
        if bad:
            raise ValueError(f"Unknown part of the day: {', '.join(bad)}")
        return {k: companion.fmt_hhmm(companion.parse_hhmm(t)) for k, t in v.items()}

    @field_validator("medication_times")
    @classmethod
    def med_times(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        out = {}
        for rx, times in v.items():
            if len(times) > 6:
                raise ValueError("At most six times a day")
            if times:
                out[rx] = sorted({companion.fmt_hhmm(companion.parse_hhmm(t)) for t in times})
        return out


def _settings_out(conn: Connection, patient_id: str) -> dict:
    s = companion.load_settings(conn, patient_id)
    meds = companion.load_meds(conn, patient_id)
    return {
        **{k: s[k] for k in companion.TOGGLES},
        "daily_brief_time": companion.fmt_hhmm(s["daily_brief_time"]),
        "dose_times": {slot: s["dose_times"].get(slot, companion.fmt_hhmm(t)) for slot, t in companion.SLOTS.items()},
        "medication_times": s["medication_times"],
        "medications": [
            {"rx_id": m.id, "medication": m.label, "schedule": m.freq.text, "sig": m.sig,
             "times": [companion.fmt_hhmm(t) for t in companion.dose_times(m.freq, s, m.id)],
             "custom": m.id in s["medication_times"], "started": m.start is not None}
            for m in meds
        ],
        "timezone": companion.patient_tz(conn, patient_id).key,
        "updated_at": s["updated_at"],
    }


@router.get("/settings")
def get_settings(conn: Conn, user: Patient) -> dict:
    return _settings_out(conn, user.patient_id)


@router.put("/settings")
def put_settings(body: SettingsIn, conn: Conn, user: Patient) -> dict:
    pid = user.patient_id
    mine = {m.id for m in companion.load_meds(conn, pid)}
    unknown = [rx for rx in body.medication_times if rx not in mine]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Times can only be set for your active medicines")
    conn.execute(
        f"""
        INSERT INTO companion_settings (patient_id, {', '.join(companion.TOGGLES)}, daily_brief_time, dose_times,
                                        medication_times, updated_by)
        VALUES (%s, {', '.join(['%s'] * len(companion.TOGGLES))}, %s, %s, %s, %s)
        ON CONFLICT (patient_id) DO UPDATE SET
            {', '.join(f'{k} = EXCLUDED.{k}' for k in companion.TOGGLES)},
            daily_brief_time = EXCLUDED.daily_brief_time, dose_times = EXCLUDED.dose_times,
            medication_times = EXCLUDED.medication_times, updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        (pid, *[getattr(body, k) for k in companion.TOGGLES], body.daily_brief_time, Jsonb(body.dose_times),
         Jsonb(body.medication_times), user.id),
    )
    cancelled = _cancel_outdated(conn, user, body)
    audit.record(conn, action="companion_settings_updated", entity_type="patient", entity_id=pid, actor=user,
                 patient_id=pid, detail={**{k: getattr(body, k) for k in companion.TOGGLES},
                                         "cancelled_reminders": cancelled})
    return _settings_out(conn, pid)


def _cancel_outdated(conn: Connection, user: User, body: SettingsIn) -> int:
    """Pending reminders that no longer match: everything when a kind is turned off; for medicines, any
    reminder whose time is no longer one of that medicine's dose times (the job creates the new ones)."""
    n = 0
    if not body.appointment_reminders:
        n += cancel(conn, user_id=user.id, dedupe_prefix="appt:")
    if not body.medication_reminders:
        return n + cancel(conn, user_id=user.id, dedupe_prefix="med:")
    settings = companion.load_settings(conn, user.patient_id)
    meds = {m.id: m for m in companion.load_meds(conn, user.patient_id)}
    pending = conn.execute(
        "SELECT dedupe_key FROM notifications WHERE user_id = %s AND status = 'pending' AND dedupe_key LIKE 'med:%%'",
        (user.id,),
    ).fetchall()
    for p in pending:
        _, rx_id, stamp = p["dedupe_key"].split(":", 2)
        med = meds.get(rx_id)
        if med is None:
            continue
        wanted = {companion.fmt_hhmm(t) for t in companion.dose_times(med.freq, settings, rx_id)}
        if stamp[11:16] not in wanted:
            n += cancel(conn, user_id=user.id, dedupe_prefix=p["dedupe_key"])
    return n


# --- Clinician: between visits ---------------------------------------------------------------------


def between_visits(conn: Connection, patient_id: str, now: datetime) -> dict:
    tz = companion.patient_tz(conn, patient_id)
    adh = companion.adherence(conn, patient_id, now, tz=tz)
    recent = companion.recent_checkins(conn, patient_id, now - timedelta(days=30))
    answered = [c for c in recent if c["status"] == "answered"]
    return {
        "adherence": adh,
        "checkins": [
            {**_checkin_out(c), "sentence": companion.checkin_sentence(c, tz) if c["status"] == "answered" else None,
             "review_status": c["review_status"]}
            for c in recent
        ],
        "escalations": [
            {"checkin_id": c["id"], "review_item_id": c["review_item_id"], "priority": c["escalation"],
             "reason": c["escalation_reason"], "subject": c["subject"], "note": c["note"], "at": c["answered_at"],
             "status": c["review_status"] or "not routed"}
            for c in answered if c["escalation"]
        ],
        "counts": {
            "answered": len(answered),
            "open": sum(1 for c in recent if c["status"] == "open"),
            "worse": sum(1 for c in answered if c["response"] == "worse"),
        },
    }


@router.get("/patients/{patient_id}/between-visits")
def patient_between_visits(patient_id: str, conn: Conn, user: Clinician) -> dict:
    pid = _scope(conn, user, patient_id)
    out = between_visits(conn, pid, _now())
    audit.record(conn, action="companion_summary_viewed", entity_type="patient", entity_id=pid, actor=user,
                 patient_id=pid)
    return out


@router.get("/clinician/escalations")
def escalations(conn: Conn, user: Clinician, state: Literal["open", "all"] = "open") -> dict:
    rows = conn.execute(
        """
        SELECT r.id::text AS review_item_id, r.kind, r.priority, r.status, r.title, r.body, r.created_at,
               r.resolution, r.resolved_at, c.id::text AS checkin_id, c.kind AS checkin_kind, c.subject, c.response,
               c.note, c.escalation_reason, c.answered_at, p.id::text AS patient_id, p.name AS patient_name
        FROM companion_checkins c
        JOIN review_items r ON r.id = c.review_item_id
        JOIN patients p ON p.id = c.patient_id
        WHERE r.practitioner_id = %s AND p.organization_id = %s AND (%s = 'all' OR r.status = 'open')
        ORDER BY (r.status = 'open') DESC, (r.priority = 'urgent') DESC, r.created_at DESC
        LIMIT 100
        """,
        (user.practitioner_id, user.organization_id, state),
    ).fetchall()
    audit.record(conn, action="companion_escalations_viewed", entity_type="review_item", actor=user,
                 detail={"count": len(rows), "state": state})
    return {"items": rows}


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


@router.post("/clinician/escalations/{review_item_id}/resolve")
def resolve(review_item_id: str, body: ResolveIn, conn: Conn, user: Clinician) -> dict:
    review_item_id = _uuid(review_item_id, "Review item")
    item = conn.execute(
        """
        SELECT r.id::text, r.status, r.patient_id::text, c.id::text AS checkin_id
        FROM review_items r JOIN companion_checkins c ON c.review_item_id = r.id
        WHERE r.id = %s AND r.practitioner_id = %s FOR UPDATE OF r
        """,
        (review_item_id, user.practitioner_id),
    ).fetchone()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    assert_patient_access(conn, user, item["patient_id"])
    if item["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already resolved")
    note = (body.note or "").strip()
    resolution = "reviewed" + (f": {note}" if note else "")
    conn.execute(
        "UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now() WHERE id = %s",
        (resolution, user.id, review_item_id),
    )
    audit.record(conn, action="companion_escalation_resolved", entity_type="review_item", entity_id=review_item_id,
                 actor=user, patient_id=item["patient_id"], detail={"checkin_id": item["checkin_id"]})
    return {"id": review_item_id, "status": "resolved", "resolution": resolution}
