"""Timeline events for referrals: sent, accepted and completed."""

from __future__ import annotations

TITLES = {"sent": "Referral sent", "accepted": "Referral accepted", "completed": "Referral completed"}
TONES = {"sent": "plan", "accepted": "plan", "completed": "visit"}


def events(conn, patient_id: str, since) -> list[dict]:
    rows = conn.execute(
        """
        SELECT h.id::text, h.occurred_at, h.to_status, sr.specialty,
               coalesce(tg.name, sr.specialty) AS target, rq.name AS requester
        FROM service_request_history h
        JOIN service_requests sr ON sr.id = h.service_request_id
        JOIN practitioners rq ON rq.id = sr.requester_id
        LEFT JOIN practitioners tg ON tg.id = sr.target_practitioner_id
        WHERE h.patient_id = %(p)s AND h.to_status IN ('sent', 'accepted', 'completed')
          AND (%(since)s::timestamptz IS NULL OR h.occurred_at >= %(since)s::timestamptz)
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
    return [
        {
            "at": r["occurred_at"],
            "type": "referral",
            "title": f"{TITLES[r['to_status']]} · {r['specialty']}",
            "detail": f"{r['requester']} to {r['target']}" if r["to_status"] == "sent" else r["target"],
            "tone": TONES[r["to_status"]],
            "ref_id": r["id"],
        }
        for r in rows
    ]
