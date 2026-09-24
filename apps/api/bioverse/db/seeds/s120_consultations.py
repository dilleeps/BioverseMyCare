"""Online consultations and clinician credentialing. Idempotent: fixed IDs 10000-10999, ON CONFLICT DO NOTHING.

Everyone here is fictional. License numbers and NPIs are made up (the NPIs are patterned numbers that pass
the check-digit test), and every registry lookup recorded below is labelled as a simulated demo lookup.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from psycopg.types.json import Jsonb

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_OKAFOR, ORG, P_HADDAD, P_MAYA, P_PARK, PLAN, U_ADMIN, U_HADDAD, U_MAYA, U_OKAFOR, U_PARK, _id,
)

# Users and practitioners (10100-10299)
U_BENALI, U_RIVERA, U_WHITFIELD, U_CASTELLANO, U_ZHAO, U_SOLBERG, U_MENSAH = (_id(10101 + i) for i in range(7))
DR_BENALI, DR_RIVERA, DR_WHITFIELD, DR_CASTELLANO, DR_ZHAO, DR_SOLBERG, DR_MENSAH = (_id(10201 + i) for i in range(7))

# Credentials (10300-10399)
CR_OKAFOR, CR_BENALI, CR_RIVERA, CR_WHITFIELD, CR_CASTELLANO, CR_ZHAO, CR_SOLBERG, CR_MENSAH = (
    _id(10301 + i) for i in range(8)
)

# Consultations (10400-10499), messages (10500-10699), ratings (10700-10799)
CO_MAYA_DERM, CO_MAYA_VIDEO, CO_PARK_POOL, CO_PARK_FM, CO_HADDAD_ENDO, CO_HADDAD_CARDIO, CO_PARK_PSY = (
    _id(10401 + i) for i in range(7)
)

WEEKDAYS_9_5 = {d: ["09:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")}

CLINICIANS = [
    # user, practitioner, name, email, specialty, languages, modes, fee, years, hours, bio
    (U_BENALI, DR_BENALI, "Dr. Nadia Benali", "n.benali@northside.example", "Dermatology",
     ["English", "French", "Arabic"], ["message", "video"], 7500, 11, {**WEEKDAYS_9_5, "sat": ["10:00", "14:00"]},
     "Rashes, acne, eczema and mole checks. Send clear photos to your in-person visit if one is needed."),
    (U_RIVERA, DR_RIVERA, "Dr. Tomás Rivera", "t.rivera@northside.example", "Family medicine",
     ["English", "Spanish"], ["message", "video", "phone"], 4500, 18,
     {d: ["08:00", "20:00"] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
     "Everyday health questions for adults and families: colds, infections, medicines and prevention."),
    (U_WHITFIELD, DR_WHITFIELD, "Dr. Grace Whitfield", "g.whitfield@northside.example", "Pediatrics",
     ["English"], ["message", "video"], 5500, 9, WEEKDAYS_9_5,
     "Fevers, feeding, rashes and growth questions for babies, children and teenagers."),
    (U_CASTELLANO, DR_CASTELLANO, "Dr. Oren Castellano", "o.castellano@northside.example", "Psychiatry",
     ["English", "Hebrew"], ["video", "phone"], 9500, 7, WEEKDAYS_9_5,
     "Anxiety, low mood and sleep, with medication review when it helps."),
    (U_ZHAO, DR_ZHAO, "Dr. Mei Zhao", "m.zhao@northside.example", "Endocrinology",
     ["English", "Mandarin"], ["message", "video"], 8000, 14,
     {d: ["10:00", "18:00"] for d in ("tue", "wed", "thu", "fri", "sat")},
     "Diabetes and prediabetes, thyroid and hormone questions."),
    (U_SOLBERG, DR_SOLBERG, "Dr. Ingrid Solberg", "i.solberg@northside.example", "Psychiatry",
     ["English", "Norwegian"], ["video", "phone"], 9500, 20,
     {d: ["12:00", "20:00"] for d in ("mon", "tue", "wed", "thu")},
     "Adult psychiatry: anxiety, depression, ADHD and sleep. Evening appointments."),
    (U_MENSAH, DR_MENSAH, "Dr. Kwame Mensah", "k.mensah@northside.example", "Family medicine",
     ["English", "Twi"], ["message", "video"], 4500, 25, WEEKDAYS_9_5,
     "Family doctor for all ages."),
]

OKAFOR_PROFILE = (["message", "video"], 6500, 16, {d: ["13:00", "17:00"] for d in ("mon", "tue", "wed", "thu", "fri")},
                  "Cardiologist focused on prevention: cholesterol, blood pressure and heart-rhythm questions.")


def _checks(name: str, npi: str, lic: str, jur: str, lic_type: str, board: str | None, expires: date, at) -> list:
    iso = at.isoformat()
    out = [
        {"check": "NPI check digit (Luhn with 80840 prefix)", "result": "pass", "detail": f"NPI {npi}", "demo": False, "at": iso},
        {"check": "License in date", "result": "pass", "detail": f"Expires {expires:%d %b %Y}", "demo": False, "at": iso},
        {"check": "NPPES registry lookup", "result": "match",
         "detail": f"Name and NPI match {name} (simulated demo lookup)", "demo": True, "at": iso},
        {"check": f"State board lookup ({jur})", "result": "active",
         "detail": f"{lic_type} license {lic} active, no public discipline (simulated demo lookup)", "demo": True, "at": iso},
    ]
    if board:
        out.append({"check": "Board certification", "result": "confirmed", "detail": f"{board} (simulated demo lookup)",
                    "demo": True, "at": iso})
    return out


def _weekday_on_or_after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()

    # --- Clinicians ---------------------------------------------------------------------------
    cur.executemany(
        """
        INSERT INTO users (id, role, display_name, email, organization_id) VALUES (%s, 'clinician', %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [(c[0], c[2], c[3], ORG) for c in CLINICIANS],
    )
    cur.execute("UPDATE users SET demo_label = 'Dermatology', demo_order = 22 WHERE id = %s AND demo_label IS NULL",
                (U_BENALI,))
    cur.executemany(
        """
        INSERT INTO practitioners (id, user_id, organization_id, name, specialty, location_name, distance_km,
                                   languages, accessibility, accepted_plans, offers_telehealth)
        VALUES (%s, %s, %s, %s, %s, 'Northside Virtual Care', 0, %s, '{Remote}', %s, true)
        ON CONFLICT (id) DO NOTHING
        """,
        [(c[1], c[0], ORG, c[2], c[4], c[5], [PLAN]) for c in CLINICIANS],
    )
    profiles = [(c[1], c[6], c[7], c[8], json.dumps(c[9]), c[10]) for c in CLINICIANS]
    profiles.append((DR_OKAFOR, OKAFOR_PROFILE[0], OKAFOR_PROFILE[1], OKAFOR_PROFILE[2], json.dumps(OKAFOR_PROFILE[3]),
                     OKAFOR_PROFILE[4]))
    cur.executemany(
        """
        INSERT INTO consult_profiles (practitioner_id, modes, fee_cents, years_in_practice, hours, bio)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (practitioner_id) DO NOTHING
        """,
        profiles,
    )

    # --- Credentials ----------------------------------------------------------------------------
    verified_at = at(days(-120), 10, 0)
    creds = [
        # id, practitioner, name, license, jurisdiction, type, board, npi, issued, expires, status, source
        (CR_OKAFOR, DR_OKAFOR, "Dr. Adaeze Okafor", "MD-DEMO-204118", "NY", "MD",
         "American Board of Internal Medicine: Cardiovascular Disease", "1000000012", days(-3400), days(540), "verified", "state_board"),
        (CR_BENALI, DR_BENALI, "Dr. Nadia Benali", "MD-DEMO-311562", "NY", "MD",
         "American Board of Dermatology", "1000000020", days(-2900), days(410), "verified", "nppes"),
        (CR_RIVERA, DR_RIVERA, "Dr. Tomás Rivera", "MD-DEMO-118904", "NJ", "MD",
         "American Board of Family Medicine", "1000000038", days(-6000), days(300), "verified", "state_board"),
        (CR_WHITFIELD, DR_WHITFIELD, "Dr. Grace Whitfield", "MD-DEMO-402217", "NY", "MD",
         "American Board of Pediatrics", "1000000046", days(-2400), days(20), "verified", "state_board"),
        (CR_CASTELLANO, DR_CASTELLANO, "Dr. Oren Castellano", "MD-DEMO-520339", "CT", "MD",
         "American Board of Psychiatry and Neurology", "1000000053", days(-1900), days(700), "pending", "state_board"),
        (CR_ZHAO, DR_ZHAO, "Dr. Mei Zhao", "MD-DEMO-233781", "NY", "MD",
         "American Board of Internal Medicine: Endocrinology", "1000000061", days(-4200), days(620), "verified", "nppes"),
        (CR_SOLBERG, DR_SOLBERG, "Dr. Ingrid Solberg", "DO-DEMO-145090", "NY", "DO",
         "American Board of Psychiatry and Neurology", "1000000079", days(-5500), days(380), "verified", "state_board"),
        # Verified once, but the date has passed: the gate already excludes it; the expiry job marks it expired.
        (CR_MENSAH, DR_MENSAH, "Dr. Kwame Mensah", "MD-DEMO-087665", "NJ", "MD",
         "American Board of Family Medicine", "1000000087", days(-9000), days(-5), "verified", "state_board"),
    ]
    rows = []
    for cid, pr, name, lic, jur, typ, board, npi, issued, expires, st, source in creds:
        verified = st == "verified"
        checks = _checks(name, npi, lic, jur, typ, board, expires, verified_at) if verified else []
        rows.append((cid, pr, lic, jur, typ, board, npi, issued, expires, st, source, Jsonb(checks),
                     U_ADMIN if verified else None, verified_at if verified else None,
                     "Submitted for online consults." if st == "pending" else None,
                     U_CASTELLANO if st == "pending" else U_ADMIN))
    cur.executemany(
        """
        INSERT INTO practitioner_credentials (id, practitioner_id, license_number, jurisdiction, license_type,
            board_certification, npi, issued_on, expires_on, status, source, verification_checks, verified_by,
            verified_at, notes, submitted_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )

    # --- Consultations --------------------------------------------------------------------------
    video_day = _weekday_on_or_after(days(3))
    consults = [
        # id, patient, practitioner, requested, specialty, mode, reason, status, scheduled, fee, created, accepted,
        # started, completed, summary, follow up
        (CO_MAYA_DERM, P_MAYA, DR_BENALI, DR_BENALI, "Dermatology", "message",
         "I've had an itchy red patch on the inside of my left forearm for about two weeks. It started after I "
         "switched laundry detergent.",
         "completed", None, 7500, at(days(-41), 19, 5), at(days(-41), 20, 10), at(days(-41), 20, 12),
         at(days(-40), 9, 30),
         "Most likely irritant contact dermatitis from the new detergent. Go back to your previous detergent and "
         "rinse clothes twice for the next few weeks. Apply over-the-counter hydrocortisone 1% cream thinly twice a "
         "day for up to 7 days, and keep using a fragrance-free moisturizer. No prescription needed.",
         "If it spreads, blisters, or isn't clearly better in 2 weeks, message me here or book an in-person "
         "dermatology visit."),
        (CO_MAYA_VIDEO, P_MAYA, DR_OKAFOR, DR_OKAFOR, "Cardiology", "video",
         "Check in on how the atorvastatin is going, and go over my home blood pressure readings.",
         "accepted", at(video_day, 16, 30), 6500, at(days(-1), 12, 40), at(days(-1), 15, 5), None, None, None, None),
        (CO_PARK_POOL, P_PARK, None, None, "Cardiology", "message",
         "My home blood pressure readings have been around 135/85 for two weeks. Should I change anything?",
         "requested", None, 6500, at(days(-1), 18, 20), None, None, None, None, None),
        (CO_PARK_FM, P_PARK, DR_RIVERA, None, "Family medicine", "message",
         "Blocked, stuffy nose for 10 days. No fever. Is it worth seeing someone?",
         "completed", None, 4500, at(days(-20), 8, 15), at(days(-20), 9, 0), at(days(-20), 9, 2), at(days(-20), 11, 40),
         "Symptoms fit a viral sinus infection that is slow to clear. Saline rinses twice a day and a steroid nasal "
         "spray from the pharmacy for up to two weeks. Antibiotics aren't needed at this point.",
         "Message again if you get a fever over 39 °C, facial swelling, or you're not improving after another week."),
        (CO_HADDAD_ENDO, P_HADDAD, DR_ZHAO, DR_ZHAO, "Endocrinology", "video",
         "I'd like advice on whether I should be screened for diabetes. My sister was just diagnosed.",
         "completed", at(days(-30), 11, 0), 8000, at(days(-33), 10, 0), at(days(-33), 12, 0), at(days(-30), 11, 1),
         at(days(-30), 11, 24),
         "With a family history and your age, screening is sensible. I've suggested an HbA1c at your next blood test. "
         "Keep up regular walking; we'll go over the result together.",
         "HbA1c at your next lab visit. I'll message you with the result."),
        (CO_HADDAD_CARDIO, P_HADDAD, DR_OKAFOR, DR_OKAFOR, "Cardiology", "message",
         "Is it OK to take amlodipine in the morning instead of the evening?",
         "completed", None, 6500, at(days(-6), 9, 0), at(days(-6), 13, 10), at(days(-6), 13, 11), at(days(-6), 13, 30),
         "Yes. Amlodipine works over a full day, so morning or evening is fine. Pick one time and keep to it.",
         None),
        (CO_PARK_PSY, P_PARK, DR_SOLBERG, DR_SOLBERG, "Psychiatry", "video",
         "Trouble falling asleep since starting a new job two months ago.",
         "completed", at(days(-45), 18, 0), 9500, at(days(-47), 21, 0), at(days(-46), 12, 30), at(days(-45), 18, 0),
         at(days(-45), 18, 35),
         "Sleep trouble linked to work stress, without signs of depression today. We agreed a wind-down routine, a fixed "
         "wake time and no screens in bed. A sleep diary for two weeks will show what's helping.",
         "Book a follow-up in 3 to 4 weeks with your sleep diary."),
    ]
    inserted = []
    for (cid, pat, pr, req, spec, mode, reason, st, sched, fee, created, accepted, started, completed,
         summary, follow_up) in consults:
        row = cur.execute(
            """
            INSERT INTO consultations (id, patient_id, practitioner_id, requested_practitioner_id, specialty, mode, reason,
                status, scheduled_at, fee_cents, telehealth_consent, consented_at, created_at, accepted_at, started_at,
                completed_at, summary, follow_up, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING RETURNING id
            """,
            (cid, pat, pr, req, spec, mode, reason, st, sched, fee, created, created, accepted, started, completed,
             summary, follow_up, completed or accepted or created),
        ).fetchone()
        if row:
            inserted.append((cid, pat, spec, mode, reason, created))

    # Pre-consult intake summaries, built by the same rules path the API uses.
    from bioverse.routers.consultations import record_facts, rules_intake

    for cid, pat, spec, mode, reason, created in inserted:
        summary = rules_intake({"mode": mode, "specialty": spec, "reason": reason}, record_facts(conn, pat),
                               "Red-flag screen negative (demo seed).")
        summary["generated_at"] = created.isoformat()
        cur.execute(
            "UPDATE consultations SET intake_summary = %s, intake_produced_by = 'consult-intake/rules' WHERE id = %s",
            (Jsonb(summary), cid),
        )

    msgs = [
        # id, consult, patient, kind, user, label, body, at
        (_id(10501), CO_MAYA_DERM, P_MAYA, "patient", U_MAYA, "Maya Thornton", consults[0][6], at(days(-41), 19, 5)),
        (_id(10502), CO_MAYA_DERM, P_MAYA, "clinician", U_BENALI, "Dr. Nadia Benali",
         "Thanks, Maya. Is the patch raised or flat, and has it spread, blistered or wept at all? Have you put anything "
         "on it so far?", at(days(-41), 20, 12)),
        (_id(10503), CO_MAYA_DERM, P_MAYA, "patient", U_MAYA, "Maya Thornton",
         "It's flat and a bit dry, about the size of a coin. No blisters. I tried moisturizer but it still itches.",
         at(days(-41), 20, 31)),
        (_id(10504), CO_MAYA_DERM, P_MAYA, "clinician", U_BENALI, "Dr. Nadia Benali",
         "That fits a reaction to the detergent rather than anything worrying. I've written what to do in your summary.",
         at(days(-40), 9, 28)),
        (_id(10505), CO_MAYA_DERM, P_MAYA, "system", None, "Bioverse",
         "Dr. Nadia Benali completed the consult. The summary is below.", at(days(-40), 9, 30)),
        (_id(10506), CO_MAYA_VIDEO, P_MAYA, "patient", U_MAYA, "Maya Thornton", consults[1][6], at(days(-1), 12, 40)),
        (_id(10507), CO_MAYA_VIDEO, P_MAYA, "clinician", U_OKAFOR, "Dr. Adaeze Okafor",
         "Looking forward to it, Maya. If you can, jot down a week of home blood pressure readings before the call.",
         at(days(-1), 15, 6)),
        (_id(10508), CO_PARK_POOL, P_PARK, "patient", U_PARK, "Jun Park", consults[2][6], at(days(-1), 18, 20)),
        (_id(10509), CO_PARK_FM, P_PARK, "patient", U_PARK, "Jun Park", consults[3][6], at(days(-20), 8, 15)),
        (_id(10510), CO_PARK_FM, P_PARK, "clinician", U_RIVERA, "Dr. Tomás Rivera",
         "Hi Jun. Any fever, facial pain or swelling, or thick green discharge?", at(days(-20), 9, 2)),
        (_id(10511), CO_PARK_FM, P_PARK, "patient", U_PARK, "Jun Park", "No fever. Just blocked and a bit of pressure.",
         at(days(-20), 10, 50)),
        (_id(10512), CO_HADDAD_ENDO, P_HADDAD, "patient", U_HADDAD, "Rana Haddad", consults[4][6], at(days(-33), 10, 0)),
        (_id(10513), CO_HADDAD_CARDIO, P_HADDAD, "patient", U_HADDAD, "Rana Haddad", consults[5][6], at(days(-6), 9, 0)),
        (_id(10514), CO_PARK_PSY, P_PARK, "patient", U_PARK, "Jun Park", consults[6][6], at(days(-47), 21, 0)),
    ]
    cur.executemany(
        """
        INSERT INTO consultation_messages (id, consultation_id, patient_id, author_kind, author_user_id, author_label,
                                           body, screen_level, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, CASE WHEN %s = 'patient' THEN 'none' END, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[3], m[7]) for m in msgs],
    )

    ratings = [
        (_id(10701), CO_MAYA_DERM, P_MAYA, DR_BENALI, 5, "Clear advice and a quick reply.", at(days(-40), 12, 0)),
        (_id(10702), CO_PARK_FM, P_PARK, DR_RIVERA, 4, "Helpful, though the reply took a couple of hours.",
         at(days(-19), 8, 0)),
        (_id(10703), CO_HADDAD_ENDO, P_HADDAD, DR_ZHAO, 5, "Dr. Zhao explained everything clearly.", at(days(-30), 12, 0)),
        (_id(10704), CO_HADDAD_CARDIO, P_HADDAD, DR_OKAFOR, 5, None, at(days(-6), 15, 0)),
        (_id(10705), CO_PARK_PSY, P_PARK, DR_SOLBERG, 5, "I felt listened to.", at(days(-44), 9, 0)),
    ]
    cur.executemany(
        """
        INSERT INTO consultation_ratings (id, consultation_id, patient_id, practitioner_id, stars, comment,
                                          comment_status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s::text IS NULL THEN 'none' ELSE 'published' END, %s)
        ON CONFLICT DO NOTHING
        """,
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[5], r[6]) for r in ratings],
    )
