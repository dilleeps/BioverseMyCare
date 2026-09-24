"""Weight coach: weigh-ins, BMI, a goal with guardrails, and a weekly check-in.

Guardrails, enforced here and nowhere else:
- No target below a BMI of 18.5 at the latest recorded height, and no loss goal when BMI is already below it.
- No pace faster than 1 kg a week.
- Before any goal, a gentle eating-disorder screen (SCOFF). Two or more "yes" answers route to the care team
  with a review item instead of coaching; a clinician clears it from the Nutrition & weight screen.

Weigh-ins live in `observations` (code `weight`, category 'vital-signs'); typed ones are source 'manual',
and readings from any other source (a smart scale, the clinic) are read the same way.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Clinician, CurrentUser
from bioverse.config import clinic_today, clinic_tz
from bioverse.db import DbConn
from bioverse.mind_escalation import own_open_item, raise_review, resolve_item
from bioverse.mind_instruments import crisis_support
from bioverse.routers.nutrition import own_record, read_access
from bioverse.vitals_codes import CODES

router = APIRouter(prefix="/api/weight", tags=["weight"])

Conn = DbConn
WEIGHT, HEIGHT = CODES["weight"], CODES["height"]
MIN_BMI = 18.5
MAX_PACE = 1.0
SCREEN_VALID_DAYS = 90
PACES = (0.25, 0.5, 0.75, 1.0)

SCOFF = {
    "id": "scoff",
    "title": "A few questions first",
    "intro": ("Before setting a weight goal, we ask everyone these five questions. They help make sure a weight "
              "coach is the right kind of support for you. There are no wrong answers."),
    "questions": [
        {"id": "sick", "text": "Do you make yourself sick because you feel uncomfortably full?"},
        {"id": "control", "text": "Do you worry that you have lost control over how much you eat?"},
        {"id": "one_stone", "text": "Have you recently lost more than 6 kg (about 14 lb) in a three-month period?"},
        {"id": "fat", "text": "Do you believe yourself to be fat when others say you are too thin?"},
        {"id": "food", "text": "Would you say that food dominates your life?"},
    ],
    "source": "Adapted from the SCOFF questionnaire (Morgan, Reid and Lacey, BMJ 1999;319:1467). Two or more "
              "“yes” answers suggest talking with a clinician.",
}
SCOFF_IDS = [q["id"] for q in SCOFF["questions"]]

ROUTED_MESSAGE = ("Thank you for answering honestly. Some of your answers suggest that eating and weight may be "
                  "weighing on you in ways a coaching app can't support well. We've asked your care team to check "
                  "in with you before any weight goal is set. You can still log meals and weigh-ins, and nothing "
                  "you do here is judged.")


def _bmi(weight_kg: float, height_cm: float) -> float:
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def _bmi_label(bmi: float) -> str:
    if bmi < 18.5:
        return "Below the healthy range"
    if bmi < 25:
        return "Healthy range"
    if bmi < 30:
        return "Above the healthy range"
    return "Well above the healthy range"


def min_target_kg(height_cm: float) -> float:
    return math.ceil(MIN_BMI * (height_cm / 100) ** 2 * 10) / 10


def weigh_ins(conn: Connection, patient_id: str, limit: int = 120) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id::text, value, effective_at, source, device FROM observations
        WHERE patient_id = %s AND loinc_code = %s ORDER BY effective_at DESC LIMIT %s
        """,
        (patient_id, WEIGHT.loinc, limit),
    ).fetchall()
    rows.reverse()
    return [{**r, "value": float(r["value"])} for r in rows]


def latest_height(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT value, effective_at, source FROM observations WHERE patient_id = %s AND loinc_code = %s
        ORDER BY effective_at DESC LIMIT 1
        """,
        (patient_id, HEIGHT.loinc),
    ).fetchone()
    return {**row, "value": float(row["value"])} if row else None


def _local_day(ts: datetime) -> date:
    return ts.astimezone(clinic_tz()).date()


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_averages(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weeks: dict[date, list[float]] = {}
    for p in points:
        weeks.setdefault(monday(_local_day(p["effective_at"])), []).append(p["value"])
    return [{"week_start": w, "average": round(sum(v) / len(v), 1), "count": len(v)} for w, v in sorted(weeks.items())]


def week_summary(points: list[dict[str, Any]], goal: dict[str, Any] | None, week_start: date) -> dict[str, Any]:
    """The coach's plain summary of one week against the week before. Static wording, no advice beyond the plan."""
    avgs = {w["week_start"]: w["average"] for w in weekly_averages(points)}
    this, prev = avgs.get(week_start), avgs.get(week_start - timedelta(days=7))
    change = round(this - prev, 1) if this is not None and prev is not None else None
    pct = None
    if goal and this is not None:
        span = goal["start_weight_kg"] - goal["target_weight_kg"]
        pct = round(max(0.0, min(100.0, 100 * (goal["start_weight_kg"] - this) / span))) if span > 0 else 100
    if this is None:
        msg = "No weigh-ins that week. Once a week, same time of day, is plenty."
    elif change is None:
        msg = f"Your average that week was {this:.1f} kg. Next week you'll see how it compares."
    elif goal and this <= goal["target_weight_kg"]:
        msg = f"Your average was {this:.1f} kg: you've reached your goal. Well done."
    elif change <= -MAX_PACE:
        msg = (f"Down {abs(change):.1f} kg, faster than 1 kg a week. Slower, steadier loss is easier to keep up; "
               "make sure you're eating regular meals. Your care team can help if you're unsure.")
    elif change < -0.1:
        msg = f"Down {abs(change):.1f} kg on the week before. That's in line with a steady plan."
    elif change <= 0.3:
        msg = "About the same as the week before. Weight goes up and down day to day; the trend over weeks matters most."
    else:
        msg = (f"Up {change:.1f} kg on the week before. Day-to-day changes are normal, often water. "
               "Keep going and look at the trend over a few weeks.")
    return {"week_start": week_start, "weekly_avg_kg": this, "change_kg": change, "percent_to_goal": pct, "message": msg}


def _goal(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id::text, start_weight_kg, target_weight_kg, pace_kg_week, height_cm, status, created_at, ended_at
        FROM weight_goals WHERE patient_id = %s ORDER BY (status = 'active') DESC, created_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row:
        for k in ("start_weight_kg", "target_weight_kg", "pace_kg_week", "height_cm"):
            row[k] = float(row[k])
    return row


def _screening(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT s.id::text, s.score, s.positive, s.cleared_at, s.created_at, r.status AS review_status
        FROM weight_screenings s LEFT JOIN review_items r ON r.id = s.review_item_id
        WHERE s.patient_id = %s ORDER BY s.created_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()


def screening_state(s: dict[str, Any] | None) -> str:
    """none | negative | cleared | paused_for_review | declined_by_care_team | expired"""
    if s is None:
        return "none"
    if s["positive"]:
        if s["cleared_at"]:
            return "cleared"
        return "declined_by_care_team" if s["review_status"] == "resolved" else "paused_for_review"
    if s["created_at"] < datetime.now(timezone.utc) - timedelta(days=SCREEN_VALID_DAYS):
        return "expired"
    return "negative"


def coach_view(conn: Connection, patient_id: str) -> dict[str, Any]:
    points = weigh_ins(conn, patient_id)
    height = latest_height(conn, patient_id)
    latest = points[-1] if points else None
    bmi = _bmi(latest["value"], height["value"]) if latest and height else None
    goal = _goal(conn, patient_id)
    screen = _screening(conn, patient_id)
    state = screening_state(screen)
    goal_out = None
    if goal:
        span = goal["start_weight_kg"] - goal["target_weight_kg"]
        now_w = latest["value"] if latest else goal["start_weight_kg"]
        remaining = max(0.0, round(now_w - goal["target_weight_kg"], 1))
        weeks_left = math.ceil(remaining / goal["pace_kg_week"]) if remaining > 0 else 0
        goal_out = {
            **goal,
            "change_kg": round(now_w - goal["start_weight_kg"], 1),
            "remaining_kg": remaining,
            "percent": round(max(0.0, min(100.0, 100 * (goal["start_weight_kg"] - now_w) / span))) if span > 0 else 100,
            "weeks_left": weeks_left,
            "expected_by": clinic_today() + timedelta(weeks=weeks_left),
            "target_bmi": _bmi(goal["target_weight_kg"], goal["height_cm"]),
        }
    today = clinic_today()
    checkins = conn.execute(
        """
        SELECT week_start, weekly_avg_kg, change_kg, percent_to_goal, message, created_at FROM weight_checkins
        WHERE patient_id = %s ORDER BY week_start DESC LIMIT 4
        """,
        (patient_id,),
    ).fetchall()
    return {
        "weigh_ins": points,
        "weekly": weekly_averages(points),
        "latest": latest,
        "height": height,
        "bmi": bmi,
        "bmi_label": _bmi_label(bmi) if bmi is not None else None,
        "goal": goal_out,
        "screening": {"state": state, "id": screen["id"] if screen else None,
                      "taken_at": screen["created_at"] if screen else None},
        "can_set_goal": state in ("negative", "cleared") and (goal is None or goal["status"] != "active"),
        "routed_message": ROUTED_MESSAGE if state in ("paused_for_review", "declined_by_care_team") else None,
        "guardrails": {"min_bmi": MIN_BMI, "min_target_kg": min_target_kg(height["value"]) if height else None,
                       "max_pace_kg_week": MAX_PACE, "paces": PACES},
        "this_week": week_summary(points, goal if goal and goal["status"] == "active" else None, monday(today)),
        "checkins": checkins,
        "today": today,
    }


@router.get("/patients/{patient_id}")
def get_coach(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    read_access(conn, user, patient_id, "weight")
    return coach_view(conn, patient_id)


class WeighInIn(BaseModel):
    weight_kg: float = Field(ge=25, le=350)
    measured_at: datetime | None = None


@router.post("/patients/{patient_id}/weigh-ins", status_code=status.HTTP_201_CREATED)
def add_weigh_in(patient_id: str, body: WeighInIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    at = body.measured_at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=clinic_tz())
    if at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That time hasn't happened yet")
    row = conn.execute(
        """
        INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                  category, source)
        VALUES (%s, %s, %s, %s, %s, 'N', %s, 'vital-signs', 'manual') RETURNING id::text
        """,
        (patient_id, WEIGHT.loinc, WEIGHT.display, round(body.weight_kg, 1), WEIGHT.unit, at),
    ).fetchone()
    audit.record(conn, action="weight_logged", entity_type="observation", entity_id=row["id"], actor=user,
                 patient_id=patient_id, detail={"weight_kg": round(body.weight_kg, 1)})
    return coach_view(conn, patient_id)


@router.delete("/patients/{patient_id}/weigh-ins/{observation_id}")
def delete_weigh_in(patient_id: str, observation_id: str, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    gone = conn.execute(
        """
        DELETE FROM observations WHERE id::text = %s AND patient_id = %s AND loinc_code = %s AND source = 'manual'
        RETURNING id::text
        """,
        (observation_id, patient_id, WEIGHT.loinc),
    ).fetchone()
    if gone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Only weigh-ins you typed in can be removed")
    audit.record(conn, action="weight_deleted", entity_type="observation", entity_id=observation_id, actor=user,
                 patient_id=patient_id)
    return coach_view(conn, patient_id)


class HeightIn(BaseModel):
    height_cm: float = Field(ge=100, le=250)


@router.post("/patients/{patient_id}/height", status_code=status.HTTP_201_CREATED)
def add_height(patient_id: str, body: HeightIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    row = conn.execute(
        """
        INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                  category, source)
        VALUES (%s, %s, %s, %s, %s, 'N', now(), 'vital-signs', 'manual') RETURNING id::text
        """,
        (patient_id, HEIGHT.loinc, HEIGHT.display, round(body.height_cm, 1), HEIGHT.unit),
    ).fetchone()
    audit.record(conn, action="height_logged", entity_type="observation", entity_id=row["id"], actor=user,
                 patient_id=patient_id)
    return coach_view(conn, patient_id)


# --- Screening and goal ------------------------------------------------------------------------------------------


@router.get("/screening")
def screening_definition(user: CurrentUser) -> dict:
    return SCOFF


class ScreeningIn(BaseModel):
    answers: dict[str, bool]


def score_scoff(answers: dict[str, bool]) -> tuple[int, bool]:
    if set(answers) != set(SCOFF_IDS):
        raise ValueError("Answer all five questions")
    total = sum(1 for k in SCOFF_IDS if answers[k])
    return total, total >= 2


@router.post("/patients/{patient_id}/screening", status_code=status.HTTP_201_CREATED)
def take_screening(patient_id: str, body: ScreeningIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    try:
        total, positive = score_scoff(body.answers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO weight_screenings (id, patient_id, answers, score, positive) VALUES (%s, %s, %s, %s, %s)",
        (sid, patient_id, Jsonb(body.answers), total, positive),
    )
    audit.record(conn, action="weight_screening_completed", entity_type="weight_screening", entity_id=sid, actor=user,
                 agent="weight-coach/rules", patient_id=patient_id, detail={"score": total, "positive": positive})
    if not positive:
        return {"id": sid, "positive": False, "routed_to_care_team": False, "message": None}

    item_id = raise_review(
        conn, patient_id=patient_id, kind="weight_screen", priority="routine", actor=user, agent="weight-coach/rules",
        ref_id=sid, link=f"/clinician/nutrition/{patient_id}",
        title=f"Eating screen positive before weight coaching (SCOFF {total}/5)",
        body=(f"The patient asked for a weight-loss goal. SCOFF screen: {total} of 5 answered yes ("
              + ", ".join(q["text"] for q in SCOFF["questions"] if body.answers[q["id"]])
              + "). Weight coaching is paused until you review. Clear coaching, or keep it paused and follow up."),
        notify_title="A patient's weight coaching needs your review",
    )
    if item_id:
        conn.execute("UPDATE weight_screenings SET review_item_id = %s WHERE id = %s", (item_id, sid))
    return {"id": sid, "positive": True, "routed_to_care_team": item_id is not None, "message": ROUTED_MESSAGE,
            "support": crisis_support()}


class GoalIn(BaseModel):
    screening_id: str
    target_weight_kg: float = Field(gt=0, le=350)
    pace_kg_week: float = Field(gt=0)


def check_goal(current_kg: float, height_cm: float, target_kg: float, pace: float) -> None:
    """Raise 422 with a plain reason when a goal breaks a guardrail."""
    if pace > MAX_PACE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "The coach allows at most 1 kg a week. Slower loss is safer and easier to keep up.")
    if _bmi(current_kg, height_cm) < MIN_BMI:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Your weight is already below the healthy range for your height, so the coach can't set a "
                            "weight-loss goal. Your care team can help you think about what's right for you.")
    floor = min_target_kg(height_cm)
    if target_kg < floor:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"That target is below the healthy range for your height. The lowest goal the coach can "
                            f"set is {floor:.1f} kg (a BMI of {MIN_BMI}).")
    if target_kg >= current_kg:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "The coach helps with losing weight, so the target needs to be below your current weight.")


@router.post("/patients/{patient_id}/goal", status_code=status.HTTP_201_CREATED)
def set_goal(patient_id: str, body: GoalIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    s = conn.execute(
        """
        SELECT s.id::text, s.positive, s.cleared_at, s.created_at, r.status AS review_status
        FROM weight_screenings s LEFT JOIN review_items r ON r.id = s.review_item_id
        WHERE s.id::text = %s AND s.patient_id = %s
        """,
        (body.screening_id, patient_id),
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Answer the screening questions first")
    latest = _screening(conn, patient_id)
    state = screening_state(s)
    if latest["id"] != s["id"] or state not in ("negative", "cleared"):
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "screening", "state": state,
                                                        "message": ROUTED_MESSAGE if s["positive"] else
                                                        "Please answer the screening questions again."})
    if conn.execute("SELECT 1 FROM weight_goals WHERE patient_id = %s AND status = 'active'", (patient_id,)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a goal. Stop it first to set a new one.")
    points = weigh_ins(conn, patient_id, limit=1)
    height = latest_height(conn, patient_id)
    if not points:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Log a weigh-in first")
    if not height:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add your height first")
    current = points[-1]["value"]
    check_goal(current, height["value"], body.target_weight_kg, body.pace_kg_week)
    gid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO weight_goals (id, patient_id, start_weight_kg, target_weight_kg, pace_kg_week, height_cm, screening_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (gid, patient_id, current, round(body.target_weight_kg, 1), body.pace_kg_week, height["value"], s["id"]),
    )
    audit.record(conn, action="weight_goal_set", entity_type="weight_goal", entity_id=gid, actor=user,
                 agent="weight-coach/rules", patient_id=patient_id,
                 detail={"target_kg": body.target_weight_kg, "pace": body.pace_kg_week})
    return coach_view(conn, patient_id)


@router.post("/patients/{patient_id}/goal/stop")
def stop_goal(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    row = conn.execute(
        "UPDATE weight_goals SET status = 'stopped', ended_at = now() WHERE patient_id = %s AND status = 'active' RETURNING id::text",
        (patient_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active goal")
    audit.record(conn, action="weight_goal_stopped", entity_type="weight_goal", entity_id=row["id"], actor=user,
                 patient_id=patient_id)
    return coach_view(conn, patient_id)


# --- Clinician: decide on a positive screen -------------------------------------------------------------------------


class ScreenDecisionIn(BaseModel):
    action: Literal["clear", "keep_paused", "acknowledge"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/review-items/{item_id}/resolve")
def resolve_screen(item_id: str, body: ScreenDecisionIn, conn: Conn, user: Clinician) -> dict:
    """A positive eating screen (clear coaching or keep it paused), or a home reading alert (acknowledge)."""
    item = own_open_item(conn, item_id, user, ("weight_screen", "vital_alert"))
    allowed = {"acknowledge"} if item["kind"] == "vital_alert" else {"clear", "keep_paused"}
    if body.action not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{body.action}' is not valid for this item")
    if body.action == "clear":
        conn.execute("UPDATE weight_screenings SET cleared_by = %s, cleared_at = now() WHERE id::text = %s",
                     (user.id, item["ref_id"]))
    note = (body.note or "").strip()
    label = {"clear": "Cleared for weight coaching", "keep_paused": "Weight coaching kept paused",
             "acknowledge": "Acknowledged"}[body.action]
    resolve_item(conn, item, user, label + (f": {note}" if note else ""))
    return {"id": item_id, "status": "resolved", "action": body.action}
