"""Timeline events from home vitals: abnormal-reading alerts, their acknowledgement, and monitoring plans."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    return conn.execute(
        """
        WITH ev AS (
            SELECT a.created_at AS at, 'vital_alert' AS type, 'Home reading alert · ' || a.title AS title,
                   CASE WHEN a.status = 'acknowledged'
                        THEN 'Reviewed by ' || coalesce(u.display_name, 'the care team')
                        ELSE 'Care team notified' END AS detail,
                   'alert' AS tone, a.id::text AS ref_id
            FROM vital_alerts a LEFT JOIN users u ON u.id = a.acknowledged_by
            WHERE a.patient_id = %(p)s

            UNION ALL
            SELECT v.created_at, 'vital_plan',
                   'Home monitoring · ' || CASE v.measure WHEN 'bp' THEN 'blood pressure' WHEN 'heart_rate' THEN 'heart rate'
                       WHEN 'spo2' THEN 'oxygen saturation' WHEN 'glucose' THEN 'blood glucose' ELSE v.measure END,
                   pr.name || ' · ' || cardinality(v.times) || ' a day, ' || to_char(v.start_on, 'DD Mon') || ' to '
                   || to_char(v.end_on, 'DD Mon') || CASE v.status WHEN 'stopped' THEN ' · stopped' ELSE '' END,
                   'plan', v.id::text
            FROM vital_monitoring_plans v JOIN practitioners pr ON pr.id = v.practitioner_id
            WHERE v.patient_id = %(p)s
        )
        SELECT * FROM ev
        WHERE %(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
