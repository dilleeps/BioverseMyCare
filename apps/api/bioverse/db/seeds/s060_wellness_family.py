"""Wellness, family and caregivers demo data (IDs 6000-6999). Idempotent. All people are fictional.

- Eleanor Thornton (81), Maya's mother, with appointments, a care plan with medicines, one reviewed
  result and one result still awaiting clinician review. Eleanor made Maya her full proxy.
- David Thornton, Maya's spouse: a normal patient, and Maya's caregiver with view_appointments and
  view_care_plan. In the demo switcher as "Caregiver".
- Maya's steps goal with two weeks of patient-reported entries, and emergency contacts.
"""

from __future__ import annotations

import json

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import DR_LINDQVIST, DR_MORI, ORG, P_HADDAD, P_MAYA, P_PARK, PLAN, U_MAYA, _id

U_ELEANOR, P_ELEANOR = _id(6001), _id(6002)
U_DAVID, P_DAVID = _id(6003), _id(6004)

ELEANOR_PLAN = _id(6010)
ELEANOR_SLOT_1, ELEANOR_SLOT_2 = _id(6020), _id(6021)
ELEANOR_APPT_1, ELEANOR_APPT_2 = _id(6022), _id(6023)
ELEANOR_KIDNEY, ELEANOR_VITD = _id(6030), _id(6031)
ELEANOR_VITD_REVIEW = _id(6032)
MAYA_STEPS_GOAL = _id(6100)

ALL_PERMISSIONS = ["view_appointments", "book_appointments", "view_care_plan", "view_results",
                   "view_medications", "message_care_team"]


def run(conn, ctx: SeedContext) -> None:
    days = ctx.days

    # Sex at birth for existing demo patients (drives sex-specific screenings). Never overwrite a real value.
    for pid, sex in ((P_MAYA, "female"), (P_PARK, "male"), (P_HADDAD, "female")):
        conn.execute("UPDATE patients SET sex_at_birth = %s WHERE id = %s AND sex_at_birth IS NULL", (sex, pid))

    conn.execute(
        """
        INSERT INTO users (id, role, display_name, email, organization_id, demo_label, demo_order)
        VALUES (%s, 'patient', 'Eleanor Thornton', 'eleanor@example.com', %s, NULL, 100),
               (%s, 'patient', 'David Thornton', 'david@example.com', %s, 'Caregiver', 15)
        ON CONFLICT (id) DO NOTHING
        """,
        (U_ELEANOR, ORG, U_DAVID, ORG),
    )
    conn.execute("UPDATE users SET demo_label = 'Caregiver', demo_order = 15 WHERE id = %s", (U_DAVID,))

    inserted = conn.execute(
        """
        INSERT INTO patients (id, user_id, organization_id, name, birth_date, pronouns, preferred_language,
                              insurance_plan, allergies, sex_at_birth)
        VALUES (%s, %s, %s, 'Eleanor Thornton', %s, 'she/her', 'English', %s, '{}', 'female'),
               (%s, %s, %s, 'David Thornton', %s, 'he/him', 'English', %s, '{}', 'male')
        ON CONFLICT (id) DO NOTHING
        RETURNING id::text
        """,
        (P_ELEANOR, U_ELEANOR, ORG, days(-81 * 365 - 90), PLAN, P_DAVID, U_DAVID, ORG, days(-56 * 365 - 40), PLAN),
    ).fetchall()
    first_run = any(r[0] == P_ELEANOR for r in inserted)

    _relationships(conn)
    if first_run:
        _eleanor_record(conn, ctx)
        _consents(conn)
    _maya_wellness(conn, ctx)
    _contacts(conn)


def _relationships(conn) -> None:
    conn.execute(
        """
        INSERT INTO related_persons (id, patient_id, user_id, relationship, created_by) VALUES
            (%s, %s, %s, 'child', %s),
            (%s, %s, %s, 'spouse', %s)
        ON CONFLICT DO NOTHING
        """,
        (_id(6040), P_ELEANOR, U_MAYA, U_ELEANOR, _id(6041), P_MAYA, U_DAVID, U_MAYA),
    )


def _consents(conn) -> None:
    rows = [
        # Eleanor made her daughter Maya her full proxy.
        (_id(6050), P_ELEANOR, U_MAYA, {"permissions": ALL_PERMISSIONS, "proxy": True, "relationship": "child"}, U_ELEANOR),
        # Maya lets her spouse David see her appointments and care plan.
        (_id(6051), P_MAYA, U_DAVID, {"permissions": ["view_appointments", "view_care_plan"], "proxy": False,
                                      "relationship": "spouse"}, U_MAYA),
    ]
    for cid, patient, grantee, detail, by in rows:
        new = conn.execute(
            """
            INSERT INTO consents (id, patient_id, scope, grantee, status, detail, updated_by)
            VALUES (%s, %s, 'caregiver_access', %s, 'granted', %s, %s)
            ON CONFLICT DO NOTHING RETURNING id::text
            """,
            (cid, patient, grantee, json.dumps(detail), by),
        ).fetchone()
        if new:
            conn.execute(
                """
                INSERT INTO audit_events (actor_user_id, actor_role, agent, action, entity_type, entity_id, patient_id, detail)
                VALUES (%s, 'patient', 'seed', 'consent_granted', 'consent', %s, %s, %s)
                """,
                (by, cid, patient, json.dumps({"scope": "caregiver_access", "grantee": grantee})),
            )


def _eleanor_record(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    conn.execute(
        """
        INSERT INTO encounters (id, patient_id, practitioner_id, occurred_at, kind, summary) VALUES
            (%s, %s, %s, %s, 'Annual review', 'BP 136/82. Walking daily with a stick. Kidney function and vitamin D ordered.')
        ON CONFLICT DO NOTHING
        """,
        (_id(6060), P_ELEANOR, DR_LINDQVIST, at(days(-60), 10, 30)),
    )
    conn.execute(
        """
        INSERT INTO immunizations (id, patient_id, vaccine, location, occurred_at) VALUES
            (%s, %s, 'Influenza vaccine', 'Northside Clinic', %s),
            (%s, %s, 'Pneumococcal conjugate vaccine (PCV20)', 'Northside Clinic', %s)
        ON CONFLICT DO NOTHING
        """,
        (_id(6061), P_ELEANOR, at(days(-300), 11), _id(6062), P_ELEANOR, at(days(-700), 11)),
    )

    # Two upcoming appointments on their own slots (odd minutes, so they never clash with core slots).
    conn.execute(
        """
        INSERT INTO slots (id, practitioner_id, starts_at, mode, status) VALUES
            (%s, %s, %s, 'in_person', 'booked'),
            (%s, %s, %s, 'in_person', 'booked')
        ON CONFLICT DO NOTHING
        """,
        (ELEANOR_SLOT_1, DR_LINDQVIST, at(days(6), 15, 10), ELEANOR_SLOT_2, DR_MORI, at(days(13), 11, 50)),
    )
    conn.execute(
        """
        INSERT INTO appointments (id, patient_id, practitioner_id, slot_id, reason) VALUES
            (%s, %s, %s, %s, 'Blood pressure review'),
            (%s, %s, %s, %s, 'Vitamin D follow-up')
        ON CONFLICT DO NOTHING
        """,
        (ELEANOR_APPT_1, P_ELEANOR, DR_LINDQVIST, ELEANOR_SLOT_1, ELEANOR_APPT_2, P_ELEANOR, DR_MORI, ELEANOR_SLOT_2),
    )

    conn.execute(
        """
        INSERT INTO care_plans (id, patient_id, practitioner_id, title, started_at)
        VALUES (%s, %s, %s, 'Blood pressure and bone health', %s) ON CONFLICT DO NOTHING
        """,
        (ELEANOR_PLAN, P_ELEANOR, DR_LINDQVIST, at(days(-60), 11)),
    )
    tasks = [
        (_id(6011), 1, "lab", "Kidney function blood test", "Northside Lab", None, days(-58), "done"),
        # Ongoing daily medicines: no due date, so they never read as overdue.
        (_id(6012), 2, "medication", "Take amlodipine 5 mg, once daily", "In the morning, with water", None, None, "todo"),
        (_id(6013), 3, "medication", "Vitamin D 1,000 IU, once daily", "With a meal", None, None, "todo"),
        (_id(6014), 4, "appointment", "Blood pressure review", "Booked for next week", "Primary care", days(6), "todo"),
        (_id(6015), 5, "lifestyle", "Short walk most days", "10 to 20 minutes, with the stick", None, None, "todo"),
    ]
    conn.cursor().executemany(
        """
        INSERT INTO care_plan_tasks (id, care_plan_id, position, kind, title, detail, specialty, due_on, status, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(t[0], ELEANOR_PLAN, *t[1:], at(days(-58), 9) if t[7] == "done" else None) for t in tasks],
    )

    # Kidney function: reviewed and approved. Vitamin D: explanation drafted, still awaiting review.
    conn.execute(
        """
        INSERT INTO diagnostic_reports (id, patient_id, name, lab_name, collected_at, responsible_practitioner_id) VALUES
            (%s, %s, 'Kidney function', 'Northside Lab', %s, %s),
            (%s, %s, 'Vitamin D', 'Northside Lab', %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (ELEANOR_KIDNEY, P_ELEANOR, at(days(-58), 8, 15), DR_LINDQVIST,
         ELEANOR_VITD, P_ELEANOR, at(days(-3), 8, 30), DR_LINDQVIST),
    )
    conn.cursor().executemany(
        """
        INSERT INTO observations (id, patient_id, report_id, loinc_code, display, value, unit, ref_low, ref_high,
                                  interpretation, effective_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (_id(6033), P_ELEANOR, ELEANOR_KIDNEY, "33914-3", "eGFR", 68, "mL/min/1.73m2", 60, None, "N", at(days(-58), 8, 15)),
            (_id(6034), P_ELEANOR, ELEANOR_KIDNEY, "2160-0", "Creatinine", 0.9, "mg/dL", 0.6, 1.1, "N", at(days(-58), 8, 15)),
            (_id(6035), P_ELEANOR, ELEANOR_VITD, "1989-3", "25-hydroxy vitamin D", 22, "ng/mL", 30, 100, "L", at(days(-3), 8, 30)),
        ],
    )
    kidney_text = ("Your kidney function results are within the expected range for your age. "
                   "Dr. Lindqvist will keep checking them once a year while you take your blood pressure medicine.")
    conn.execute(
        """
        INSERT INTO result_explanations (id, report_id, draft_text, final_text, status, produced_by, reviewed_at)
        VALUES (%s, %s, %s, %s, 'approved', 'results-agent/rules', %s) ON CONFLICT DO NOTHING
        """,
        (_id(6036), ELEANOR_KIDNEY, kidney_text, kidney_text, at(days(-57), 12)),
    )
    draft = ("DRAFT: Your vitamin D is below the reference range. Low vitamin D is common, especially in winter. "
             "Your doctor will talk with you about whether to change your supplement.")
    conn.execute(
        """
        INSERT INTO result_explanations (id, report_id, draft_text, questions, status, produced_by)
        VALUES (%s, %s, %s, %s, 'pending_review', 'results-agent/rules') ON CONFLICT DO NOTHING
        """,
        (ELEANOR_VITD_REVIEW, ELEANOR_VITD, draft, json.dumps(["Should my supplement dose change?"])),
    )
    conn.execute(
        """
        INSERT INTO review_items (id, kind, patient_id, practitioner_id, ref_id, title, body, priority)
        VALUES (%s, 'result_explanation', %s, %s, %s, 'Result explanation · Vitamin D 22 ng/mL', %s, 'routine')
        ON CONFLICT DO NOTHING
        """,
        (_id(6037), P_ELEANOR, DR_LINDQVIST, ELEANOR_VITD_REVIEW, draft),
    )


def _maya_wellness(conn, ctx: SeedContext) -> None:
    new = conn.execute(
        """
        INSERT INTO wellness_goals (id, patient_id, kind, title, unit, target, created_at)
        VALUES (%s, %s, 'steps', 'Daily steps', 'steps', 7000, %s) ON CONFLICT DO NOTHING RETURNING id
        """,
        (MAYA_STEPS_GOAL, P_MAYA, ctx.at(ctx.days(-16), 19)),
    ).fetchone()
    if not new:
        return  # entries are relative to the day the goal was first seeded; don't add more on reseed
    # Oldest first, ending yesterday. A 7-day run gives a milestone; today is left for the patient to log.
    values = [5200, 6100, 7400, 7900, 7100, 8200, 7050, 9100, 7600, 4300, 7200, 8800, 7300, 6900, 7700]
    conn.cursor().executemany(
        """
        INSERT INTO wellness_goal_entries (id, goal_id, patient_id, day, value) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        [(_id(6101 + i), MAYA_STEPS_GOAL, P_MAYA, ctx.days(-len(values) + i), v) for i, v in enumerate(values)],
    )


def _contacts(conn) -> None:
    conn.execute(
        """
        INSERT INTO emergency_contacts (id, patient_id, name, relationship, phone, notes) VALUES
            (%s, %s, 'David Thornton', 'Spouse', '555-0142', 'Usually reachable after 5 pm'),
            (%s, %s, 'Maya Thornton', 'Daughter', '555-0117', 'Holds proxy access in Bioverse')
        ON CONFLICT DO NOTHING
        """,
        (_id(6200), P_MAYA, _id(6201), P_ELEANOR),
    )
