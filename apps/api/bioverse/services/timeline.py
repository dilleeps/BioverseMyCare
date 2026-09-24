"""Longitudinal record queries shared by My Health Story and the clinician workspace."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg import Connection


def age(birth_date: date) -> int:
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def patient_header(conn: Connection, patient_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id::text, name, birth_date, pronouns, preferred_language, insurance_plan, allergies
        FROM patients WHERE id = %s
        """,
        (patient_id,),
    ).fetchone()
    row["age"] = age(row["birth_date"])
    return row


def events(conn: Connection, patient_id: str, since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Every dated event in the record, newest first. `tone` tells the UI how to mark it."""
    rows = conn.execute(
        """
        WITH ev AS (
            SELECT e.occurred_at AS at, 'visit' AS type,
                   e.kind AS title,
                   coalesce(pr.name || ' · ', '') || e.summary AS detail,
                   'visit' AS tone, e.id::text AS ref_id
            FROM encounters e LEFT JOIN practitioners pr ON pr.id = e.practitioner_id
            WHERE e.patient_id = %(p)s

            UNION ALL
            SELECT r.collected_at, 'report',
                   r.name || coalesce(' · ' || (
                       SELECT string_agg(o.display || ' ' || CASE o.interpretation WHEN 'H' THEN 'high' ELSE 'low' END, ', ')
                       FROM observations o WHERE o.report_id = r.id AND o.interpretation <> 'N'
                   ), ''),
                   r.lab_name || CASE WHEN x.status = 'approved' THEN ' · reviewed by ' || coalesce(u.display_name, 'clinician')
                                      WHEN x.status = 'pending_review' THEN ' · awaiting clinician review' ELSE '' END,
                   CASE WHEN EXISTS (SELECT 1 FROM observations o WHERE o.report_id = r.id AND o.interpretation <> 'N')
                        THEN 'alert' ELSE 'neutral' END,
                   r.id::text
            FROM diagnostic_reports r
            LEFT JOIN result_explanations x ON x.report_id = r.id
            LEFT JOIN users u ON u.id = x.reviewed_by
            WHERE r.patient_id = %(p)s

            UNION ALL
            SELECT i.occurred_at, 'immunization', i.vaccine, coalesce(i.location, ''), 'neutral', i.id::text
            FROM immunizations i WHERE i.patient_id = %(p)s

            UNION ALL
            SELECT n.created_at, 'intake', 'Intake · ' || lower(n.chief_complaint),
                   CASE WHEN n.urgency = 'emergency' THEN 'Red flag: ' || array_to_string(n.red_flags, ', ') || ' · advised emergency care'
                        ELSE 'Red-flag screen negative · routed to ' || coalesce(n.specialty, 'care') END,
                   CASE WHEN n.urgency = 'emergency' THEN 'alert' ELSE 'neutral' END,
                   n.id::text
            FROM intakes n WHERE n.patient_id = %(p)s

            UNION ALL
            SELECT c.started_at, 'care_plan', 'Care plan started · ' || c.title, pr.name || ' · ' || pr.specialty,
                   'plan', c.id::text
            FROM care_plans c JOIN practitioners pr ON pr.id = c.practitioner_id
            WHERE c.patient_id = %(p)s

            UNION ALL
            SELECT s.starts_at, 'appointment', 'Upcoming · ' || pr.specialty, pr.name || ' · ' || pr.location_name,
                   'plan', a.id::text
            FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN practitioners pr ON pr.id = a.practitioner_id
            WHERE a.patient_id = %(p)s AND a.status = 'booked'
        )
        SELECT * FROM ev
        WHERE %(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz
        ORDER BY at DESC
        LIMIT %(limit)s
        """,
        {"p": patient_id, "since": since, "limit": limit},
    ).fetchall()
    return rows


def abnormal_trends(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    """For each test whose latest value is out of range, the value history."""
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (loinc_code) loinc_code, display, value, unit, interpretation, ref_low, ref_high, effective_at
            FROM observations WHERE patient_id = %s
            ORDER BY loinc_code, effective_at DESC
        )
        SELECT l.*, (
            SELECT json_agg(json_build_object('value', o.value, 'at', o.effective_at) ORDER BY o.effective_at)
            FROM observations o WHERE o.patient_id = %s AND o.loinc_code = l.loinc_code
        ) AS history
        FROM latest l WHERE l.interpretation <> 'N'
        ORDER BY l.effective_at DESC
        """,
        (patient_id, patient_id),
    ).fetchall()
    return rows
