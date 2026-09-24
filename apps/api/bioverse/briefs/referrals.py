"""Pre-visit brief lines: referrals that are still waiting (sent) or not yet booked (accepted)."""

from __future__ import annotations

from bioverse.routers import referrals as ref


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    ref.refresh(conn, patient_id=patient_id)
    today = ref.clinic_today(conn)
    rows = conn.execute(
        """
        SELECT sr.id::text, sr.specialty, sr.status, sr.expires_on, sr.sent_at, sr.accepted_at,
               sr.required_documents, sr.provided_documents,
               coalesce(tg.name, sr.specialty) AS target, rq.name AS requester
        FROM service_requests sr
        JOIN practitioners rq ON rq.id = sr.requester_id
        LEFT JOIN practitioners tg ON tg.id = sr.target_practitioner_id
        WHERE sr.patient_id = %s AND sr.status IN ('sent', 'accepted')
        ORDER BY sr.expires_on
        """,
        (patient_id,),
    ).fetchall()
    out = []
    for r in rows:
        days_left = (r["expires_on"] - today).days
        if r["status"] == "sent":
            state = f"sent {r['sent_at']:%d %b} by {r['requester']}, awaiting acceptance"
        else:
            state = f"accepted {r['accepted_at']:%d %b}, not yet booked"
        missing = [d for d in r["required_documents"] if d not in r["provided_documents"]]
        extra = f" Missing: {', '.join(missing)}." if missing else ""
        out.append({
            "text": f"Referral to {r['target']} ({r['specialty']}): {state}; expires {r['expires_on']:%d %b}.{extra}",
            "source": {"type": "service_request", "id": r["id"]},
            "flag": "Referral expiring" if days_left <= ref.EXPIRING_DAYS else "Referral pending",
        })
    return out
