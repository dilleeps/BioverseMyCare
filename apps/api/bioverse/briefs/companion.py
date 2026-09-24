"""Pre-visit brief lines from the health companion: doses taken between visits, check-in answers, escalations.

Example lines: "Amlodipine 5 mg: took 6 of 7 scheduled doses in the last 7 days (1 not recorded)."
"Reported feeling worse on day 2 of Atorvastatin 20 mg: \"muscle aches\"."
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bioverse import companion

MIN_EXPECTED = 3   # fewer scheduled doses than this says nothing about adherence
CHECKIN_DAYS = 14


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    tz = companion.patient_tz(conn, patient_id)
    out: list[dict] = []

    adh = companion.adherence(conn, patient_id, now, tz=tz)
    for m in adh["medications"]:
        if not m.get("tracking") or m["last_7"]["expected"] < MIN_EXPECTED:
            continue
        w = m["last_7"]
        not_taken = []
        if w["skipped"]:
            not_taken.append(f"{w['skipped']} skipped")
        if w["missed"]:
            not_taken.append(f"{w['missed']} not recorded")
        detail = f" ({', '.join(not_taken)})" if not_taken else ""
        low = w["pct"] is not None and w["pct"] < companion.ADHERENCE_TARGET
        out.append({
            "text": f"{m['medication']}: took {w['taken']} of {w['expected']} scheduled doses in the last 7 days"
                    f"{detail}, from the patient's companion log.",
            "source": {"type": "medication_request", "id": m["rx_id"]},
            "flag": "Missed doses" if low else None,
        })

    for c in companion.recent_checkins(conn, patient_id, now - timedelta(days=CHECKIN_DAYS)):
        if c["status"] != "answered":
            continue
        text = companion.checkin_sentence(c, tz)
        if c["note"]:
            text += f': "{c["note"]}"'
        flag = None
        if c["escalation"] == "urgent":
            text += " Red flag raised; patient shown emergency guidance."
            flag = "Red flag in check-in" if c["review_status"] == "open" else None
        elif c["escalation"] and c["review_status"] == "open":
            flag = "Check-in needs review"
        out.append({"text": text + ("" if text.endswith(".") else "."),
                    "source": {"type": "companion_checkin", "id": c["id"]}, "flag": flag})
    return out
