"""Timeline events from Mood & anxiety: each completed PHQ-9 and GAD-7."""

from __future__ import annotations

from bioverse.mind_instruments import INSTRUMENTS, band


def events(conn, patient_id: str, since) -> list[dict]:
    out = []
    for r in conn.execute(
        """
        SELECT id::text, instrument, total, crisis, created_at FROM mind_questionnaire_responses
        WHERE patient_id = %s AND (%s::timestamptz IS NULL OR created_at >= %s) ORDER BY created_at
        """,
        (patient_id, since, since),
    ).fetchall():
        spec = INSTRUMENTS[r["instrument"]]
        _, label = band(r["instrument"], r["total"])
        out.append({"at": r["created_at"], "type": "questionnaire", "title": f"{spec['name']} completed",
                    "detail": f"Score {r['total']} of {spec['max']} · {label.lower()} · patient-reported",
                    "tone": "alert" if r["crisis"] or r["total"] >= 10 else "neutral", "ref_id": r["id"]})
    return out
