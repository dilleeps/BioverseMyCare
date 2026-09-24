"""Pre-visit brief lines from Nutrition & weight: weekly sodium pattern, weight trend and BMI, eating screen."""

from __future__ import annotations

from datetime import timedelta

from bioverse.config import clinic_today, clinic_tz


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    from bioverse.routers.nutrition import weekly_patterns
    from bioverse.routers.weight import _bmi, latest_height, weigh_ins

    out: list[dict] = []
    week = weekly_patterns(conn, patient_id, clinic_today() - timedelta(days=1))
    for p in week["patterns"]:
        if p["nutrient"] in ("sodium_mg", "sugar_g"):
            out.append({"text": f"Food log (patient-reported): {p['text']}",
                        "source": {"type": "nutrition_log", "id": patient_id},
                        "flag": "Sodium over target most days" if p["nutrient"] == "sodium_mg" else None})

    points = weigh_ins(conn, patient_id)
    if points:
        latest = points[-1]
        height = latest_height(conn, patient_id)
        month_ago = [p for p in points if p["effective_at"] <= latest["effective_at"] - timedelta(days=21)]
        trend = ""
        if month_ago:
            change = latest["value"] - month_ago[-1]["value"]
            days = (latest["effective_at"] - month_ago[-1]["effective_at"]).days
            trend = f", {change:+.1f} kg over {days} days"
        bmi = f", BMI {_bmi(latest['value'], height['value'])}" if height else ""
        goal = conn.execute(
            "SELECT target_weight_kg, pace_kg_week FROM weight_goals WHERE patient_id = %s AND status = 'active'",
            (patient_id,),
        ).fetchone()
        goal_text = (f"; weight-loss goal {float(goal['target_weight_kg']):.1f} kg at {float(goal['pace_kg_week']):g} kg/week"
                     if goal else "")
        out.append({"text": f"Weight {latest['value']:.1f} kg ({latest['effective_at'].astimezone(clinic_tz()):%d %b}, {latest['source']}){trend}{bmi}{goal_text}.",
                    "source": {"type": "observation", "id": latest["id"]}, "flag": None})

    for s in conn.execute(
        """
        SELECT s.id::text, s.score, s.created_at FROM weight_screenings s JOIN review_items r ON r.id = s.review_item_id
        WHERE s.patient_id = %s AND s.positive AND s.cleared_at IS NULL AND r.status = 'open'
        """,
        (patient_id,),
    ).fetchall():
        out.append({"text": f"Eating screen (SCOFF) {s['score']}/5 on {s['created_at'].astimezone(clinic_tz()):%d %b}; weight coaching paused for review.",
                    "source": {"type": "weight_screening", "id": s["id"]}, "flag": "Eating screen positive"})
    return out
