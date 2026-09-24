"""Pre-visit brief lines from Mood & anxiety: latest PHQ-9 and GAD-7 with the change, and any crisis flag."""

from __future__ import annotations

from bioverse.config import clinic_tz
from bioverse.mind_instruments import INSTRUMENTS, band


def _d(ts) -> str:
    return f"{ts.astimezone(clinic_tz()):%d %b}"


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    out: list[dict] = []
    for key, spec in INSTRUMENTS.items():
        rows = conn.execute(
            """
            SELECT id::text, total, item9, crisis, created_at FROM mind_questionnaire_responses
            WHERE patient_id = %s AND instrument = %s ORDER BY created_at DESC LIMIT 2
            """,
            (patient_id, key),
        ).fetchall()
        if not rows:
            continue
        latest = rows[0]
        _, label = band(key, latest["total"])
        change = f" (previous {rows[1]['total']} on {_d(rows[1]['created_at'])})" if len(rows) > 1 else ""
        flag = None
        text = f"{spec['title']} {latest['total']}/{spec['max']}, {label.lower()}, {_d(latest['created_at'])}{change}."
        if latest["crisis"]:
            text += f" Item 9 scored {latest['item9']}: crisis support shown, urgent review raised."
            flag = "PHQ-9 item 9 positive"
        elif latest["total"] >= 10:
            flag = f"{spec['title']} {label.lower()}"
        out.append({"text": text, "source": {"type": "questionnaire_response", "id": latest["id"]}, "flag": flag})
    return out
