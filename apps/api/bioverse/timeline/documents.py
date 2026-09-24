"""Timeline events: lab reports the patient uploaded, and results that arrived by HL7 lab feed."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.created_at AS at, 'document' AS type,
               'Lab report uploaded · patient-reported' AS title,
               coalesce(d.filename, 'Pasted text') || ' · ' ||
               CASE WHEN d.status = 'extracted' THEN 'not saved yet: values waiting to be checked'
                    WHEN x.status = 'approved' THEN 'saved and reviewed by ' || coalesce(u.display_name, 'clinician')
                    WHEN x.status = 'rejected' THEN 'saved · your clinician will discuss it with you'
                    ELSE 'saved · awaiting clinician review' END AS detail,
               'neutral' AS tone, d.id::text AS ref_id
        FROM document_references d
        LEFT JOIN result_explanations x ON x.report_id = d.report_id
        LEFT JOIN users u ON u.id = x.reviewed_by
        WHERE d.patient_id = %(p)s AND d.status IN ('extracted', 'confirmed')
          AND (%(since)s::timestamptz IS NULL OR d.created_at >= %(since)s::timestamptz)

        UNION ALL
        SELECT m.received_at, 'lab_import',
               'Results received from the lab · ' || r.name,
               coalesce(m.sending_facility, r.lab_name) || ' · electronic lab feed',
               'neutral', r.id::text
        FROM hl7_inbound_messages m JOIN diagnostic_reports r ON r.id = m.report_id
        WHERE m.patient_id = %(p)s AND m.outcome = 'accepted'
          AND (%(since)s::timestamptz IS NULL OR m.received_at >= %(since)s::timestamptz)
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
    return [dict(r) for r in rows]
