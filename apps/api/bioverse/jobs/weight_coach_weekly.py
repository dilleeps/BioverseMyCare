"""Weekly weight check-in: summarize last week for every active goal and let the patient know. Idempotent."""

from __future__ import annotations

from datetime import timedelta

from bioverse import audit
from bioverse.challenge_engine import clinic_day
from bioverse.jobs import job
from bioverse.notify import notify, patient_user


@job("weight_coach_weekly", every_minutes=24 * 60, description="Write each weight goal's weekly check-in and notify")
def run(conn, now):
    from bioverse.routers.weight import _goal, monday, week_summary, weigh_ins

    today = clinic_day(now)
    week_start = monday(today) - timedelta(days=7)          # the last complete week, Monday to Sunday
    created = achieved = 0
    goals = conn.execute(
        "SELECT id::text, patient_id::text FROM weight_goals WHERE status = 'active' AND created_at::date <= %s",
        (week_start + timedelta(days=6),),
    ).fetchall()
    for g in goals:
        goal = _goal(conn, g["patient_id"])
        summary = week_summary(weigh_ins(conn, g["patient_id"]), goal, week_start)
        row = conn.execute(
            """
            INSERT INTO weight_checkins (patient_id, goal_id, week_start, weekly_avg_kg, change_kg, percent_to_goal, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (goal_id, week_start) DO NOTHING RETURNING id::text
            """,
            (g["patient_id"], g["id"], week_start, summary["weekly_avg_kg"], summary["change_kg"],
             summary["percent_to_goal"], summary["message"]),
        ).fetchone()
        if row is None:
            continue
        created += 1
        uid = patient_user(conn, g["patient_id"])
        if uid:
            notify(conn, user_id=uid, kind="weight_coach", title="Your weekly weight check-in",
                   body="Your summary for last week is ready.", link="/weight", patient_id=g["patient_id"],
                   dedupe_key=f"weight_coach:{g['id']}:{week_start}")
        if summary["weekly_avg_kg"] is not None and summary["weekly_avg_kg"] <= goal["target_weight_kg"]:
            conn.execute("UPDATE weight_goals SET status = 'achieved', ended_at = now() WHERE id = %s", (g["id"],))
            achieved += 1
        audit.record(conn, action="weight_checkin_created", entity_type="weight_goal", entity_id=g["id"],
                     agent="weight-coach/rules", patient_id=g["patient_id"], detail={"week_start": week_start})
    return {"goals": len(goals), "checkins": created, "achieved": achieved}
