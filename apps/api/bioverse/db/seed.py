"""Seed a demo tenant that matches the Bioverse One designs.

Dates are relative to today so booked slots are always in the future and history
always reads as recent. IDs are fixed so the web app's demo identities are stable.

Usage:
    python -m bioverse.db.seed
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg

from bioverse.config import get_settings


def _id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


ORG = _id(1)

# Users
U_MAYA, U_OKAFOR, U_PARK, U_HADDAD, U_FRONTDESK = _id(101), _id(102), _id(103), _id(104), _id(105)

# Patients
P_MAYA, P_PARK, P_HADDAD = _id(201), _id(202), _id(203)

# Practitioners
DR_OKAFOR, DR_FERREIRA, DR_ACHEBE, TEAM_DERM_TELE = _id(301), _id(302), _id(303), _id(304)
DR_LINDQVIST, DR_RAMAN, DR_MORI, DR_WEISS = _id(305), _id(306), _id(307), _id(308)

PLAN = "Northside Health Plus"

DEMO_USERS = {
    "patient": U_MAYA,
    "clinician": U_OKAFOR,
}


def seed(database_url: str) -> None:
    tz = ZoneInfo(os.getenv("BIOVERSE_CLINIC_TZ", "America/New_York"))
    today = datetime.now(tz).date()

    def at(day: date, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(day, time(hh, mm), tzinfo=tz)

    def days(n: int) -> date:
        return today + timedelta(days=n)

    with psycopg.connect(database_url) as conn:
        cur = conn.cursor()

        cur.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (ORG, "Northside Health"))

        users = [
            (U_MAYA, "patient", "Maya Thornton", "maya@example.com"),
            (U_OKAFOR, "clinician", "Dr. Adaeze Okafor", "a.okafor@northside.example"),
            (U_PARK, "patient", "Jun Park", "jun@example.com"),
            (U_HADDAD, "patient", "Rana Haddad", "rana@example.com"),
            (U_FRONTDESK, "staff", "Northside Front Desk", "frontdesk@northside.example"),
        ]
        cur.executemany(
            "INSERT INTO users (id, role, display_name, email, organization_id) VALUES (%s, %s, %s, %s, %s)",
            [(*u, ORG) for u in users],
        )

        practitioners = [
            # id, user_id, name, specialty, location, km, languages, accessibility, telehealth
            (DR_OKAFOR, U_OKAFOR, "Dr. Adaeze Okafor", "Cardiology", "Northside Heart Centre", 3.4,
             ["English", "Igbo"], ["Step-free access"], False),
            (DR_FERREIRA, None, "Dr. Lucía Ferreira", "Dermatology", "Northside Clinic", 2.1,
             ["English", "Spanish"], ["Step-free access"], False),
            (DR_ACHEBE, None, "Dr. Samuel Achebe", "Dermatology", "Riverside Medical Centre", 4.8,
             ["English", "Spanish"], [], False),
            (TEAM_DERM_TELE, None, "Telehealth · Dermatology team", "Dermatology", "Video visit", 0,
             ["English"], ["Remote"], True),
            (DR_LINDQVIST, None, "Dr. Erik Lindqvist", "Primary care", "Northside Clinic", 2.1,
             ["English", "Swedish"], ["Step-free access"], True),
            (DR_RAMAN, None, "Dr. Priya Raman", "Cardiology", "Riverside Medical Centre", 4.8,
             ["English", "Hindi", "Spanish"], ["Step-free access"], True),
            (DR_MORI, None, "Dr. Kenji Mori", "Primary care", "Eastgate Family Practice", 6.2,
             ["English", "Japanese"], [], False),
            (DR_WEISS, None, "Dr. Hannah Weiss", "Neurology", "Northside Clinic", 2.1,
             ["English", "German"], ["Step-free access"], True),
        ]
        cur.executemany(
            """
            INSERT INTO practitioners
                (id, user_id, organization_id, name, specialty, location_name, distance_km,
                 languages, accessibility, accepted_plans, offers_telehealth)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(p[0], p[1], ORG, p[2], p[3], p[4], p[5], p[6], p[7], [PLAN], p[8]) for p in practitioners],
        )

        patients = [
            (P_MAYA, U_MAYA, "Maya Thornton", date(1972, 3, 9), "she/her", "Spanish", ["Penicillin"]),
            (P_PARK, U_PARK, "Jun Park", date(1985, 11, 2), "he/him", "English", []),
            (P_HADDAD, U_HADDAD, "Rana Haddad", date(1961, 6, 18), "she/her", "English", ["Sulfa drugs"]),
        ]
        cur.executemany(
            """
            INSERT INTO patients (id, user_id, organization_id, name, birth_date, pronouns,
                                  preferred_language, insurance_plan, allergies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(p[0], p[1], ORG, p[2], p[3], p[4], p[5], PLAN, p[6]) for p in patients],
        )

        # Availability for the next two weeks. The first slot per clinician is staggered
        # so the navigator has a clear "earliest" option.
        first_slot = {
            DR_FERREIRA: (2, 9, 20), DR_ACHEBE: (6, 14, 0), TEAM_DERM_TELE: (0, 17, 40),
            DR_OKAFOR: (5, 10, 0), DR_RAMAN: (3, 11, 30), DR_LINDQVIST: (1, 8, 40),
            DR_MORI: (2, 15, 0), DR_WEISS: (4, 13, 20),
        }
        slot_rows = []
        for pid, (d0, hh, mm) in first_slot.items():
            mode = "video" if pid == TEAM_DERM_TELE else "in_person"
            for offset in range(0, 14, 2):
                for extra_hours in (0, 2):
                    slot_rows.append((pid, at(days(d0 + offset), hh + extra_hours, mm), mode))
        cur.executemany(
            "INSERT INTO slots (practitioner_id, starts_at, mode) VALUES (%s, %s, %s)", slot_rows
        )

        # Maya's history ------------------------------------------------------------
        cur.executemany(
            "INSERT INTO encounters (patient_id, practitioner_id, occurred_at, kind, summary) VALUES (%s, %s, %s, %s, %s)",
            [
                (P_MAYA, DR_LINDQVIST, at(days(-194), 9), "Annual physical", "BP 138/88. Lipid panel ordered."),
                (P_MAYA, DR_OKAFOR, at(days(-2), 9, 20), "Cardiology visit", "Care plan started. Atorvastatin 20 mg. Echo referral."),
            ],
        )
        cur.execute(
            "INSERT INTO immunizations (patient_id, vaccine, location, occurred_at) VALUES (%s, %s, %s, %s)",
            (P_MAYA, "Influenza vaccine", "Riverside Pharmacy", at(days(-113), 11)),
        )
        cur.execute(
            """
            INSERT INTO intakes (patient_id, chief_complaint, urgency, red_flags, specialty,
                                 patient_summary, clinician_summary, status, produced_by, created_at)
            VALUES (%s, %s, 'routine', '{}', 'Cardiology', %s, %s, 'routed', 'intake-agent/rules', %s)
            """,
            (
                P_MAYA,
                "Chest discomfort",
                "You reported chest discomfort that started the day before. The safety check found no warning signs, and you were routed to cardiology.",
                "54F. Intermittent chest discomfort x1 day, not present at time of intake. Red-flag screen negative "
                "(no dyspnoea, diaphoresis, radiation, or ongoing pain). Hx: LDL rising over 18 months. Allergy: penicillin.",
                at(days(-4), 8, 14),
            ),
        )

        lipid_panels = [
            (days(-560), {"LDL": 121, "HDL": 55, "TG": 138, "TC": 186}),
            (days(-367), {"LDL": 134, "HDL": 57, "TG": 133, "TC": 192}),
            (days(-2), {"LDL": 148, "HDL": 58, "TG": 130, "TC": 198}),
        ]
        loinc = {
            "LDL": ("13457-7", "LDL cholesterol", None, 100),
            "HDL": ("2085-9", "HDL cholesterol", 40, None),
            "TG": ("2571-8", "Triglycerides", None, 150),
            "TC": ("2093-3", "Total cholesterol", None, 200),
        }
        latest_report_id = None
        for i, (day, values) in enumerate(lipid_panels):
            cur.execute(
                """
                INSERT INTO diagnostic_reports (patient_id, name, lab_name, collected_at, responsible_practitioner_id)
                VALUES (%s, 'Lipid panel', 'Northside Lab', %s, %s) RETURNING id
                """,
                (P_MAYA, at(day, 7, 45), DR_OKAFOR if i == 2 else DR_LINDQVIST),
            )
            report_id = cur.fetchone()[0]
            latest_report_id = report_id
            for key, value in values.items():
                code, display, low, high = loinc[key]
                interp = "H" if high is not None and value >= high else "L" if low is not None and value < low else "N"
                cur.execute(
                    """
                    INSERT INTO observations (patient_id, report_id, loinc_code, display, value, unit,
                                              ref_low, ref_high, interpretation, effective_at)
                    VALUES (%s, %s, %s, %s, %s, 'mg/dL', %s, %s, %s, %s)
                    """,
                    (P_MAYA, report_id, code, display, value, low, high, interp, at(day, 7, 45)),
                )
            if i < 2:
                text = "Your cholesterol values were reviewed. LDL was a little above target; your doctor will recheck it."
                cur.execute(
                    """
                    INSERT INTO result_explanations (report_id, draft_text, final_text, status, produced_by, reviewed_by, reviewed_at)
                    VALUES (%s, %s, %s, 'approved', 'results-agent/rules', %s, %s)
                    """,
                    (report_id, text, text, U_OKAFOR, at(day + timedelta(days=1), 12)),
                )

        latest_expl = (
            "Your LDL cholesterol is above the target range and has risen over the last 18 months. "
            "Your other values are within range. Dr. Okafor has recommended starting a statin and "
            "rechecking your cholesterol in about three months."
        )
        cur.execute(
            """
            INSERT INTO result_explanations (report_id, draft_text, final_text, questions, status, produced_by, reviewed_by, reviewed_at)
            VALUES (%s, %s, %s, %s, 'approved', 'results-agent/rules', %s, %s)
            """,
            (
                latest_report_id,
                latest_expl,
                latest_expl,
                json.dumps([
                    "Should I start a medication, or try lifestyle changes first?",
                    "When should this be rechecked?",
                    "Does my family history change the target?",
                ]),
                U_OKAFOR,
                at(days(-1), 12),
            ),
        )

        cur.execute(
            """
            INSERT INTO care_plans (patient_id, practitioner_id, title, started_at)
            VALUES (%s, %s, 'Cholesterol and heart health', %s) RETURNING id
            """,
            (P_MAYA, DR_OKAFOR, at(days(-2), 9, 40)),
        )
        plan_id = cur.fetchone()[0]
        tasks = [
            (1, "lab", "Blood test", "Lipid panel at Northside Lab", None, days(-2), "done"),
            (2, "medication", "Start atorvastatin 20 mg, once daily", "Take in the evening", None, days(0), "todo"),
            (3, "appointment", "Follow-up with cardiology", "Book within two weeks", "Cardiology", days(12), "todo"),
            (4, "referral", "Schedule an echocardiogram", "Referral sent to Imaging. They will contact you.", None, days(7), "todo"),
            (5, "checkin", "Check in with Bioverse in 30 days", "How the medication is going", None, days(28), "todo"),
        ]
        cur.executemany(
            """
            INSERT INTO care_plan_tasks (care_plan_id, position, kind, title, detail, specialty, due_on, status, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(plan_id, *t, at(days(-2), 8) if t[6] == "done" else None) for t in tasks],
        )

        cur.execute(
            "INSERT INTO care_gaps (patient_id, title, detail, specialty) VALUES (%s, %s, %s, %s)",
            (P_MAYA, "Blood pressure check overdue", "Last reading was 6 months ago and slightly high.", "Primary care"),
        )

        # Clinician review queue --------------------------------------------------------
        cur.execute(
            """
            INSERT INTO diagnostic_reports (patient_id, name, lab_name, collected_at, responsible_practitioner_id)
            VALUES (%s, 'HbA1c', 'Northside Lab', %s, %s) RETURNING id
            """,
            (P_PARK, at(days(-1), 8), DR_OKAFOR),
        )
        park_report = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO observations (patient_id, report_id, loinc_code, display, value, unit, ref_low, ref_high, interpretation, effective_at)
            VALUES (%s, %s, '4548-4', 'Hemoglobin A1c', 6.1, '%%', NULL, 5.7, 'H', %s)
            """,
            (P_PARK, park_report, at(days(-1), 8)),
        )
        park_draft = (
            "Your HbA1c is 6.1%, which is slightly above the normal range. This is sometimes called "
            "prediabetes. It is common and often improves with changes to diet and activity. "
            "Your doctor will talk with you about next steps."
        )
        cur.execute(
            """
            INSERT INTO result_explanations (report_id, draft_text, questions, status, produced_by)
            VALUES (%s, %s, %s, 'pending_review', 'results-agent/rules') RETURNING id
            """,
            (park_report, park_draft, json.dumps(["What changes would make the biggest difference?", "When should I retest?"])),
        )
        park_expl = cur.fetchone()[0]

        cur.executemany(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                ("result_explanation", P_PARK, DR_OKAFOR, park_expl, "Result explanation · HbA1c 6.1%",
                 park_draft, "routine", at(days(0), 7, 10)),
                ("agent_escalation", P_HADDAD, DR_OKAFOR, None, "Doctor Agent escalation · side effect",
                 "\"Is dizziness normal with the new tablet?\" Patient started amlodipine 5 mg eight days ago. "
                 "Agent gathered: dizziness on standing, no falls, no chest pain.", "routine", at(days(0), 6, 55)),
            ],
        )

        # Doctor Agent configuration --------------------------------------------------------
        cur.execute(
            """
            INSERT INTO doctor_agent_configs (practitioner_id, previsit_questions, followup_protocol,
                                              escalation_rules, approval_requirements)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                DR_OKAFOR,
                json.dumps([
                    {"id": "q1", "text": "Any chest pain, breathlessness or palpitations since last visit?", "source": "specialty", "enabled": True},
                    {"id": "q2", "text": "Current medications and any missed doses this week", "source": "specialty", "enabled": True},
                    {"id": "q3", "text": "Home blood pressure readings, if you have any", "source": "clinician", "enabled": True},
                    {"id": "q4", "text": "Sleep quality over the past two weeks", "source": "clinician", "enabled": False},
                ]),
                json.dumps([
                    {"day": 1, "action": "Confirm first dose taken"},
                    {"day": 7, "action": "Side effects check: muscle pain, fatigue"},
                    {"day": 30, "action": "Adherence check and prompt lipid recheck booking"},
                ]),
                json.dumps([
                    {"id": "red_flag", "label": "Red-flag symptom", "action": "emergency_guidance", "route_to": "clinician_and_team_now", "locked": True},
                    {"id": "new_symptom", "label": "New or worsening symptom", "action": "gather_then_escalate", "route_to": "clinician_same_day", "locked": False},
                    {"id": "side_effect", "label": "Side-effect question", "action": "answer_from_approved_content", "route_to": "staff_if_unresolved", "locked": False},
                    {"id": "logistics", "label": "Appointment or logistics", "action": "handle_via_scheduling", "route_to": "front_desk", "locked": False},
                ]),
                json.dumps([
                    {"id": "abnormal_results", "label": "Abnormal result explanations", "required": True, "locked": True},
                    {"id": "medication_instructions", "label": "Medication instructions", "required": True, "locked": True},
                    {"id": "normal_results", "label": "Normal result explanations", "required": True, "locked": False},
                    {"id": "routine_education", "label": "Routine education from my approved handouts", "required": False, "locked": False},
                ]),
            ),
        )

        cur.execute(
            "INSERT INTO audit_events (actor_role, agent, action, entity_type, detail) VALUES ('system', 'seed', 'seed', 'organization', %s)",
            (json.dumps({"organization": "Northside Health"}),),
        )
        conn.commit()


def main() -> None:
    seed(get_settings().database_url)
    print("Seeded demo tenant: Northside Health")


if __name__ == "__main__":
    main()
