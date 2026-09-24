"""Timeline events from online consultations: completed consults, booked video or phone consults, and
emergency guidance given during a consult."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    return conn.execute(
        """
        WITH ev AS (
            SELECT c.completed_at AS at, 'consultation' AS type,
                   'Online consult · ' || c.specialty AS title,
                   pr.name || ' · ' || CASE c.mode WHEN 'message' THEN 'secure message' ELSE c.mode END AS detail,
                   'visit' AS tone, c.id::text AS ref_id
            FROM consultations c JOIN practitioners pr ON pr.id = c.practitioner_id
            WHERE c.patient_id = %(p)s AND c.status = 'completed'

            UNION ALL
            SELECT c.scheduled_at, 'consultation', 'Upcoming online consult · ' || c.specialty,
                   pr.name || ' · ' || c.mode || ' call', 'plan', c.id::text
            FROM consultations c JOIN practitioners pr ON pr.id = c.practitioner_id
            WHERE c.patient_id = %(p)s AND c.status = 'accepted' AND c.scheduled_at IS NOT NULL

            UNION ALL
            SELECT m.created_at, 'consultation_red_flag', 'Emergency guidance given in an online consult',
                   coalesce(c.flag_reason, 'Red flag'), 'alert', c.id::text
            FROM consultation_messages m JOIN consultations c ON c.id = m.consultation_id
            WHERE m.patient_id = %(p)s AND m.author_kind = 'system' AND m.payload ->> 'kind' = 'emergency'
        )
        SELECT * FROM ev
        WHERE %(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
