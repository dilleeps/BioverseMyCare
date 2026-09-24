"""Pre-visit brief lines from messaging and the Doctor Agent.

- Pre-visit interview answers for this clinician's next (or most recent) appointment, one line per answer.
- "Patient reported new symptoms" when an answer mentions a symptom (rules or red-flag screen).
- Open red-flag message threads, and message threads still waiting for this clinician.
"""

from __future__ import annotations

from bioverse.agents.message_triage import CATEGORY_LABELS


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    out: list[dict] = []

    appt = conn.execute(
        """
        SELECT q.appointment_id FROM questionnaire_responses q
        JOIN appointments a ON a.id = q.appointment_id JOIN slots s ON s.id = a.slot_id
        WHERE q.patient_id = %s AND q.practitioner_id = %s AND a.status <> 'cancelled'
        ORDER BY (s.starts_at > now()) DESC, abs(extract(epoch FROM s.starts_at - now())) LIMIT 1
        """,
        (patient_id, practitioner_id),
    ).fetchone()
    if appt:
        answers = conn.execute(
            """
            SELECT id::text, question_text, answer_text, mentions_symptoms, created_at
            FROM questionnaire_responses WHERE appointment_id = %s ORDER BY created_at
            """,
            (appt["appointment_id"],),
        ).fetchall()
        for a in answers:
            out.append({
                "text": f"Pre-visit answers ({a['created_at']:%d %b}): {a['question_text']} Patient: \"{a['answer_text']}\"",
                "source": {"type": "questionnaire_response", "id": a["id"]},
                "flag": "Patient reported new symptoms" if a["mentions_symptoms"] else None,
            })

    for t in conn.execute(
        """
        SELECT id::text, subject, flag_reason, category, awaiting_since, flagged, flag_acknowledged_at
        FROM communication_threads
        WHERE patient_id = %s AND practitioner_id = %s AND status = 'open'
          AND ((flagged AND flag_acknowledged_at IS NULL) OR (awaiting_since IS NOT NULL AND assigned_to = 'clinician'))
        ORDER BY flagged DESC, awaiting_since
        """,
        (patient_id, practitioner_id),
    ).fetchall():
        if t["flagged"] and t["flag_acknowledged_at"] is None:
            out.append({
                "text": f"Message thread \"{t['subject']}\": red flag ({t['flag_reason']}); patient was shown emergency guidance.",
                "source": {"type": "communication_thread", "id": t["id"]},
                "flag": "Red flag in messages",
            })
        else:
            label = CATEGORY_LABELS.get(t["category"] or "", "Message").lower()
            out.append({
                "text": f"Unanswered message ({label}) since {t['awaiting_since']:%d %b}: \"{t['subject']}\".",
                "source": {"type": "communication_thread", "id": t["id"]},
                "flag": None,
            })
    return out
