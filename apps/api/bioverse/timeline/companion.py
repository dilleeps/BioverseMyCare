"""Timeline events from the health companion: answered check-ins and escalations to the care team."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    return conn.execute(
        """
        WITH ev AS (
            SELECT c.answered_at AS at, 'companion_checkin' AS type,
                   'Check-in · feeling ' || CASE c.response WHEN 'same' THEN 'about the same' ELSE c.response END AS title,
                   CASE c.kind WHEN 'post_visit' THEN 'After ' || c.subject ELSE 'New medicine · ' || c.subject END AS detail,
                   CASE WHEN c.response = 'worse' THEN 'alert' ELSE 'neutral' END AS tone,
                   c.id::text AS ref_id
            FROM companion_checkins c
            WHERE c.patient_id = %(p)s AND c.status = 'answered'

            UNION ALL
            SELECT c.answered_at, 'companion_escalation',
                   CASE c.escalation WHEN 'urgent' THEN 'Check-in red flag · care team alerted'
                                     ELSE 'Check-in shared with care team' END,
                   coalesce(c.escalation_reason, ''), 'alert', c.id::text
            FROM companion_checkins c
            WHERE c.patient_id = %(p)s AND c.escalation IS NOT NULL
        )
        SELECT * FROM ev
        WHERE at IS NOT NULL AND (%(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz)
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
