"""Timeline events from Nutrition & weight: weight goals set, reached or stopped."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    out = []
    for g in conn.execute(
        """
        SELECT id::text, start_weight_kg, target_weight_kg, pace_kg_week, status, created_at, ended_at
        FROM weight_goals WHERE patient_id = %s
        """,
        (patient_id,),
    ).fetchall():
        out.append({"at": g["created_at"], "type": "weight_goal", "title": "Weight goal set",
                    "detail": f"{float(g['start_weight_kg']):.1f} kg to {float(g['target_weight_kg']):.1f} kg, "
                              f"{float(g['pace_kg_week']):g} kg a week · patient-set",
                    "tone": "plan", "ref_id": g["id"]})
        if g["ended_at"] and g["status"] in ("achieved", "stopped"):
            out.append({"at": g["ended_at"], "type": "weight_goal_end",
                        "title": "Weight goal reached" if g["status"] == "achieved" else "Weight goal stopped",
                        "detail": "Patient-reported", "tone": "plan", "ref_id": f"{g['id']}-end"})
    if since is not None:
        out = [e for e in out if e["at"] >= since]
    return out
