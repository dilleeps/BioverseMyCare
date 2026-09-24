"""Timeline events from Pharmacy: prescription started, fill ready, picked up."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    return conn.execute(
        """
        WITH ev AS (
            SELECT m.authored_at AS at, 'prescription' AS type,
                   'Prescription started · ' || m.drug_name || ' ' || m.strength AS title,
                   pr.name || ' · ' || m.sig AS detail, 'plan' AS tone, m.id::text AS ref_id
            FROM medication_requests m JOIN practitioners pr ON pr.id = m.prescriber_id
            WHERE m.patient_id = %(p)s

            UNION ALL
            SELECT d.ready_at, 'prescription_filled',
                   'Prescription filled · ' || m.drug_name || ' ' || m.strength,
                   ph.name || CASE WHEN d.fill_number > 1 THEN ' · refill ' || (d.fill_number - 1) ELSE '' END,
                   'neutral', d.id::text
            FROM medication_dispenses d
            JOIN medication_requests m ON m.id = d.medication_request_id
            JOIN pharmacies ph ON ph.id = d.pharmacy_id
            WHERE d.patient_id = %(p)s AND d.ready_at IS NOT NULL

            UNION ALL
            SELECT d.picked_up_at, 'prescription_picked_up',
                   'Picked up · ' || m.drug_name || ' ' || m.strength, ph.name, 'neutral', d.id::text
            FROM medication_dispenses d
            JOIN medication_requests m ON m.id = d.medication_request_id
            JOIN pharmacies ph ON ph.id = d.pharmacy_id
            WHERE d.patient_id = %(p)s AND d.picked_up_at IS NOT NULL
        )
        SELECT * FROM ev
        WHERE %(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
