"""Pre-visit brief lines from online consultations: open and upcoming consults, a recent consult summary,
and any red flag raised during a consult."""

from __future__ import annotations

from bioverse.config import clinic_tz

RECENT_DAYS = 90
MODE = {"message": "message", "video": "video", "phone": "phone"}
STATE = {"requested": "requested", "accepted": "booked", "in_progress": "in progress"}


def _when(ts) -> str:
    return f"{ts.astimezone(clinic_tz()):%d %b}"


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    out: list[dict] = []
    rows = conn.execute(
        """
        SELECT c.id::text, c.status, c.mode, c.specialty, c.scheduled_at, c.created_at, c.completed_at, c.summary,
               c.flagged, c.flag_reason, c.practitioner_id::text, pr.name
        FROM consultations c LEFT JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s
          AND (c.status IN ('requested', 'accepted', 'in_progress')
               OR (c.status = 'completed' AND c.completed_at > now() - make_interval(days => %s))
               OR c.flagged)
        ORDER BY coalesce(c.completed_at, c.scheduled_at, c.created_at) DESC
        """,
        (patient_id, RECENT_DAYS),
    ).fetchall()
    for c in rows:
        who = "you" if c["practitioner_id"] == practitioner_id else (c["name"] or f"first available in {c['specialty']}")
        src = {"type": "consultation", "id": c["id"]}
        if c["flagged"]:
            out.append({"text": f"Red flag raised in an online consult ({c['specialty']}): {c['flag_reason']}. "
                                "The patient was shown emergency guidance.",
                        "source": src, "flag": "Red flag in online consult"})
        if c["status"] in STATE:
            when = f" on {_when(c['scheduled_at'])}" if c["scheduled_at"] else ""
            out.append({"text": f"Online {MODE[c['mode']]} consult in {c['specialty']} with {who}{when}: "
                                f"{STATE[c['status']]}.", "source": src, "flag": None})
        elif c["status"] == "completed" and c["summary"]:
            summary = c["summary"] if len(c["summary"]) <= 180 else c["summary"][:177].rstrip() + "..."
            out.append({"text": f"Online consult, {c['specialty']}, {_when(c['completed_at'])} with {who}: {summary}",
                        "source": src, "flag": None})
    return out
