"""Wellness and prevention: preventive checklist, patient-reported goals, lifestyle assessment."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from bioverse import audit, prevention
from bioverse.agents.health_ai import notify_care_team
from bioverse.auth import CurrentUser, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.safety import red_flags

router = APIRouter(prefix="/api/wellness", tags=["wellness"])

Conn = DbConn


def _own_record(user: User, patient_id: str) -> None:
    """Goals and assessments are patient-reported: only the patient writes them."""
    if user.role != "patient" or user.patient_id != patient_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can record their own wellness data")


# --- Preventive care -------------------------------------------------------------------------------


@router.get("/patients/{patient_id}/prevention")
def prevention_checklist(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    assert_patient_access(conn, user, patient_id)
    result = prevention.evaluate(prevention.load_record(conn, patient_id))
    audit.record(conn, action="prevention_evaluated", entity_type="patient", entity_id=patient_id, actor=user,
                 agent="prevention-rules", patient_id=patient_id, detail={"ruleset": prevention.RULESET_VERSION})
    return result


@router.post("/patients/{patient_id}/prevention/sync")
def sync_prevention(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    """Write due/overdue items to care gaps (and close ones now up to date). Safe to call repeatedly."""
    assert_patient_access(conn, user, patient_id)
    result = prevention.evaluate(prevention.load_record(conn, patient_id))
    changes = prevention.sync_gaps(conn, patient_id, result["items"], user)
    return {"ruleset": prevention.RULESET_VERSION, **changes}


# --- Goals -----------------------------------------------------------------------------------------

GOAL_KINDS: dict[str, dict[str, Any]] = {
    "steps": {"title": "Daily steps", "unit": "steps", "target": 7000, "max": 100000},
    "sleep_hours": {"title": "Sleep", "unit": "hours", "target": 7.5, "max": 24},
    "active_minutes": {"title": "Active minutes", "unit": "minutes", "target": 30, "max": 1440},
    "fruit_veg_servings": {"title": "Fruit and vegetables", "unit": "servings", "target": 5, "max": 50},
    "custom": {"title": None, "unit": None, "target": None, "max": 1_000_000},
}
STREAK_MILESTONES = (7, 30, 100)


def progress(target: float, entries: dict[date, float], today: date) -> dict[str, Any]:
    """7- and 30-day progress, current and best streak. A day counts as met when value >= target.

    The current streak runs back from today; if today has nothing logged yet (or isn't met yet) it runs
    back from yesterday, so an unfinished day never breaks a streak.
    """

    def window(n: int) -> dict[str, Any]:
        days = [today - timedelta(days=d) for d in range(n)]
        logged = [entries[d] for d in days if d in entries]
        met = sum(1 for v in logged if v >= target)
        return {
            "days": n,
            "logged": len(logged),
            "met": met,
            "average": round(sum(logged) / len(logged), 1) if logged else None,
            "percent_met": round(100 * met / n),
        }

    def met(d: date) -> bool:
        return d in entries and entries[d] >= target

    streak, d = 0, today if met(today) else today - timedelta(days=1)
    while met(d):
        streak += 1
        d -= timedelta(days=1)

    best = run = 0
    prev: date | None = None
    for day in sorted(entries):
        if entries[day] >= target:
            run = run + 1 if prev is not None and day - prev == timedelta(days=1) and met(prev) else 1
            best = max(best, run)
        else:
            run = 0
        prev = day

    last7 = [{"day": today - timedelta(days=i), "value": entries.get(today - timedelta(days=i)),
              "met": met(today - timedelta(days=i))} for i in range(6, -1, -1)]
    return {"last_7": window(7), "last_30": window(30), "current_streak": streak, "best_streak": best, "series": last7}


def milestones(target: float, entries: dict[date, float]) -> list[dict[str, Any]]:
    """Each time a run of met days reaches a milestone length: {day, streak}."""
    out, run, prev = [], 0, None
    for day in sorted(entries):
        if entries[day] >= target:
            run = run + 1 if prev is not None and day - prev == timedelta(days=1) and entries[prev] >= target else 1
            if run in STREAK_MILESTONES:
                out.append({"day": day, "streak": run})
        else:
            run = 0
        prev = day
    return out


def _entries(conn: Connection, goal_id: str) -> dict[date, float]:
    rows = conn.execute("SELECT day, value FROM wellness_goal_entries WHERE goal_id = %s", (goal_id,)).fetchall()
    return {r["day"]: float(r["value"]) for r in rows}


def _goal_out(conn: Connection, goal: dict[str, Any], today: date) -> dict[str, Any]:
    target = float(goal["target"])
    entries = _entries(conn, goal["id"])
    return {
        **goal,
        "target": target,
        "reported_by": "patient",
        "progress": progress(target, entries, today),
        "logged_today": entries.get(today),
    }


def _goal_row(conn: Connection, goal_id: str) -> dict[str, Any]:
    goal = conn.execute(
        """
        SELECT id::text, patient_id::text, kind, title, unit, target, status, source, created_at
        FROM wellness_goals WHERE id = %s
        """,
        (goal_id,),
    ).fetchone()
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    return goal


@router.get("/patients/{patient_id}/goals")
def list_goals(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    assert_patient_access(conn, user, patient_id)
    today = date.today()
    goals = conn.execute(
        """
        SELECT id::text, patient_id::text, kind, title, unit, target, status, source, created_at
        FROM wellness_goals WHERE patient_id = %s AND status = 'active' ORDER BY created_at
        """,
        (patient_id,),
    ).fetchall()
    return {
        "today": today,
        "kinds": {k: {kk: v[kk] for kk in ("title", "unit", "target")} for k, v in GOAL_KINDS.items()},
        "goals": [_goal_out(conn, g, today) for g in goals],
    }


class GoalIn(BaseModel):
    kind: Literal["steps", "sleep_hours", "active_minutes", "fruit_veg_servings", "custom"]
    target: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=2, max_length=80)
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    assessment_id: str | None = None

    @model_validator(mode="after")
    def custom_needs_details(self) -> "GoalIn":
        if self.kind == "custom" and not (self.title and self.unit and self.target):
            raise ValueError("A custom goal needs a title, a unit and a target")
        if self.target is not None and self.target > GOAL_KINDS[self.kind]["max"]:
            raise ValueError("That target is higher than this goal allows")
        return self


@router.post("/patients/{patient_id}/goals", status_code=status.HTTP_201_CREATED)
def create_goal(patient_id: str, body: GoalIn, conn: Conn, user: CurrentUser) -> dict:
    _own_record(user, patient_id)
    defaults = GOAL_KINDS[body.kind]
    source = "patient"
    if body.assessment_id:
        owned = conn.execute("SELECT 1 FROM wellness_assessments WHERE id = %s AND patient_id = %s",
                             (body.assessment_id, patient_id)).fetchone()
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
        source = "assessment"
    goal = conn.execute(
        """
        INSERT INTO wellness_goals (patient_id, kind, title, unit, target, source, assessment_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (patient_id, body.kind, body.title or defaults["title"], body.unit or defaults["unit"],
         body.target or defaults["target"], source, body.assessment_id),
    ).fetchone()
    audit.record(conn, action="goal_created", entity_type="goal", entity_id=goal["id"], actor=user,
                 patient_id=patient_id, detail={"kind": body.kind, "source": source})
    return _goal_out(conn, _goal_row(conn, goal["id"]), date.today())


class GoalUpdate(BaseModel):
    target: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=2, max_length=80)
    status: Literal["active", "archived"] | None = None


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: str, body: GoalUpdate, conn: Conn, user: CurrentUser) -> dict:
    goal = _goal_row(conn, goal_id)
    _own_record(user, goal["patient_id"])
    if body.target is not None and body.target > GOAL_KINDS[goal["kind"]]["max"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That target is higher than this goal allows")
    conn.execute(
        """
        UPDATE wellness_goals SET target = coalesce(%s, target), title = coalesce(%s, title),
               status = coalesce(%s, status)
        WHERE id = %s
        """,
        (body.target, body.title, body.status, goal_id),
    )
    audit.record(conn, action="goal_updated", entity_type="goal", entity_id=goal_id, actor=user,
                 patient_id=goal["patient_id"], detail=body.model_dump(exclude_none=True))
    return _goal_out(conn, _goal_row(conn, goal_id), date.today())


class EntryIn(BaseModel):
    value: float = Field(ge=0)


def _check_day(day: date) -> None:
    today = date.today()
    if day > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't log a day that hasn't happened yet")
    if day < today - timedelta(days=60):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can log up to 60 days back")


@router.put("/goals/{goal_id}/entries/{day}")
def log_entry(goal_id: str, day: date, body: EntryIn, conn: Conn, user: CurrentUser) -> dict:
    goal = _goal_row(conn, goal_id)
    _own_record(user, goal["patient_id"])
    _check_day(day)
    if body.value > GOAL_KINDS[goal["kind"]]["max"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That value is higher than this goal allows")
    if goal["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This goal is archived")
    entry = conn.execute(
        """
        INSERT INTO wellness_goal_entries (goal_id, patient_id, day, value) VALUES (%s, %s, %s, %s)
        ON CONFLICT (goal_id, day) DO UPDATE SET value = EXCLUDED.value, created_at = now()
        RETURNING id::text
        """,
        (goal_id, goal["patient_id"], day, body.value),
    ).fetchone()
    audit.record(conn, action="goal_logged", entity_type="goal_entry", entity_id=entry["id"], actor=user,
                 patient_id=goal["patient_id"], detail={"goal_id": goal_id, "day": day, "value": body.value})
    return _goal_out(conn, goal, date.today())


@router.delete("/goals/{goal_id}/entries/{day}")
def delete_entry(goal_id: str, day: date, conn: Conn, user: CurrentUser) -> dict:
    goal = _goal_row(conn, goal_id)
    _own_record(user, goal["patient_id"])
    conn.execute("DELETE FROM wellness_goal_entries WHERE goal_id = %s AND day = %s", (goal_id, day))
    audit.record(conn, action="goal_entry_deleted", entity_type="goal", entity_id=goal_id, actor=user,
                 patient_id=goal["patient_id"], detail={"day": day})
    return _goal_out(conn, goal, date.today())


# --- Lifestyle assessment -------------------------------------------------------------------------

ASSESSMENT_VERSION = "lifestyle-2026.09"

ASSESSMENT = {
    "version": ASSESSMENT_VERSION,
    "title": "Lifestyle check-in",
    "intro": "Five quick questions about your everyday habits. Your answers stay in your record.",
    "questions": [
        {"id": "active_days", "type": "number", "min": 0, "max": 7, "step": 1,
         "label": "On how many days in a typical week are you active for at least 30 minutes?"},
        {"id": "sleep_hours", "type": "number", "min": 0, "max": 24, "step": 0.5,
         "label": "How many hours do you usually sleep a night?"},
        {"id": "smoking", "type": "choice", "label": "Do you smoke or vape?",
         "options": [{"id": "never", "label": "Never"}, {"id": "former", "label": "I used to"},
                     {"id": "current", "label": "Yes, currently"}]},
        {"id": "alcohol_drinks_per_week", "type": "number", "min": 0, "max": 200, "step": 1,
         "label": "How many alcoholic drinks do you have in a typical week?"},
        {"id": "stress", "type": "choice", "label": "In the last two weeks, how often have you felt stressed?",
         "options": [{"id": "rarely", "label": "Rarely"}, {"id": "sometimes", "label": "Sometimes"},
                     {"id": "often", "label": "Often"}, {"id": "almost_always", "label": "Almost always"}]},
        {"id": "notes", "type": "text", "optional": True, "label": "Anything else you'd like your care team to know?"},
    ],
}


class AssessmentIn(BaseModel):
    active_days: int = Field(ge=0, le=7)
    sleep_hours: float = Field(ge=0, le=24)
    smoking: Literal["never", "former", "current"]
    alcohol_drinks_per_week: int = Field(ge=0, le=200)
    stress: Literal["rarely", "sometimes", "often", "almost_always"]
    notes: str | None = Field(default=None, max_length=1000)


def assess(a: AssessmentIn) -> dict[str, Any]:
    """Plain-language suggestions from the answers, plus at most one suggested goal. General wellness
    education only: no diagnosis, no medicines."""
    suggestions: list[dict[str, Any]] = []
    goal: dict[str, Any] | None = None

    if a.active_days < 5:
        suggestions.append({
            "id": "activity", "title": "Move a little more",
            "text": "Aim for about 30 minutes of movement on most days, like a brisk walk. Short bursts count, "
                    "and any increase from where you are now helps.",
        })
        goal = goal or {"kind": "active_minutes", "target": 30, "title": "Active minutes", "unit": "minutes",
                        "reason": "30 active minutes a day"}
    if a.sleep_hours < 7:
        suggestions.append({
            "id": "sleep", "title": "Protect your sleep",
            "text": "Most adults feel best with 7 to 9 hours. A regular bedtime, a dark cool room and less screen "
                    "time before bed can help.",
        })
        goal = goal or {"kind": "sleep_hours", "target": 7.5, "title": "Sleep", "unit": "hours",
                        "reason": "7.5 hours of sleep a night"}
    elif a.sleep_hours > 9:
        suggestions.append({
            "id": "sleep_long", "title": "Mention your sleep",
            "text": "Regularly needing more than 9 hours of sleep is worth mentioning at your next visit.",
            "specialty": "Primary care",
        })
    if a.smoking == "current":
        suggestions.append({
            "id": "smoking", "title": "Support to quit smoking",
            "text": "Stopping smoking is one of the best things you can do for your health, and support doubles "
                    "your chances. Your care team can talk you through the options.",
            "specialty": "Primary care",
        })
    if a.alcohol_drinks_per_week > 14:
        suggestions.append({
            "id": "alcohol", "title": "Cut back on alcohol",
            "text": "More than 14 drinks a week raises health risks. Try alcohol-free days each week, and talk to "
                    "your care team if cutting back is hard.",
            "specialty": "Primary care",
        })
    elif a.alcohol_drinks_per_week > 7:
        suggestions.append({
            "id": "alcohol_light", "title": "Keep an eye on alcohol",
            "text": "Having a few alcohol-free days each week is a simple way to keep drinking in a healthy range.",
        })
    if a.stress in ("often", "almost_always"):
        suggestions.append({
            "id": "stress", "title": "Look after your stress",
            "text": "Feeling stressed a lot of the time is hard. Regular movement, time outdoors and talking to "
                    "someone you trust can help, and your care team can connect you with support.",
            "specialty": "Primary care",
        })
    if not suggestions:
        suggestions.append({
            "id": "keep_going", "title": "You're doing well",
            "text": "Your answers show healthy habits. Keep going, and keep up with your preventive checks.",
        })
        goal = {"kind": "steps", "target": 7000, "title": "Daily steps", "unit": "steps",
                "reason": "7,000 steps a day to keep your momentum"}
    return {"suggestions": suggestions, "suggested_goal": goal}


@router.get("/assessment")
def assessment_definition(user: CurrentUser) -> dict:
    return ASSESSMENT


@router.post("/patients/{patient_id}/assessments", status_code=status.HTTP_201_CREATED)
def submit_assessment(patient_id: str, body: AssessmentIn, conn: Conn, user: CurrentUser) -> dict:
    _own_record(user, patient_id)
    answers = body.model_dump()

    # Free text is screened before anything else. An emergency stops the routine flow here.
    screen = red_flags.screen(body.notes) if body.notes and body.notes.strip() else red_flags.ScreenResult(level="none")
    if screen.level in ("emergency", "crisis"):
        row = conn.execute(
            """
            INSERT INTO wellness_assessments (patient_id, version, answers, red_flag_level)
            VALUES (%s, %s, %s, %s) RETURNING id::text, created_at
            """,
            (patient_id, ASSESSMENT_VERSION, Jsonb(answers), screen.level),
        ).fetchone()
        notified = notify_care_team(conn, user=user, patient_id=patient_id, flags=screen.flags, text=body.notes or "",
                                    source="wellness-assessment/red-flags", link=None)
        audit.record(conn, action="assessment_red_flag", entity_type="assessment", entity_id=row["id"], actor=user,
                     agent="safety/red-flags", patient_id=patient_id,
                     detail={"level": screen.level, "flags": screen.flags, "ruleset": screen.ruleset})
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "emergency": {
                "level": screen.level,
                "flags": screen.flags,
                "message": red_flags.emergency_message(screen),
                "emergency_number": red_flags.EMERGENCY_NUMBER,
                "crisis_line": red_flags.CRISIS_LINE if screen.level == "crisis" else None,
                "care_team_notified": notified,
            },
            "suggestions": [],
            "suggested_goal": None,
        }

    result = assess(body)
    notice = None
    if screen.level == "screen":
        notice = {"topic": screen.topic, "to": "/app", "initial": body.notes,
                  "message": "You mentioned something that can sometimes need urgent care. Please tell Bioverse "
                             "about it so it can check a few things with you."}
    row = conn.execute(
        """
        INSERT INTO wellness_assessments (patient_id, version, answers, suggestions, red_flag_level)
        VALUES (%s, %s, %s, %s, %s) RETURNING id::text, created_at
        """,
        (patient_id, ASSESSMENT_VERSION, Jsonb(answers), Jsonb(result["suggestions"]), screen.level),
    ).fetchone()
    audit.record(conn, action="assessment_completed", entity_type="assessment", entity_id=row["id"], actor=user,
                 agent="wellness-rules", patient_id=patient_id,
                 detail={"version": ASSESSMENT_VERSION, "suggestions": [s["id"] for s in result["suggestions"]]})
    return {"id": row["id"], "created_at": row["created_at"], "emergency": None, "symptom_notice": notice, **result}


@router.get("/patients/{patient_id}/assessments/latest")
def latest_assessment(patient_id: str, conn: Conn, user: CurrentUser) -> dict | None:
    assert_patient_access(conn, user, patient_id)
    return conn.execute(
        """
        SELECT id::text, version, answers, suggestions, red_flag_level, created_at
        FROM wellness_assessments WHERE patient_id = %s ORDER BY created_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
