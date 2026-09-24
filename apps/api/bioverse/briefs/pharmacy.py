"""Pre-visit brief lines from Pharmacy: low patient-logged adherence and refill requests awaiting approval."""

from __future__ import annotations

from bioverse.routers.pharmacy import ADHERENCE_TARGET, adherence_for

MIN_TRACKED_DAYS = 3  # too few tracked days says nothing about adherence


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    out: list[dict] = []
    active = conn.execute(
        """
        SELECT id::text, drug_name, strength FROM medication_requests
        WHERE patient_id = %s AND status = 'active' ORDER BY authored_at
        """,
        (patient_id,),
    ).fetchall()
    for rx in active:
        a = adherence_for(conn, rx["id"])
        if not a["tracking"] or a["days_7"] < MIN_TRACKED_DAYS or a["pct_7"] is None:
            continue
        if a["pct_7"] < ADHERENCE_TARGET:
            out.append({
                "text": f"{rx['drug_name']} {rx['strength']}: patient-logged adherence {a['pct_7']}% over the last "
                        f"{a['days_7']} days ({a['taken_7']} of {a['days_7']} days logged).",
                "source": {"type": "medication_request", "id": rx["id"]},
                "flag": "Low medication adherence",
            })

    pending = conn.execute(
        """
        SELECT r.id::text, m.drug_name, m.strength, pr.name AS prescriber, r.prescriber_id::text, r.created_at
        FROM refill_requests r
        JOIN medication_requests m ON m.id = r.medication_request_id
        JOIN practitioners pr ON pr.id = r.prescriber_id
        WHERE r.patient_id = %s AND r.status = 'pending_approval'
        ORDER BY r.created_at
        """,
        (patient_id,),
    ).fetchall()
    for r in pending:
        who = "your approval" if r["prescriber_id"] == practitioner_id else f"approval by {r['prescriber']}"
        out.append({
            "text": f"Refill request for {r['drug_name']} {r['strength']} awaiting {who} "
                    f"(no refills remaining), requested {r['created_at']:%d %b}.",
            "source": {"type": "refill_request", "id": r["id"]},
            "flag": "Refill request pending",
        })
    return out
