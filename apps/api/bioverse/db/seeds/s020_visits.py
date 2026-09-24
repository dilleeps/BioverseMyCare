"""Visits and referrals demo data (IDs 2000-2999). Idempotent: safe to re-run against a live database.

- Location details for every seeded location, including the video-visit room.
- Northside Imaging (echocardiography) with free slots, so Maya can book her echo from the navigator.
- Maya's echocardiogram referral from Dr. Okafor: sent two days ago, accepted by the front desk yesterday.
- Two more referrals that show the clinician's flags (missing documents and expiring; accepted but not booked).
- An after-visit summary for Maya's cardiology visit two days ago.
- Dr. Okafor's clinic queue for the day of the first seed (Jun Park, Rana Haddad).
- Pre-visit checklist items for any upcoming appointments Maya has.
"""

from __future__ import annotations

from datetime import timedelta

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_LINDQVIST, DR_MORI, DR_OKAFOR, ORG, P_HADDAD, P_MAYA, P_PARK, PLAN, U_FRONTDESK, U_OKAFOR, _id,
)

IMAGING = _id(2001)

LOC_HEART, LOC_CLINIC, LOC_RIVERSIDE, LOC_EASTGATE, LOC_VIDEO = _id(2010), _id(2011), _id(2012), _id(2013), _id(2014)

REF_MAYA_ECHO, REF_HADDAD_PC, REF_PARK_PC = _id(2020), _id(2030), _id(2060)

SLOT_PARK_TODAY, SLOT_HADDAD_TODAY = _id(2040), _id(2041)
APPT_PARK_TODAY, APPT_HADDAD_TODAY = _id(2042), _id(2043)

AVS_MAYA_CARDIO = _id(2050)

LOCATIONS = [
    # id, name, mode, address, phone, parking, directions, accessibility, join_url, tech_check
    (LOC_HEART, "Northside Heart Centre", "physical", "140 Northside Avenue, Building B, 3rd floor",
     "(555) 010-4410", "Visitor garage on Linden Street. The first two hours are free with a validated ticket.",
     "Take the Building B lifts to floor 3 and follow the red line to Cardiology and Imaging reception.",
     ["Step-free entrance", "Lifts to every floor", "Accessible toilets", "Wheelchairs at the entrance"], None, []),
    (LOC_CLINIC, "Northside Clinic", "physical", "112 Northside Avenue, ground floor",
     "(555) 010-4400", "Surface lot behind the clinic. Accessible bays next to the main door.",
     "Enter through the main doors on Northside Avenue. Reception is on your left.",
     ["Step-free entrance", "Hearing loop at reception", "Accessible toilets"], None, []),
    (LOC_RIVERSIDE, "Riverside Medical Centre", "physical", "8 Riverside Walk, 2nd floor",
     "(555) 010-5520", "Pay-and-display street parking on Riverside Walk. The Mill Road garage is a 4-minute walk.",
     "Use the Riverside Walk entrance and take the lift to floor 2.",
     ["Lift to all floors", "Accessible toilets"], None, []),
    (LOC_EASTGATE, "Eastgate Family Practice", "physical", "27 Eastgate Road",
     "(555) 010-6630", "Small free lot at the front, usually full after 10am. Street parking on Hale Lane.",
     "The practice is next to Eastgate Pharmacy. Ring the bell if the door is closed.",
     ["Two steps at the entrance; ramp on request"], None, []),
    (LOC_VIDEO, "Video visit", "virtual", None, "(555) 010-4499", None, None,
     ["Live captions available", "Works with screen readers"],
     "https://visit.northside.example/join",
     ["Use a phone, tablet or computer with a camera and microphone.",
      "Use Chrome, Safari or Edge, updated to the latest version.",
      "Allow camera and microphone access when your browser asks.",
      "Open the link 15 minutes early. If it doesn't work, call the number above."]),
]


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()

    cur.executemany(
        """
        INSERT INTO locations (id, organization_id, name, mode, address, phone, parking, directions,
                               accessibility, join_url, tech_check)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        [(loc[0], ORG, *loc[1:]) for loc in LOCATIONS],
    )

    # Northside Imaging, bookable through the navigator under "Imaging".
    cur.execute(
        """
        INSERT INTO practitioners (id, user_id, organization_id, name, specialty, location_name, distance_km,
                                   languages, accessibility, accepted_plans, offers_telehealth)
        VALUES (%s, NULL, %s, 'Northside Imaging · Echocardiography', 'Imaging', 'Northside Heart Centre', 3.4,
                %s, %s, %s, false)
        ON CONFLICT DO NOTHING
        """,
        (IMAGING, ORG, ["English", "Spanish"], ["Step-free access"], [PLAN]),
    )
    # Free slots for the next two weeks. Keyed by (practitioner, time), so re-seeding later tops them up.
    cur.executemany(
        """
        INSERT INTO slots (practitioner_id, starts_at, duration_min, mode) VALUES (%s, %s, 45, 'in_person')
        ON CONFLICT DO NOTHING
        """,
        [(IMAGING, at(days(d), hh, mm)) for d in range(1, 15) for hh, mm in ((8, 30), (11, 0), (14, 30))],
    )

    # Referrals ----------------------------------------------------------------------------------------
    referrals = [
        # id, patient, target, specialty, reason, priority, required, provided, status, sent, accepted, expires
        (REF_MAYA_ECHO, P_MAYA, IMAGING, "Imaging",
         "Transthoracic echocardiogram to assess heart structure and function, as discussed at the cardiology visit.",
         "routine", ["Referral letter", "Recent lipid panel", "Cardiology visit notes"],
         ["Referral letter", "Recent lipid panel", "Cardiology visit notes"],
         "accepted", at(days(-2), 9, 45), at(days(-1), 10, 5), days(88)),
        (REF_HADDAD_PC, P_HADDAD, DR_MORI, "Primary care",
         "Blood pressure medication review. Dizziness on standing since starting amlodipine 5 mg.",
         "routine", ["Referral letter", "Medication list"], ["Referral letter"],
         "sent", at(days(-12), 11, 20), None, days(4)),
        (REF_PARK_PC, P_PARK, DR_LINDQVIST, "Primary care",
         "HbA1c 6.1%. Please enrol in the diabetes prevention programme and review lifestyle goals.",
         "routine", ["Referral letter", "HbA1c result"], ["Referral letter", "HbA1c result"],
         "accepted", at(days(-10), 14, 0), at(days(-8), 9, 30), days(50)),
    ]
    for i, (rid, pid, target, spec, reason, prio, req, prov, st, sent, accepted, expires) in enumerate(referrals):
        created = sent - timedelta(minutes=10)
        cur.execute(
            """
            INSERT INTO service_requests (id, organization_id, patient_id, requester_id, specialty,
                                          target_practitioner_id, reason, priority, required_documents,
                                          provided_documents, status, expires_on, created_at, sent_at,
                                          accepted_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (rid, ORG, pid, DR_OKAFOR, spec, target, reason, prio, req, prov, st, expires, created, sent,
             accepted, accepted or sent),
        )
        if cur.fetchone() is None:
            continue  # already seeded; leave its history alone
        base = 2100 + i * 10
        history = [
            (_id(base), None, "draft", U_OKAFOR, None, created),
            (_id(base + 1), "draft", "sent", U_OKAFOR, None, sent),
        ]
        if accepted:
            history.append((_id(base + 2), "sent", "accepted", U_FRONTDESK, "Accepted. The patient can book online.", accepted))
        cur.executemany(
            """
            INSERT INTO service_request_history (id, service_request_id, patient_id, from_status, to_status,
                                                 actor_user_id, note, occurred_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [(h[0], rid, pid, *h[1:]) for h in history],
        )
        cur.execute(
            """
            INSERT INTO review_items (id, kind, patient_id, practitioner_id, ref_id, title, body, priority, link,
                                      status, resolution, resolved_by, created_at, resolved_at)
            VALUES (%s, 'referral', %s, %s, %s, %s, %s, %s, '/clinician/referrals', %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (_id(base + 5), pid, target, rid, f"Referral · {spec} from Dr. Adaeze Okafor", reason, prio,
             "resolved" if accepted else "open", "accepted by Northside Front Desk" if accepted else None,
             U_FRONTDESK if accepted else None, sent, accepted),
        )
        cur.execute(
            """
            INSERT INTO audit_events (actor_role, agent, action, entity_type, entity_id, patient_id, detail)
            VALUES ('system', 'seed', 'referral_seeded', 'service_request', %s, %s, '{}'::jsonb)
            """,
            (rid, pid),
        )

    # After-visit summary for Maya's cardiology visit two days ago (written by Dr. Okafor).
    enc = conn.execute(
        """
        SELECT id FROM encounters WHERE patient_id = %s AND practitioner_id = %s
        ORDER BY occurred_at DESC LIMIT 1
        """,
        (P_MAYA, DR_OKAFOR),
    ).fetchone()
    if enc is not None:
        cur.execute(
            """
            INSERT INTO after_visit_summaries (id, patient_id, practitioner_id, encounter_id, instructions,
                                               follow_up, prescriptions, author_user_id, published_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                AVS_MAYA_CARDIO, P_MAYA, DR_OKAFOR, enc[0],
                "Your LDL cholesterol is above target. Start atorvastatin 20 mg once a day, in the evening. "
                "Keep taking your other medicines as usual. Call us if you notice muscle pain or unusual tiredness. "
                "If chest discomfort comes back and is severe, spreads to your arm or jaw, or comes with "
                "breathlessness or sweating, call 911.",
                "Book a cardiology follow-up within two weeks. Book the echocardiogram once Imaging accepts the "
                "referral. Repeat the cholesterol blood test in about three months.",
                "Atorvastatin 20 mg tablet, one each evening. 30 tablets, 2 repeats.",
                U_OKAFOR, at(days(-2), 10, 15), at(days(-2), 10, 15),
            ),
        )

    # Dr. Okafor's clinic queue for the day of the first seed.
    cur.executemany(
        """
        INSERT INTO slots (id, practitioner_id, starts_at, duration_min, mode, status)
        VALUES (%s, %s, %s, 20, 'in_person', 'booked')
        ON CONFLICT DO NOTHING
        """,
        [(SLOT_PARK_TODAY, DR_OKAFOR, at(days(0), 9, 0)), (SLOT_HADDAD_TODAY, DR_OKAFOR, at(days(0), 9, 40))],
    )
    cur.executemany(
        """
        INSERT INTO appointments (id, patient_id, practitioner_id, slot_id, reason, created_at)
        SELECT %s, %s, %s, %s, %s, %s WHERE EXISTS (SELECT 1 FROM slots WHERE id = %s)
        ON CONFLICT DO NOTHING
        """,
        [
            (APPT_PARK_TODAY, P_PARK, DR_OKAFOR, SLOT_PARK_TODAY, "Blood sugar and heart health review",
             at(days(-6), 12), SLOT_PARK_TODAY),
            (APPT_HADDAD_TODAY, P_HADDAD, DR_OKAFOR, SLOT_HADDAD_TODAY, "Dizziness since starting amlodipine",
             at(days(-3), 15), SLOT_HADDAD_TODAY),
        ],
    )

    # Pre-visit checklists for any upcoming appointments Maya already has.
    from bioverse.routers.visits import ensure_checklist

    for appt_id, patient_id, mode, location_name, reason in conn.execute(
        """
        SELECT a.id::text, a.patient_id::text, s.mode, pr.location_name, a.reason
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.patient_id = %s AND a.status = 'booked' AND s.starts_at > now()
        """,
        (P_MAYA,),
    ).fetchall():
        ensure_checklist(conn, {"id": appt_id, "patient_id": patient_id, "mode": mode,
                                "location_name": location_name, "reason": reason})
