"""Hospital operations demo data: organization setup, care pathways, and 90 days of activity.

Everything here is fictional and uses fixed IDs from 4000-4999 with ON CONFLICT DO NOTHING, so it is
safe to run on every seed. Dates are relative to the day the row is first written.

ID ranges:
    4001-4009 locations            4011-4019 departments        4021-4039 services
    4051-4059 care pathways        4061-4099 pathway tasks
    4101-4119 patients             4121-4139 care plans         4141-4199 care plan tasks
    4201-4209 care gaps            4211-4219 reports            4221-4239 observations
    4301-4499 intakes              4501-4699 slots              4701-4899 appointments
    4901-4999 review items
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_ACHEBE,
    DR_FERREIRA,
    DR_LINDQVIST,
    DR_MORI,
    DR_OKAFOR,
    DR_RAMAN,
    DR_WEISS,
    ORG,
    PLAN,
    TEAM_DERM_TELE,
    U_OKAFOR,
    _id,
)

# --- Organization -------------------------------------------------------------------------------

LOC_HEART, LOC_CLINIC, LOC_RIVERSIDE, LOC_EASTGATE, LOC_VIDEO = (_id(n) for n in range(4001, 4006))
DEPT_CARDIO, DEPT_DERM, DEPT_PRIMARY, DEPT_NEURO = (_id(n) for n in range(4011, 4015))

WEEKDAY_HOURS = {d: {"open": "08:00", "close": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}

LOCATIONS = [
    (LOC_HEART, "Northside Heart Centre", "physical", "12 Harbour Road", "(555) 010-2410", True),
    (LOC_CLINIC, "Northside Clinic", "physical", "40 Mill Street", "(555) 010-2420", True),
    (LOC_RIVERSIDE, "Riverside Medical Centre", "physical", "3 Quay Lane", "(555) 010-2430", True),
    (LOC_EASTGATE, "Eastgate Family Practice", "physical", "88 East Gate", "(555) 010-2440", False),
    (LOC_VIDEO, "Video visit", "virtual", None, None, True),
]

DEPARTMENTS = [
    (DEPT_CARDIO, "Cardiology", "Cardiology", LOC_HEART, WEEKDAY_HOURS),
    (DEPT_DERM, "Dermatology", "Dermatology", LOC_CLINIC,
     {**WEEKDAY_HOURS, "sat": {"open": "09:00", "close": "13:00"}}),
    (DEPT_PRIMARY, "Primary care", "Primary care", LOC_CLINIC,
     {**{d: {"open": "07:30", "close": "18:00"} for d in WEEKDAY_HOURS}}),
    (DEPT_NEURO, "Neurology", "Neurology", LOC_CLINIC, {d: WEEKDAY_HOURS[d] for d in ("mon", "wed", "thu")}),
]

SERVICES = [
    (_id(4021), DEPT_CARDIO, "New cardiology consultation", 40, "in_person"),
    (_id(4022), DEPT_CARDIO, "Cardiology follow-up", 20, "either"),
    (_id(4023), DEPT_DERM, "Skin check", 20, "in_person"),
    (_id(4024), DEPT_DERM, "Dermatology video visit", 20, "video"),
    (_id(4025), DEPT_PRIMARY, "Primary care visit", 20, "either"),
    (_id(4026), DEPT_PRIMARY, "Annual physical", 40, "in_person"),
    (_id(4027), DEPT_NEURO, "Neurology consultation", 40, "in_person"),
]

PRACTITIONER_LOCATIONS = {
    "Northside Heart Centre": LOC_HEART,
    "Northside Clinic": LOC_CLINIC,
    "Riverside Medical Centre": LOC_RIVERSIDE,
    "Eastgate Family Practice": LOC_EASTGATE,
    "Video visit": LOC_VIDEO,
}

# --- Care pathways ------------------------------------------------------------------------------

PW_STATIN, PW_HTN, PW_BIOPSY = _id(4051), _id(4052), _id(4053)

PATHWAYS = [
    (PW_STATIN, "New statin start", "Cardiology", "Starting a statin for raised LDL cholesterol, with a lipid recheck.", [
        ("lab", "Baseline blood test", "Lipid panel and liver function before starting", None, 0),
        ("medication", "Start your statin, once daily", "Take it at the same time each evening", None, 0),
        ("checkin", "Check in about side effects", "Muscle aches, tiredness, anything new", None, 7),
        ("lab", "Recheck cholesterol", "Lipid panel at Northside Lab", None, 84),
        ("appointment", "Follow-up with cardiology", "Review results and next steps", "Cardiology", 90),
    ]),
    (PW_HTN, "Hypertension follow-up", "Cardiology", "Follow-up after a raised blood pressure reading or a new blood pressure medicine.", [
        ("lifestyle", "Cut down on salt", "Aim for less than a teaspoon a day", None, 0),
        ("checkin", "Send home blood pressure readings", "Morning and evening for one week", None, 7),
        ("lab", "Kidney function blood test", "Basic metabolic panel", None, 28),
        ("appointment", "Blood pressure follow-up visit", "Bring your readings", "Cardiology", 30),
    ]),
    (PW_BIOPSY, "Dermatology biopsy follow-up", "Dermatology", "Aftercare and results after a skin biopsy.", [
        ("lifestyle", "Keep the wound clean and covered", "Change the dressing daily for a week", None, 0),
        ("checkin", "Wound check", "Tell us about redness, swelling or discharge", None, 3),
        ("appointment", "Biopsy results visit", "Discuss the pathology report", "Dermatology", 10),
        ("lifestyle", "Sun protection", "SPF 30 or higher on exposed skin", None, 14),
    ]),
]

# --- Fictional patients -------------------------------------------------------------------------

PATIENTS = [
    (_id(4101), "Sofia Delgado", date(1969, 4, 2), "she/her", "Spanish"),
    (_id(4102), "Tomas Varga", date(1958, 9, 14), "he/him", "English"),
    (_id(4103), "Una Byrne", date(1990, 1, 23), "she/her", "English"),
    (_id(4104), "Victor Osei", date(1977, 7, 30), "he/him", "English"),
    (_id(4105), "Wen Li", date(1983, 12, 5), "she/her", "English"),
    (_id(4106), "Xavier Moreau", date(1995, 3, 17), "he/him", "English"),
    (_id(4107), "Yara Nasser", date(1964, 11, 8), "she/her", "English"),
    (_id(4108), "Zoe Kaplan", date(2001, 6, 21), "she/her", "English"),
]
P_SOFIA, P_TOMAS = PATIENTS[0][0], PATIENTS[1][0]

BY_SPECIALTY = {
    "Cardiology": [DR_OKAFOR, DR_RAMAN],
    "Dermatology": [DR_FERREIRA, DR_ACHEBE, TEAM_DERM_TELE],
    "Primary care": [DR_LINDQVIST, DR_MORI],
    "Neurology": [DR_WEISS],
}

COMPLAINTS = {
    "Cardiology": ["Palpitations", "Chest tightness on exertion", "High blood pressure reading"],
    "Dermatology": ["Itchy rash", "Changing mole", "Eczema flare", "Acne not improving"],
    "Primary care": ["Persistent cough", "Tiredness", "Sore throat", "Back pain"],
    "Neurology": ["Frequent migraines", "Numb fingers"],
}

# Weekly routed intakes per specialty. Week 0 is the most recent 7 days. Dermatology demand climbs.
DERM_BY_WEEK = {0: 18, 1: 10, 2: 6}


def weekly_counts(week: int) -> dict[str, int]:
    return {
        "Cardiology": 2 + (week % 3 == 0),
        "Dermatology": DERM_BY_WEEK.get(week, 3),
        "Primary care": 3 + (week % 2 == 0),
        "Neurology": 1,
    }


# Follow-up visits already booked for today and the next 7 days: booked slots per practitioner per day.
UPCOMING_PER_DAY = {
    DR_FERREIRA: 2, DR_ACHEBE: 1, TEAM_DERM_TELE: 2, DR_OKAFOR: 1, DR_RAMAN: 1,
    DR_LINDQVIST: 2, DR_MORI: 1, DR_WEISS: 1,
}

# Emergencies (red-flag escalations): days ago. Day 0 is today.
EMERGENCY_DAYS = [0, 4, 9, 17, 23, 30, 37, 45, 51, 58, 66, 73, 80, 86]

# Open review items: (practitioner, kind, priority, age in days, title)
OPEN_REVIEWS = [
    (DR_FERREIRA, "agent_escalation", "routine", 4, "Doctor Agent escalation · rash not improving"),
    (DR_FERREIRA, "agent_escalation", "routine", 2, "Doctor Agent escalation · cream side effect"),
    (DR_FERREIRA, "agent_escalation", "routine", 1, "Doctor Agent escalation · photo follow-up"),
    (DR_FERREIRA, "agent_escalation", "routine", 0, "Doctor Agent escalation · appointment question"),
    (DR_LINDQVIST, "agent_escalation", "routine", 3, "Doctor Agent escalation · cough persisting"),
    (DR_LINDQVIST, "agent_escalation", "routine", 1, "Doctor Agent escalation · sick note request"),
    (DR_RAMAN, "agent_escalation", "routine", 2, "Doctor Agent escalation · dizziness question"),
]


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()
    now = datetime.now(ctx.tz)

    cur.execute(
        """
        INSERT INTO organization_profiles (organization_id, display_name, accent_color, support_phone)
        VALUES (%s, 'Northside Health', '#0e6b60', '(555) 010-2400')
        ON CONFLICT (organization_id) DO NOTHING
        """,
        (ORG,),
    )
    cur.executemany(
        """
        INSERT INTO locations (id, organization_id, name, kind, address, phone, step_free)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(i, ORG, n, k, a, ph, sf) for i, n, k, a, ph, sf in LOCATIONS],
    )
    cur.executemany(
        """
        INSERT INTO departments (id, organization_id, name, specialty, location_id, hours)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(i, ORG, n, s, loc, json.dumps(h)) for i, n, s, loc, h in DEPARTMENTS],
    )
    cur.executemany(
        """
        INSERT INTO healthcare_services (id, organization_id, department_id, name, duration_min, mode)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(i, ORG, d, n, m, mode) for i, d, n, m, mode in SERVICES],
    )
    for name, loc in PRACTITIONER_LOCATIONS.items():
        cur.execute(
            "UPDATE practitioners SET location_id = %s WHERE organization_id = %s AND location_name = %s AND location_id IS NULL",
            (loc, ORG, name),
        )

    action_id = 4061
    for pid, name, specialty, description, actions in PATHWAYS:
        cur.execute(
            """
            INSERT INTO plan_definitions (id, organization_id, name, specialty, description)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (pid, ORG, name, specialty, description),
        )
        for pos, (kind, title, detail, spec, offset) in enumerate(actions, start=1):
            cur.execute(
                """
                INSERT INTO plan_definition_actions (id, plan_definition_id, position, kind, title, detail, specialty, due_offset_days)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (_id(action_id), pid, pos, kind, title, detail, spec, offset),
            )
            action_id += 1

    cur.executemany(
        """
        INSERT INTO patients (id, organization_id, name, birth_date, pronouns, preferred_language, insurance_plan)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(i, ORG, n, b, pr, lang, PLAN) for i, n, b, pr, lang in PATIENTS],
    )

    _seed_activity(cur, ctx, now)
    _seed_panel(cur, ctx)


def _seed_activity(cur, ctx: SeedContext, now: datetime) -> None:
    """Intakes, bookings and review work over the last 90 days (13 rolling weeks)."""
    at, days = ctx.at, ctx.days
    minutes = (5, 15, 25, 35, 45, 55)  # core slots never use these minutes
    used: set[tuple[str, datetime]] = set()

    def free_time(practitioner: str, day: date, n: int) -> datetime:
        k = n
        while True:
            t = at(day, 8 + (k % 9), minutes[k % 6])
            if (practitioner, t) not in used:
                used.add((practitioner, t))
                return t
            k += 1

    intake_n, slot_n, appt_n, review_n = 4301, 4501, 4701, 4901
    i = 0
    for week in range(13):
        for specialty, count in weekly_counts(week).items():
            for j in range(count):
                day_ago = 7 * week + ((j * 3 + len(specialty)) % 7)
                if day_ago > 90:
                    continue
                created = at(days(-day_ago), 8 + (i % 9), (i * 7) % 60)
                patient = PATIENTS[i % len(PATIENTS)][0]
                urgency = "urgent" if i % 5 == 0 else "self_care" if i % 7 == 3 else "routine"
                status = "closed" if urgency == "self_care" else "routed"
                complaint = COMPLAINTS[specialty][i % len(COMPLAINTS[specialty])]
                intake_id = _id(intake_n)
                cur.execute(
                    """
                    INSERT INTO intakes (id, patient_id, chief_complaint, urgency, red_flags, specialty,
                                         patient_summary, clinician_summary, status, produced_by, created_at)
                    VALUES (%s, %s, %s, %s, '{}', %s, %s, %s, %s, 'intake-agent/rules', %s) ON CONFLICT DO NOTHING
                    """,
                    (intake_id, patient, complaint, urgency, specialty,
                     f"You were routed to {specialty}.",
                     f"Demo history. {complaint}. Red-flag screen negative. Routed to {specialty}.",
                     status, created),
                )
                intake_n += 1

                practitioners = BY_SPECIALTY[specialty]
                practitioner = practitioners[i % len(practitioners)]
                # Roughly a third of routed intakes never book (referral leakage). Self-care needs no visit.
                books = status == "routed" and i % 3 != 2
                booked_at = created + timedelta(days=1 + i % 4)
                if books and booked_at <= now:
                    visit_day = (booked_at + timedelta(days=2 + i % 6)).astimezone(ctx.tz).date()
                    starts = free_time(practitioner, visit_day, i)
                    in_past = starts < now
                    slot_id = _id(slot_n)
                    cur.execute(
                        """
                        INSERT INTO slots (id, practitioner_id, starts_at, duration_min, mode, status)
                        VALUES (%s, %s, %s, 20, %s, 'booked') ON CONFLICT DO NOTHING
                        """,
                        (slot_id, practitioner, starts, "video" if practitioner == TEAM_DERM_TELE else "in_person"),
                    )
                    slot_n += 1
                    appt_id = _id(appt_n)
                    appt_n += 1
                    # Another module may already hold that exact time; then this booking is skipped.
                    if cur.execute("SELECT 1 FROM slots WHERE id = %s", (slot_id,)).fetchone() is not None:
                        cur.execute(
                            """
                            INSERT INTO appointments (id, patient_id, practitioner_id, slot_id, intake_id, reason, status, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                            """,
                            (appt_id, patient, practitioner, slot_id, intake_id, complaint,
                             "fulfilled" if in_past else "booked", booked_at),
                        )

                # Every fourth intake produced review work that has since been resolved.
                if i % 4 == 1 and day_ago >= 1:
                    hours = 2 + (i % 5) * 9  # 2 to 38 hours
                    resolved = created + timedelta(hours=hours)
                    if resolved <= now:
                        cur.execute(
                            """
                            INSERT INTO review_items (id, kind, patient_id, practitioner_id, title, body, priority,
                                                      status, resolution, resolved_by, created_at, resolved_at)
                            VALUES (%s, 'agent_escalation', %s, %s, %s, %s, 'routine', 'resolved', 'reply: demo history',
                                    %s, %s, %s) ON CONFLICT DO NOTHING
                            """,
                            (_id(review_n), patient, practitioner, f"Doctor Agent escalation · {complaint.lower()}",
                             "Demo history: patient question after intake.",
                             U_OKAFOR if practitioner == DR_OKAFOR else None, created, resolved),
                        )
                        review_n += 1
                i += 1

    # Follow-up visits on the books for today and the coming week (not tied to an intake).
    for day_ahead in range(0, 8):
        day = days(day_ahead)
        if day.weekday() == 6:
            continue
        for practitioner, per_day in UPCOMING_PER_DAY.items():
            for k in range(per_day):
                starts = free_time(practitioner, day, 3 * k + day_ahead)
                slot_id, appt_id = _id(slot_n), _id(appt_n)
                slot_n += 1
                appt_n += 1
                cur.execute(
                    """
                    INSERT INTO slots (id, practitioner_id, starts_at, duration_min, mode, status)
                    VALUES (%s, %s, %s, 20, %s, 'booked') ON CONFLICT DO NOTHING
                    """,
                    (slot_id, practitioner, starts, "video" if practitioner == TEAM_DERM_TELE else "in_person"),
                )
                if cur.execute("SELECT 1 FROM slots WHERE id = %s", (slot_id,)).fetchone() is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO appointments (id, patient_id, practitioner_id, slot_id, reason, status, created_at)
                    VALUES (%s, %s, %s, %s, 'Follow-up visit', %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (appt_id, PATIENTS[(slot_n + k) % len(PATIENTS)][0], practitioner, slot_id,
                     "fulfilled" if starts < now else "booked", at(days(-(3 + (slot_n * 11) % 78)), 10)),
                )

    # Red-flag escalations. The one from today is still waiting for acknowledgement.
    for k, day_ago in enumerate(EMERGENCY_DAYS):
        created = at(days(-day_ago), 7, 15 + k)
        patient = PATIENTS[(k + 3) % len(PATIENTS)][0]
        intake_id = _id(intake_n)
        cur.execute(
            """
            INSERT INTO intakes (id, patient_id, chief_complaint, urgency, red_flags, patient_summary,
                                 clinician_summary, status, produced_by, created_at)
            VALUES (%s, %s, 'Chest pain with breathlessness', 'emergency', %s, %s, %s, 'escalated',
                    'safety/red-flags', %s) ON CONFLICT DO NOTHING
            """,
            (intake_id, patient, ["possible heart attack"],
             "You were advised to get emergency help now.",
             "RED FLAG (possible heart attack). Demo history. Advised emergency services.", created),
        )
        intake_n += 1
        resolved = None if day_ago == 0 else created + timedelta(minutes=20 + 5 * k)
        cur.execute(
            """
            INSERT INTO review_items (id, kind, patient_id, practitioner_id, ref_id, title, body, priority, status,
                                      resolution, created_at, resolved_at)
            VALUES (%s, 'red_flag', %s, %s, %s, 'Red flag · possible heart attack',
                    'Patient was advised to seek emergency care.', 'urgent', %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (_id(review_n), patient, DR_LINDQVIST, intake_id, "open" if resolved is None else "resolved",
             None if resolved is None else "acknowledge", created, resolved),
        )
        review_n += 1

    for k, (practitioner, kind, priority, age, title) in enumerate(OPEN_REVIEWS):
        cur.execute(
            """
            INSERT INTO review_items (id, kind, patient_id, practitioner_id, title, body, priority, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Demo history: waiting for the clinician.', %s, %s) ON CONFLICT DO NOTHING
            """,
            (_id(review_n), kind, PATIENTS[k % len(PATIENTS)][0], practitioner, title, priority,
             at(days(-age), 6, 30 + k)),
        )
        review_n += 1

    assert intake_n <= 4500 and slot_n <= 4700 and appt_n <= 4900 and review_n <= 5000, "seed ID range overflow"


def _seed_panel(cur, ctx: SeedContext) -> None:
    """Two more patients on Dr. Okafor's panel, with care plans, gaps and an unexplained abnormal result."""
    at, days = ctx.at, ctx.days
    plans = [
        (_id(4121), P_SOFIA, PW_STATIN, "New statin start", days(-30), [
            ("lab", "Baseline blood test", "done", -30),
            ("medication", "Start your statin, once daily", "done", -30),
            ("checkin", "Check in about side effects", "todo", -23),
            ("lab", "Recheck cholesterol", "todo", 54),
            ("appointment", "Follow-up with cardiology", "todo", 60),
        ]),
        (_id(4122), P_TOMAS, PW_HTN, "Hypertension follow-up", days(-20), [
            ("lifestyle", "Cut down on salt", "done", -20),
            ("checkin", "Send home blood pressure readings", "done", -13),
            ("lab", "Kidney function blood test", "todo", -2),
            ("appointment", "Blood pressure follow-up visit", "todo", 10),
        ]),
    ]
    task_n = 4141
    for plan_id, patient, pathway, title, started, tasks in plans:
        cur.execute(
            """
            INSERT INTO care_plans (id, patient_id, practitioner_id, title, started_at, plan_definition_id)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (plan_id, patient, DR_OKAFOR, title, at(started, 10), pathway),
        )
        for pos, (kind, t_title, status, due) in enumerate(tasks, start=1):
            cur.execute(
                """
                INSERT INTO care_plan_tasks (id, care_plan_id, position, kind, title, specialty, due_on, status, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (_id(task_n), plan_id, pos, kind, t_title, "Cardiology" if kind == "appointment" else None,
                 days(due), status, at(days(due), 12) if status == "done" else None),
            )
            task_n += 1

    cur.executemany(
        "INSERT INTO care_gaps (id, patient_id, title, detail, specialty) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        [
            (_id(4201), P_SOFIA, "Diabetes screening due", "No HbA1c on record in the last three years.", "Primary care"),
            (_id(4202), P_TOMAS, "Flu vaccine due", "Seasonal influenza vaccine not recorded this year.", "Primary care"),
        ],
    )

    report = _id(4211)
    cur.execute(
        """
        INSERT INTO diagnostic_reports (id, patient_id, name, lab_name, collected_at, responsible_practitioner_id)
        VALUES (%s, %s, 'Basic metabolic panel', 'Northside Lab', %s, %s) ON CONFLICT DO NOTHING
        """,
        (report, P_TOMAS, at(days(-3), 8), DR_OKAFOR),
    )
    cur.executemany(
        """
        INSERT INTO observations (id, patient_id, report_id, loinc_code, display, value, unit, ref_low, ref_high,
                                  interpretation, effective_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (_id(4221), P_TOMAS, report, "2823-3", "Potassium", 5.6, "mmol/L", 3.5, 5.1, "H", at(days(-3), 8)),
            (_id(4222), P_TOMAS, report, "2951-2", "Sodium", 139, "mmol/L", 135, 145, "N", at(days(-3), 8)),
            (_id(4223), P_TOMAS, report, "2160-0", "Creatinine", 1.0, "mg/dL", 0.7, 1.3, "N", at(days(-3), 8)),
        ],
    )
