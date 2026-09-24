"""Challenges and rewards: the catalog, progress from real data, and idempotent awarding.

Progress is always computed from what the record holds, never typed in as "progress":
    steps, active minutes    observations (category 'activity', any source) and the patient's own
                             wellness goal entries for the same measure; the higher value of the day wins
    blood pressure logged    any systolic reading (observations, category 'vital-signs') that day
    vegetables, water        the meal log (nutrition_intake_items)

`sync_enrollment` turns progress into points, badges, completion and milestone notifications. Every award
has a dedupe key or a unique constraint, so running it twice (the daily job, then a reseed) changes nothing.

Fairness: nobody sees anyone else's points, there is no ranking, and family challenges only show the
team's combined progress.
"""

from __future__ import annotations

import math
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from psycopg import Connection

from bioverse import audit
from bioverse.config import clinic_tz
from bioverse.notify import notify, patient_user
from bioverse.vitals_codes import CODES

DEFINITIONS: list[dict[str, Any]] = [
    {"id": "steps_7k_7d", "title": "7,000 steps a day for 7 days",
     "description": "Walk 7,000 steps or more every day for a week. Steps from your phone, a device or typed in all count.",
     "metric": "steps", "target": 7000, "unit": "steps", "period": "day", "duration_days": 7, "points": 100,
     "points_per_period": 10, "family_allowed": True, "position": 10, "badge": "Step champion"},
    {"id": "active_150_week", "title": "150 active minutes in a week",
     "description": "Build up 150 minutes of movement that raises your heart rate over 7 days, in any size pieces.",
     "metric": "active_minutes", "target": 150, "unit": "minutes", "period": "week", "duration_days": 7, "points": 100,
     "points_per_period": 50, "family_allowed": True, "position": 20, "badge": "Active week"},
    {"id": "bp_daily_14d", "title": "Check your blood pressure daily for 14 days",
     "description": "Take and log one home blood pressure reading every day for two weeks.",
     "metric": "bp_logged", "target": 1, "unit": "reading", "period": "day", "duration_days": 14, "points": 150,
     "points_per_period": 10, "family_allowed": False, "position": 30, "badge": "Pressure pro"},
    {"id": "veg_5_7d", "title": "5 servings of vegetables a day for 7 days",
     "description": "Log meals with 5 servings of vegetables a day. One serving is 1/2 cup cooked or 1 cup of salad leaves.",
     "metric": "veg_servings", "target": 5, "unit": "servings", "period": "day", "duration_days": 7, "points": 100,
     "points_per_period": 10, "family_allowed": True, "position": 40, "badge": "Veg five"},
    {"id": "hydration_8_7d", "title": "8 glasses of water a day for 7 days",
     "description": "Log about 8 glasses (1.9 litres) of water, sparkling water, unsweetened tea or black coffee a day.",
     "metric": "water_ml", "target": 1900, "unit": "ml", "period": "day", "duration_days": 7, "points": 100,
     "points_per_period": 10, "family_allowed": True, "position": 50, "badge": "Hydration hero"},
]
BY_ID = {d["id"]: d for d in DEFINITIONS}

# Clearly fictional demo perks. Nothing is sent and no real business is involved.
REWARDS: list[dict[str, Any]] = [
    {"id": "demo-tree", "title": "Plant a pretend tree", "cost": 50, "position": 10,
     "description": "A make-believe tree in a make-believe forest. Demo perk: nothing real happens."},
    {"id": "demo-smoothie", "title": "Smoothie at the fictional Harbor Leaf Cafe", "cost": 100, "position": 20,
     "description": "A demo voucher for a cafe that does not exist. Not redeemable anywhere."},
    {"id": "demo-yoga", "title": "One class at the imaginary Juniper Lane Yoga", "cost": 150, "position": 30,
     "description": "A demo perk for an invented studio. Not redeemable anywhere."},
    {"id": "demo-socks", "title": "Bioverse walking socks (demo only)", "cost": 200, "position": 40,
     "description": "Pretend socks for a pretend walk. Nothing will be shipped."},
    {"id": "demo-market", "title": "$5 off at the made-up Greenfield Market", "cost": 250, "position": 50,
     "description": "A demo coupon for a market that does not exist. Not redeemable anywhere."},
]
REWARD_NOTE = "These are demo perks for a fictional rewards program. No real businesses, products or money are involved."

BADGES = {
    "first_goal_day": "First day on target",
    "streak_3": "3-day streak",
    "streak_7": "7-day streak",
    "family_finish": "Team effort",
    **{f"complete_{d['id']}": d["badge"] for d in DEFINITIONS},
}
MILESTONE_STREAKS = (3, 7)


def seed_catalog(conn: Connection) -> None:
    """Upsert the catalog so edits here reach existing databases."""
    for d in DEFINITIONS:
        conn.execute(
            """
            INSERT INTO challenge_definitions (id, title, description, metric, target, unit, period, duration_days,
                                               points, points_per_period, family_allowed, position)
            VALUES (%(id)s, %(title)s, %(description)s, %(metric)s, %(target)s, %(unit)s, %(period)s, %(duration_days)s,
                    %(points)s, %(points_per_period)s, %(family_allowed)s, %(position)s)
            ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,
                target = EXCLUDED.target, unit = EXCLUDED.unit, points = EXCLUDED.points,
                points_per_period = EXCLUDED.points_per_period, family_allowed = EXCLUDED.family_allowed,
                position = EXCLUDED.position
            """,
            d,
        )
    for r in REWARDS:
        conn.execute(
            """
            INSERT INTO challenge_rewards (id, title, description, cost, position)
            VALUES (%(id)s, %(title)s, %(description)s, %(cost)s, %(position)s)
            ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,
                cost = EXCLUDED.cost, position = EXCLUDED.position
            """,
            r,
        )


# --- Data per day ------------------------------------------------------------------------------------------


def _tz() -> str:
    return str(clinic_tz())


def daily_values(conn: Connection, patient_id: str, metric: str, start: date, end: date) -> dict[date, float]:
    """{day: value} for one metric between two clinic-local days, inclusive."""
    params = {"p": patient_id, "s": start, "e": end, "tz": _tz()}
    out: dict[date, float] = {}

    def merge(rows, how=max):
        for r in rows:
            d, v = r["day"], float(r["value"] or 0)
            out[d] = how(out.get(d, 0.0), v)

    if metric in ("steps", "active_minutes"):
        code = CODES[metric].loinc
        agg = "max" if metric == "steps" else "sum"
        merge(conn.execute(
            f"""
            SELECT (effective_at AT TIME ZONE %(tz)s)::date AS day, {agg}(value) AS value FROM observations
            WHERE patient_id = %(p)s AND loinc_code = %(code)s AND category = 'activity'
              AND (effective_at AT TIME ZONE %(tz)s)::date BETWEEN %(s)s AND %(e)s
            GROUP BY 1
            """,
            {**params, "code": code},
        ).fetchall())
        # The same measure tracked as a wellness goal (patient-reported) also counts.
        merge(conn.execute(
            """
            SELECT e.day, max(e.value) AS value FROM wellness_goal_entries e JOIN wellness_goals g ON g.id = e.goal_id
            WHERE e.patient_id = %(p)s AND g.kind = %(kind)s AND e.day BETWEEN %(s)s AND %(e)s GROUP BY 1
            """,
            {**params, "kind": metric},
        ).fetchall())
    elif metric == "bp_logged":
        merge(conn.execute(
            """
            SELECT (effective_at AT TIME ZONE %(tz)s)::date AS day, 1 AS value FROM observations
            WHERE patient_id = %(p)s AND loinc_code = %(code)s
              AND (effective_at AT TIME ZONE %(tz)s)::date BETWEEN %(s)s AND %(e)s
            GROUP BY 1
            """,
            {**params, "code": CODES["bp_systolic"].loinc},
        ).fetchall())
    elif metric in ("veg_servings", "water_ml"):
        merge(conn.execute(
            f"""
            SELECT n.eaten_on AS day, sum(i.{metric}) AS value FROM nutrition_intake_items i
            JOIN nutrition_intakes n ON n.id = i.intake_id
            WHERE n.patient_id = %(p)s AND n.eaten_on BETWEEN %(s)s AND %(e)s GROUP BY 1
            """,
            params,
        ).fetchall())
    else:
        raise ValueError(metric)
    return out


# --- Progress ------------------------------------------------------------------------------------------------


def required_periods(d: dict[str, Any]) -> int:
    return d["duration_days"] if d["period"] == "day" else max(1, d["duration_days"] // 7)


def progress(conn: Connection, enrollment: dict[str, Any], today: date) -> dict[str, Any]:
    """Live progress for one enrollment. Pure read."""
    d = BY_ID[enrollment["definition_id"]]
    start, end = enrollment["started_on"], enrollment["ends_on"]
    values = daily_values(conn, enrollment["patient_id"], d["metric"], start, min(end, today))
    target = float(d["target"])
    periods: list[dict[str, Any]] = []
    if d["period"] == "day":
        day = start
        while day <= end:
            v = values.get(day)
            periods.append({"start": day, "end": day, "value": v, "met": v is not None and v >= target,
                            "future": day > today, "today": day == today})
            day += timedelta(days=1)
    else:
        for k in range(required_periods(d)):
            s = start + timedelta(days=7 * k)
            e = min(s + timedelta(days=6), end)
            total = sum(v for dd, v in values.items() if s <= dd <= e)
            periods.append({"start": s, "end": e, "value": total, "met": total >= target,
                            "future": s > today, "today": s <= today <= e})

    met = sum(1 for p in periods if p["met"])
    # Current streak runs back from today; an unfinished today never breaks it.
    closed = [p for p in periods if not p["future"]]
    if closed and closed[-1]["today"] and not closed[-1]["met"]:
        closed = closed[:-1]
    streak = 0
    for p in reversed(closed):
        if not p["met"]:
            break
        streak += 1
    best = run = 0
    for p in periods:
        run = run + 1 if p["met"] else 0
        best = max(best, run)
    needed = required_periods(d)
    current = next((p for p in periods if p["today"]), None)
    return {
        "periods": periods,
        "periods_met": met,
        "required": needed,
        "current_streak": streak,
        "best_streak": best,
        "percent": round(100 * min(met, needed) / needed),
        "complete": met >= needed,
        "today_value": current["value"] if current else None,
        "over": today > end,
    }


# --- Awards --------------------------------------------------------------------------------------------------


def add_points(conn: Connection, patient_id: str, delta: int, reason: str, dedupe_key: str,
               enrollment_id: str | None = None) -> bool:
    row = conn.execute(
        """
        INSERT INTO challenge_points (patient_id, delta, reason, enrollment_id, dedupe_key)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (patient_id, dedupe_key) DO NOTHING RETURNING id
        """,
        (patient_id, delta, reason, enrollment_id, dedupe_key),
    ).fetchone()
    return row is not None


def award_badge(conn: Connection, patient_id: str, badge: str, enrollment_id: str | None) -> bool:
    row = conn.execute(
        """
        INSERT INTO challenge_badges (patient_id, badge, title, enrollment_id) VALUES (%s, %s, %s, %s)
        ON CONFLICT (patient_id, badge) DO NOTHING RETURNING id
        """,
        (patient_id, badge, BADGES[badge], enrollment_id),
    ).fetchone()
    return row is not None


def balance(conn: Connection, patient_id: str) -> int:
    return int(conn.execute("SELECT coalesce(sum(delta), 0) AS n FROM challenge_points WHERE patient_id = %s",
                            (patient_id,)).fetchone()["n"])


def _notify(conn: Connection, patient_id: str, key: str, title: str, body: str) -> bool:
    uid = patient_user(conn, patient_id)
    if not uid:
        return False
    return notify(conn, user_id=uid, kind="challenge", title=title, body=body, link="/challenges",
                  patient_id=patient_id, dedupe_key=key) is not None


def load_enrollment(conn: Connection, enrollment_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text, patient_id::text, definition_id, team_id::text, started_on, ends_on, status,
               periods_met, current_streak, best_streak, completed_at, created_at
        FROM challenge_enrollments WHERE id::text = %s
        """,
        (enrollment_id,),
    ).fetchone()


def sync_enrollment(conn: Connection, enrollment_id: str, today: date) -> dict[str, int]:
    """Points, badges, completion and milestone notifications for one enrollment. Idempotent."""
    e = load_enrollment(conn, enrollment_id)
    counts = {"points": 0, "badges": 0, "notifications": 0, "completed": 0, "ended": 0}
    if e is None or e["status"] not in ("active", "completed"):
        return counts
    d = BY_ID[e["definition_id"]]
    p = progress(conn, e, today)
    pid, eid = e["patient_id"], e["id"]

    for per in p["periods"]:
        if per["met"]:
            key = f"enr:{eid}:{per['start']:%Y-%m-%d}"
            counts["points"] += add_points(conn, pid, d["points_per_period"], f"{d['title']}: target met", key, eid)

    if p["periods_met"] > 0 and award_badge(conn, pid, "first_goal_day", eid):
        counts["badges"] += 1
    if d["period"] == "day":
        for n in MILESTONE_STREAKS:
            if p["best_streak"] >= n and award_badge(conn, pid, f"streak_{n}", eid):
                counts["badges"] += 1
                counts["notifications"] += _notify(conn, pid, f"challenge:{eid}:streak{n}", f"{n}-day streak",
                                                   f"You met your target {n} days in a row. Nice work.")

    halfway = math.ceil(p["required"] / 2)
    if p["required"] > 1 and p["periods_met"] >= halfway and not p["complete"]:
        counts["notifications"] += _notify(conn, pid, f"challenge:{eid}:halfway", "Halfway there",
                                           f"You're halfway through “{d['title']}”.")

    status = e["status"]
    if p["complete"] and status == "active":
        conn.execute(
            "UPDATE challenge_enrollments SET status = 'completed', completed_at = now() WHERE id = %s", (eid,))
        status = "completed"
        counts["completed"] = 1
        audit.record(conn, action="challenge_completed", entity_type="challenge_enrollment", entity_id=eid,
                     agent="challenge-engine", patient_id=pid, detail={"definition": d["id"]})
    if status == "completed":
        counts["points"] += add_points(conn, pid, d["points"], f"Completed: {d['title']}", f"enr:{eid}:complete", eid)
        counts["badges"] += award_badge(conn, pid, f"complete_{d['id']}", eid)
        if e["team_id"]:
            counts["badges"] += award_badge(conn, pid, "family_finish", eid)
        counts["notifications"] += _notify(conn, pid, f"challenge:{eid}:complete", "Challenge complete",
                                           f"You finished “{d['title']}” and earned {d['points']} bonus points.")
    elif p["over"]:
        conn.execute("UPDATE challenge_enrollments SET status = 'ended' WHERE id = %s AND status = 'active'", (eid,))
        counts["ended"] = 1
        counts["notifications"] += _notify(
            conn, pid, f"challenge:{eid}:ended", "Challenge finished",
            f"You met the target {p['periods_met']} of {p['required']} "
            f"{'days' if d['period'] == 'day' else 'weeks'}. Every one of those counts. Start again whenever you like.")

    conn.execute(
        """
        UPDATE challenge_enrollments SET periods_met = %s, current_streak = %s, best_streak = %s, last_synced_at = now()
        WHERE id = %s
        """,
        (p["periods_met"], p["current_streak"], p["best_streak"], eid),
    )
    return counts


def redemption_code() -> str:
    return "DEMO-" + "-".join(secrets.token_hex(2).upper() for _ in range(2))


def clinic_day(now: datetime) -> date:
    return now.astimezone(clinic_tz()).date()
