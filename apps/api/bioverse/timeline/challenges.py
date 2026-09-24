"""Timeline events from Challenges: completed challenges."""

from __future__ import annotations

from bioverse.challenge_engine import BY_ID


def events(conn, patient_id: str, since) -> list[dict]:
    out = []
    for e in conn.execute(
        """
        SELECT id::text, definition_id, completed_at FROM challenge_enrollments
        WHERE patient_id = %s AND status = 'completed' AND completed_at IS NOT NULL
          AND (%s::timestamptz IS NULL OR completed_at >= %s)
        """,
        (patient_id, since, since),
    ).fetchall():
        out.append({"at": e["completed_at"], "type": "challenge", "title": "Challenge completed",
                    "detail": f"{BY_ID[e['definition_id']]['title']} · patient-reported", "tone": "plan",
                    "ref_id": e["id"]})
    return out
