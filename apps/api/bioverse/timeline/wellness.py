"""Timeline events from Wellness: goals set, streak milestones, lifestyle check-ins. All patient-reported.

Completed screenings and vaccines already appear through the core timeline (reports, immunizations).
"""

from __future__ import annotations

from datetime import datetime, time, timezone


def _num(v) -> str:
    f = float(v)
    return f"{int(f):,}" if f.is_integer() else f"{f:g}"


def events(conn, patient_id: str, since) -> list[dict]:
    from bioverse.routers.wellness import milestones

    out: list[dict] = []
    goals = conn.execute(
        "SELECT id::text, title, unit, target, created_at FROM wellness_goals WHERE patient_id = %s", (patient_id,)
    ).fetchall()
    for g in goals:
        out.append({"at": g["created_at"], "type": "goal", "title": f"Goal set · {g['title'].lower()}",
                    "detail": f"{_num(g['target'])} {g['unit']} a day · patient-reported", "tone": "plan",
                    "ref_id": g["id"]})
        rows = conn.execute("SELECT day, value FROM wellness_goal_entries WHERE goal_id = %s", (g["id"],)).fetchall()
        entries = {r["day"]: float(r["value"]) for r in rows}
        for m in milestones(float(g["target"]), entries):
            out.append({
                "at": datetime.combine(m["day"], time(12), tzinfo=timezone.utc),
                "type": "goal_milestone",
                "title": f"{m['streak']}-day streak · {g['title'].lower()}",
                "detail": f"Met {_num(g['target'])} {g['unit']} {m['streak']} days in a row · patient-reported",
                "tone": "plan",
                "ref_id": f"{g['id']}-{m['day']:%Y%m%d}",
            })
    for a in conn.execute(
        """
        SELECT id::text, created_at, suggestions FROM wellness_assessments
        WHERE patient_id = %s AND red_flag_level NOT IN ('emergency', 'crisis')
        """,
        (patient_id,),
    ).fetchall():
        n = len(a["suggestions"] or [])
        out.append({"at": a["created_at"], "type": "assessment", "title": "Lifestyle check-in completed",
                    "detail": f"{n} suggestion{'s' if n != 1 else ''} · patient-reported", "tone": "neutral",
                    "ref_id": a["id"]})
    if since is not None:
        out = [e for e in out if e["at"] >= since]
    return out
