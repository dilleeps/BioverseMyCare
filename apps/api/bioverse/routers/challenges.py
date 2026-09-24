"""Challenges and rewards: join (opt-in), live progress from real data, family challenges, demo perks.

No leaderboards: a patient only ever sees their own points and badges. A family challenge shows the team's
combined progress and who has joined, never a ranking. Family members are the people linked to the patient
in Family & caregivers (related_persons with an active caregiver_access consent, in either direction), and
each one joins only by accepting the invitation themselves.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field, model_validator

from bioverse import audit, consent
from bioverse.auth import CurrentUser, User
from bioverse.challenge_engine import (BADGES, BY_ID, DEFINITIONS, REWARD_NOTE, balance, progress, redemption_code,
                                       required_periods, add_points)
from bioverse.config import clinic_today, clinic_tz
from bioverse.db import DbConn
from bioverse.notify import notify
from bioverse.routers import vitals_core
from bioverse.routers.nutrition import own_record, read_access
from bioverse.vitals_codes import CODES, interpret

router = APIRouter(prefix="/api/challenges", tags=["challenges"])

Conn = DbConn


def _definition_out(d: dict[str, Any]) -> dict[str, Any]:
    return {k: d[k] for k in ("id", "title", "description", "metric", "target", "unit", "period", "duration_days",
                              "points", "points_per_period", "family_allowed", "badge")} | {"required": required_periods(d)}


@router.get("/catalog")
def catalog(conn: Conn, user: CurrentUser) -> dict:
    rewards = conn.execute(
        "SELECT id, title, description, cost FROM challenge_rewards WHERE active ORDER BY position").fetchall()
    return {"challenges": [_definition_out(d) for d in DEFINITIONS], "rewards": rewards, "reward_note": REWARD_NOTE,
            "badges": BADGES}


# --- Family -------------------------------------------------------------------------------------------------------


def family_of(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    """Patients linked to this one through Family & caregivers, with consent currently granted."""
    me = conn.execute("SELECT user_id::text, organization_id::text FROM patients WHERE id = %s", (patient_id,)).fetchone()
    rows = conn.execute(
        """
        SELECT DISTINCT p.id::text, p.name, p.user_id::text FROM patients p
        WHERE p.id <> %(me)s AND p.organization_id = %(org)s AND p.user_id IS NOT NULL AND (
            EXISTS (SELECT 1 FROM related_persons rp WHERE rp.patient_id = p.id AND rp.user_id = %(uid)s)
            OR EXISTS (SELECT 1 FROM related_persons rp WHERE rp.patient_id = %(me)s AND rp.user_id = p.user_id))
        ORDER BY p.name
        """,
        {"me": patient_id, "org": me["organization_id"], "uid": me["user_id"]},
    ).fetchall()
    return [
        {"patient_id": r["id"], "name": r["name"].split()[0], "user_id": r["user_id"]}
        for r in rows
        if consent.is_granted(conn, r["id"], "caregiver_access", me["user_id"])
        or consent.is_granted(conn, patient_id, "caregiver_access", r["user_id"])
    ]


def _team_view(conn: Connection, team_id: str, viewer: str, today: date) -> dict[str, Any]:
    team = conn.execute(
        "SELECT id::text, definition_id, created_by::text, started_on, ends_on FROM challenge_teams WHERE id::text = %s",
        (team_id,),
    ).fetchone()
    d = BY_ID[team["definition_id"]]
    members = conn.execute(
        """
        SELECT m.patient_id::text, m.status, p.name,
               (SELECT e.id::text FROM challenge_enrollments e WHERE e.team_id = m.team_id AND e.patient_id = m.patient_id
                ORDER BY e.created_at DESC LIMIT 1) AS enrollment_id
        FROM challenge_team_members m JOIN patients p ON p.id = m.patient_id
        WHERE m.team_id = %s ORDER BY p.name
        """,
        (team_id,),
    ).fetchall()
    met = needed = 0
    for m in members:
        if m["status"] == "joined" and m["enrollment_id"]:
            e = conn.execute(
                "SELECT id::text, patient_id::text, definition_id, started_on, ends_on FROM challenge_enrollments WHERE id = %s",
                (m["enrollment_id"],),
            ).fetchone()
            p = progress(conn, e, today)
            met += min(p["periods_met"], p["required"])
            needed += p["required"]
    me = next((m for m in members if m["patient_id"] == viewer), None)
    return {
        "id": team["id"], "challenge": _definition_out(d), "started_on": team["started_on"], "ends_on": team["ends_on"],
        "started_by_me": team["created_by"] == viewer, "my_status": me["status"] if me else None,
        # First names and whether they've joined. Never anyone's individual numbers.
        "members": [{"name": "You" if m["patient_id"] == viewer else m["name"].split()[0], "status": m["status"]}
                    for m in members],
        "together": {"met": met, "needed": needed, "percent": round(100 * met / needed) if needed else 0},
    }


# --- My challenges ----------------------------------------------------------------------------------------------


def _enrollments(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id::text, patient_id::text, definition_id, team_id::text, started_on, ends_on, status, periods_met,
               best_streak, completed_at, created_at
        FROM challenge_enrollments WHERE patient_id = %s AND status <> 'left'
        ORDER BY status = 'active' DESC, created_at DESC LIMIT 20
        """,
        (patient_id,),
    ).fetchall()


def overview(conn: Connection, patient_id: str) -> dict[str, Any]:
    today = clinic_today()
    active, past = [], []
    for e in _enrollments(conn, patient_id):
        d = BY_ID[e["definition_id"]]
        item = {**e, "challenge": _definition_out(d)}
        if e["status"] == "active":
            item["progress"] = progress(conn, e, today)
            active.append(item)
        else:
            past.append(item)
    teams = conn.execute(
        """
        SELECT m.team_id::text FROM challenge_team_members m JOIN challenge_teams t ON t.id = m.team_id
        WHERE m.patient_id = %s AND m.status IN ('invited', 'joined') AND t.ends_on >= %s ORDER BY t.created_at DESC
        """,
        (patient_id, today),
    ).fetchall()
    return {
        "today": today,
        "points": balance(conn, patient_id),
        "active": active,
        "past": past[:10],
        "joined_ids": [e["definition_id"] for e in active],
        "badges": conn.execute(
            "SELECT badge, title, awarded_at FROM challenge_badges WHERE patient_id = %s ORDER BY awarded_at DESC",
            (patient_id,)).fetchall(),
        "redemptions": conn.execute(
            """
            SELECT r.id::text, r.reward_id, w.title, r.points, r.code, r.created_at FROM challenge_redemptions r
            JOIN challenge_rewards w ON w.id = r.reward_id WHERE r.patient_id = %s ORDER BY r.created_at DESC
            """,
            (patient_id,)).fetchall(),
        "points_history": conn.execute(
            "SELECT delta, reason, created_at FROM challenge_points WHERE patient_id = %s ORDER BY created_at DESC LIMIT 15",
            (patient_id,)).fetchall(),
        "teams": [_team_view(conn, t["team_id"], patient_id, today) for t in teams],
        "family": [{"patient_id": f["patient_id"], "name": f["name"]} for f in family_of(conn, patient_id)],
    }


@router.get("/patients/{patient_id}")
def get_overview(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    read_access(conn, user, patient_id, "challenges")
    return overview(conn, patient_id)


def _start(conn: Connection, patient_id: str, definition_id: str, start: date, team_id: str | None,
           user: User) -> str:
    d = BY_ID.get(definition_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown challenge")
    if conn.execute("SELECT 1 FROM challenge_enrollments WHERE patient_id = %s AND definition_id = %s AND status = 'active'",
                    (patient_id, definition_id)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "You're already doing this challenge")
    eid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO challenge_enrollments (id, patient_id, definition_id, team_id, started_on, ends_on)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (eid, patient_id, definition_id, team_id, start, start + timedelta(days=d["duration_days"] - 1)),
    )
    audit.record(conn, action="challenge_joined", entity_type="challenge_enrollment", entity_id=eid, actor=user,
                 patient_id=patient_id, detail={"definition": definition_id, "team": team_id})
    return eid


class JoinIn(BaseModel):
    definition_id: str = Field(max_length=60)


@router.post("/patients/{patient_id}/enrollments", status_code=status.HTTP_201_CREATED)
def join(patient_id: str, body: JoinIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    _start(conn, patient_id, body.definition_id, clinic_today(), None, user)
    return overview(conn, patient_id)


@router.post("/enrollments/{enrollment_id}/leave")
def leave(enrollment_id: str, conn: Conn, user: CurrentUser) -> dict:
    e = conn.execute("SELECT id::text, patient_id::text, team_id::text, status FROM challenge_enrollments WHERE id::text = %s",
                     (enrollment_id,)).fetchone()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Challenge not found")
    own_record(user, e["patient_id"])
    if e["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This challenge has already finished")
    conn.execute("UPDATE challenge_enrollments SET status = 'left' WHERE id = %s", (enrollment_id,))
    if e["team_id"]:
        conn.execute("UPDATE challenge_team_members SET status = 'left', responded_at = now() WHERE team_id = %s AND patient_id = %s",
                     (e["team_id"], e["patient_id"]))
    audit.record(conn, action="challenge_left", entity_type="challenge_enrollment", entity_id=enrollment_id, actor=user,
                 patient_id=e["patient_id"])
    return overview(conn, e["patient_id"])


# --- Family challenges ------------------------------------------------------------------------------------------


class TeamIn(BaseModel):
    definition_id: str = Field(max_length=60)
    invite: list[str] = Field(min_length=1, max_length=6)


@router.post("/patients/{patient_id}/teams", status_code=status.HTTP_201_CREATED)
def start_team(patient_id: str, body: TeamIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    d = BY_ID.get(body.definition_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown challenge")
    if not d["family_allowed"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This one is a personal challenge")
    family = {f["patient_id"]: f for f in family_of(conn, patient_id)}
    invite = list(dict.fromkeys(body.invite))
    if any(pid not in family for pid in invite):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only invite people linked to you in Family & caregivers")
    today = clinic_today()
    tid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO challenge_teams (id, definition_id, created_by, started_on, ends_on) VALUES (%s, %s, %s, %s, %s)",
        (tid, d["id"], patient_id, today, today + timedelta(days=d["duration_days"] - 1)),
    )
    conn.execute("INSERT INTO challenge_team_members (team_id, patient_id, status, invited_by, responded_at) "
                 "VALUES (%s, %s, 'joined', %s, now())", (tid, patient_id, patient_id))
    _start(conn, patient_id, d["id"], today, tid, user)
    me = conn.execute("SELECT name FROM patients WHERE id = %s", (patient_id,)).fetchone()
    for pid in invite:
        conn.execute("INSERT INTO challenge_team_members (team_id, patient_id, invited_by) VALUES (%s, %s, %s)",
                     (tid, pid, patient_id))
        notify(conn, user_id=family[pid]["user_id"], kind="challenge", title="You're invited to a family challenge",
               body=f"{me['name'].split()[0]} invited you to “{d['title']}”. Join only if you'd like to.",
               link="/challenges", patient_id=pid, dedupe_key=f"team:{tid}:invite")
    audit.record(conn, action="family_challenge_started", entity_type="challenge_team", entity_id=tid, actor=user,
                 patient_id=patient_id, detail={"definition": d["id"], "invited": len(invite)})
    return overview(conn, patient_id)


class RespondIn(BaseModel):
    accept: bool


@router.post("/teams/{team_id}/respond")
def respond(team_id: str, body: RespondIn, conn: Conn, user: CurrentUser) -> dict:
    if user.role != "patient" or not user.patient_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the invited person can answer")
    m = conn.execute(
        """
        SELECT m.status, t.definition_id, t.started_on, t.ends_on FROM challenge_team_members m
        JOIN challenge_teams t ON t.id = m.team_id WHERE m.team_id::text = %s AND m.patient_id = %s
        """,
        (team_id, user.patient_id),
    ).fetchone()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if m["status"] != "invited":
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already answered this invitation")
    if body.accept:
        if m["ends_on"] < clinic_today():
            raise HTTPException(status.HTTP_409_CONFLICT, "This challenge has already finished")
        eid = _start(conn, user.patient_id, m["definition_id"], m["started_on"], team_id, user)
        conn.execute("UPDATE challenge_enrollments SET ends_on = %s WHERE id = %s", (m["ends_on"], eid))
    conn.execute(
        "UPDATE challenge_team_members SET status = %s, responded_at = now() WHERE team_id::text = %s AND patient_id = %s",
        ("joined" if body.accept else "declined", team_id, user.patient_id),
    )
    # Joining is this person's own consent to share combined progress with the team.
    audit.record(conn, action="family_challenge_joined" if body.accept else "family_challenge_declined",
                 entity_type="challenge_team", entity_id=team_id, actor=user, patient_id=user.patient_id)
    return overview(conn, user.patient_id)


# --- Logging activity for a challenge ------------------------------------------------------------------------------


class LogIn(BaseModel):
    metric: Literal["steps", "active_minutes", "bp"]
    value: float | None = Field(default=None, ge=0, le=100000)
    systolic: int | None = Field(default=None, ge=50, le=300)
    diastolic: int | None = Field(default=None, ge=30, le=200)
    day: date | None = None

    @model_validator(mode="after")
    def complete(self) -> "LogIn":
        if self.metric == "bp" and (self.systolic is None or self.diastolic is None):
            raise ValueError("A blood pressure reading needs both numbers")
        if self.metric != "bp" and self.value is None:
            raise ValueError("Enter a value")
        if self.metric == "active_minutes" and (self.value or 0) > 1440:
            raise ValueError("That's more minutes than a day has")
        return self


def _obs(conn: Connection, patient_id: str, key: str, value: float, at: datetime, panel: str | None = None) -> str:
    c = CODES[key]
    return conn.execute(
        """
        INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                  category, source, panel_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s) RETURNING id::text
        """,
        (patient_id, c.loinc, c.display, value, c.unit, interpret(c, value), at, c.category, panel),
    ).fetchone()["id"]


@router.post("/patients/{patient_id}/log", status_code=status.HTTP_201_CREATED)
def log_activity(patient_id: str, body: LogIn, conn: Conn, user: CurrentUser) -> dict:
    """Steps, active minutes or a blood pressure reading, stored as ordinary observations."""
    own_record(user, patient_id)
    today = clinic_today()
    day = body.day or today
    if day > today or day < today - timedelta(days=7):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can log today or up to a week back")
    now_local = datetime.now(clinic_tz())
    at = now_local if day == today else datetime.combine(day, time(20, 0), tzinfo=clinic_tz())
    warning = None
    if body.metric == "bp":
        # Same path as the Vitals screen, so alerts, thresholds and the care team's queue stay in one place.
        reading = vitals_core.store_reading(
            conn, patient_id=patient_id, values=[("bp_systolic", body.systolic), ("bp_diastolic", body.diastolic)],
            taken_at=at, source="manual", note="Logged for a blood pressure challenge")
        result = vitals_core.evaluate(conn, patient_id, reading)
        if result["safety"]:
            warning = f"{result['safety']['message']} Your care team has been told."
        elif any(a["severity"] == "critical" for a in result["alerts"]):
            warning = "That reading is outside the safe range. Your care team has been told."
        detail = {"systolic": body.systolic, "diastolic": body.diastolic}
    else:
        _obs(conn, patient_id, body.metric, round(body.value or 0), at)
        detail = {body.metric: body.value}
    audit.record(conn, action="activity_logged", entity_type="patient", entity_id=patient_id, actor=user,
                 patient_id=patient_id, detail={"metric": body.metric, "day": day, **detail})
    return {**overview(conn, patient_id), "warning": warning}


# --- Rewards --------------------------------------------------------------------------------------------------------


class RedeemIn(BaseModel):
    reward_id: str = Field(max_length=60)


@router.post("/patients/{patient_id}/redemptions", status_code=status.HTTP_201_CREATED)
def redeem(patient_id: str, body: RedeemIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    reward = conn.execute("SELECT id, title, cost FROM challenge_rewards WHERE id = %s AND active",
                          (body.reward_id,)).fetchone()
    if reward is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reward not found")
    conn.execute("SELECT id FROM patients WHERE id = %s FOR UPDATE", (patient_id,))  # one redemption at a time
    if balance(conn, patient_id) < reward["cost"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not enough points yet")
    rid = str(uuid.uuid4())
    code = redemption_code()
    conn.execute(
        "INSERT INTO challenge_redemptions (id, patient_id, reward_id, points, code) VALUES (%s, %s, %s, %s, %s)",
        (rid, patient_id, reward["id"], reward["cost"], code),
    )
    add_points(conn, patient_id, -reward["cost"], f"Redeemed: {reward['title']}", f"redeem:{rid}")
    audit.record(conn, action="reward_redeemed", entity_type="challenge_redemption", entity_id=rid, actor=user,
                 patient_id=patient_id, detail={"reward": reward["id"], "points": reward["cost"]})
    return {**overview(conn, patient_id), "redeemed": {"id": rid, "title": reward["title"], "code": code}}
