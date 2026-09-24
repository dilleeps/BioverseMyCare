"""Billing & Coverage and Pharmacy demo data. Idempotent: fixed IDs 5000-5999, ON CONFLICT DO NOTHING.

Everything here is fictional. The payer is a "Demo payer": rules in our own tables, not a real insurer.
Drug information and interaction pairs are a small curated demo set, not clinical reference content.
"""

from __future__ import annotations

import json
from datetime import date

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_LINDQVIST, DR_OKAFOR, ORG, P_HADDAD, P_MAYA, P_PARK, PLAN, _id,
)

# --- Billing IDs (5000-5499) ------------------------------------------------------------------
COV_MAYA, COV_PARK, COV_HADDAD = _id(5001), _id(5002), _id(5003)
PRICE_IDS = {code: _id(5010 + i) for i, code in enumerate(["PCP_VISIT", "SPEC_VISIT", "ECHO", "LIPID", "TELEHEALTH"])}
CL_PHYSICAL, CL_LIPID_OLD, CL_LIPID_PREV, CL_CARDIO, CL_LIPID_NEW = _id(5101), _id(5102), _id(5103), _id(5104), _id(5105)
CL_HADDAD_VISIT, CL_HADDAD_ECHO = _id(5106), _id(5107)
ST_PHYSICAL, ST_LIPID_PREV, ST_CARDIO, ST_HADDAD_VISIT, ST_HADDAD_ECHO = (
    _id(5201), _id(5203), _id(5204), _id(5206), _id(5207)
)
PAY_PHYSICAL, PAY_LIPID_PREV = _id(5251), _id(5253)
FA_HADDAD = _id(5301)

# --- Pharmacy IDs (5500-5999) -----------------------------------------------------------------
PH_RIVERSIDE, PH_NORTHSIDE, PH_EASTGATE, PH_HARBOR = _id(5501), _id(5502), _id(5503), _id(5504)
RX_MAYA_ATORVA, RX_MAYA_AZITHRO, RX_HADDAD_AMLO = _id(5601), _id(5602), _id(5603)
DISP_ATORVA_1, DISP_AZITHRO_1, DISP_AMLO_1 = _id(5651), _id(5652), _id(5653)
REFILL_HADDAD, REVIEW_HADDAD_REFILL = _id(5701), _id(5702)

SERVICES = [
    # code, name, category, price, allowed (demo payer contracted rate)
    ("PCP_VISIT", "Primary care visit", "primary_care", 22000, 15000),
    ("SPEC_VISIT", "Specialist visit", "specialist", 38000, 26000),
    ("ECHO", "Echocardiogram", "imaging", 180000, 90000),
    ("LIPID", "Lipid panel", "lab", 9500, 4500),
    ("TELEHEALTH", "Telehealth visit", "telehealth", 12000, 8500),
]

COPAYS = {"primary_care": 2500, "specialist": 5000, "telehealth": 1500}

MONOGRAPHS = [
    (
        "atorvastatin", "Atorvastatin", "Statin (cholesterol-lowering)",
        "Lowers LDL cholesterol and helps reduce the chance of heart attack and stroke.",
        "Take once a day, at the same time each day, with or without food.",
        ["Muscle aches", "Diarrhea", "Joint pain", "Stuffy nose"],
        ["Unexplained muscle pain, tenderness or weakness, especially with fever or tiredness",
         "Dark or cola-colored urine", "Yellowing of the skin or eyes"],
    ),
    (
        "amlodipine", "Amlodipine", "Calcium channel blocker (blood pressure)",
        "Lowers blood pressure and can ease some kinds of chest pain.",
        "Take once a day, at the same time each day, with or without food.",
        ["Swollen ankles or feet", "Flushing", "Headache", "Dizziness"],
        ["Fainting or feeling like you might faint", "Chest pain that is new or worse",
         "Fast or pounding heartbeat"],
    ),
    (
        "azithromycin", "Azithromycin", "Antibiotic (macrolide)",
        "Treats certain bacterial infections. It does not work for colds or flu.",
        "Take exactly as prescribed and finish the whole course, even if you feel better.",
        ["Upset stomach", "Diarrhea", "Nausea"],
        ["Severe or watery diarrhea", "Fast or irregular heartbeat", "Rash, swelling or trouble breathing"],
    ),
    (
        "clarithromycin", "Clarithromycin", "Antibiotic (macrolide)",
        "Treats certain bacterial infections.",
        "Take exactly as prescribed and finish the whole course.",
        ["Upset stomach", "Change in taste", "Diarrhea"],
        ["Severe or watery diarrhea", "Fast or irregular heartbeat", "Rash, swelling or trouble breathing"],
    ),
    (
        "simvastatin", "Simvastatin", "Statin (cholesterol-lowering)",
        "Lowers LDL cholesterol and helps reduce the chance of heart attack and stroke.",
        "Usually taken once a day in the evening.",
        ["Muscle aches", "Constipation", "Headache"],
        ["Unexplained muscle pain, tenderness or weakness", "Dark or cola-colored urine"],
    ),
]

INTERACTIONS = [
    (_id(5521), "atorvastatin", "clarithromycin", None, "major",
     "Clarithromycin can raise the amount of atorvastatin in the blood, which increases the risk of muscle damage.",
     "Prescribers usually pause atorvastatin or choose a different antibiotic. Don't take both without checking with "
     "your prescriber or pharmacist."),
    (_id(5522), "atorvastatin", None, "Grapefruit juice", "advisory",
     "Large amounts of grapefruit juice can raise the amount of atorvastatin in the blood.",
     "Avoid drinking large amounts of grapefruit juice (more than about a litre a day). Ask your pharmacist if unsure."),
    (_id(5523), "amlodipine", "simvastatin", None, "moderate",
     "Amlodipine raises simvastatin levels. When the two are taken together the simvastatin dose is usually limited "
     "to 20 mg a day.",
     "Your prescriber may limit your simvastatin dose. Confirm the dose with your pharmacist."),
    (_id(5524), "simvastatin", "clarithromycin", None, "major",
     "Clarithromycin greatly raises simvastatin levels and the risk of serious muscle damage.",
     "These are not usually taken together. Check with your prescriber before starting the antibiotic."),
]


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()

    # --- Billing: price list ---------------------------------------------------------------
    cur.executemany(
        """
        INSERT INTO service_prices (id, organization_id, code, name, category, price_cents, allowed_cents)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(PRICE_IDS[s[0]], ORG, *s) for s in SERVICES],
    )

    # --- Coverage ---------------------------------------------------------------------------
    plan_start = date(ctx.today.year - 2, 1, 1)
    coverages = [
        # id, patient, member id, group, start, end, ded, ded met, oop, oop met
        (COV_MAYA, P_MAYA, "NHP-4821-7730", "NS-1001", plan_start, None, 150000, 42000, 400000, 61500),
        (COV_PARK, P_PARK, "NHP-5530-1189", "NS-1001", plan_start, days(-30), 150000, 0, 400000, 0),
        (COV_HADDAD, P_HADDAD, "NHP-3307-2254", "NS-1001", plan_start, None, 100000, 100000, 300000, 147000),
    ]
    cur.executemany(
        """
        INSERT INTO coverages (id, patient_id, payer_name, plan_name, member_id, group_number, effective_start,
                               effective_end, deductible_cents, deductible_met_cents, oop_max_cents, oop_met_cents,
                               coinsurance_pct, oon_coinsurance_pct, copays)
        VALUES (%s, %s, 'Demo payer', %s, %s, %s, %s, %s, %s, %s, %s, %s, 20, 40, %s)
        ON CONFLICT DO NOTHING
        """,
        [(c[0], c[1], PLAN, *c[2:], json.dumps(COPAYS)) for c in coverages],
    )

    # --- Claims, EOBs, statements, payments --------------------------------------------------
    claims = [
        # id, patient, coverage, practitioner, code, name, category, service day, billed, status, denial
        (CL_PHYSICAL, P_MAYA, COV_MAYA, DR_LINDQVIST, "PCP_VISIT", "Annual physical (primary care visit)",
         "primary_care", -194, 22000, "paid", None),
        (CL_LIPID_OLD, P_MAYA, COV_MAYA, DR_LINDQVIST, "LIPID", "Lipid panel", "lab", -560, 9500, "denied",
         "Diagnosis code missing from the claim. Northside billing can correct and resubmit it, or you can appeal."),
        (CL_LIPID_PREV, P_MAYA, COV_MAYA, DR_LINDQVIST, "LIPID", "Lipid panel", "lab", -367, 9500, "paid", None),
        (CL_CARDIO, P_MAYA, COV_MAYA, DR_OKAFOR, "SPEC_VISIT", "Cardiology visit (specialist visit)",
         "specialist", -2, 38000, "paid", None),
        (CL_LIPID_NEW, P_MAYA, COV_MAYA, DR_OKAFOR, "LIPID", "Lipid panel", "lab", -2, 9500, "in_review", None),
        (CL_HADDAD_VISIT, P_HADDAD, COV_HADDAD, DR_OKAFOR, "SPEC_VISIT", "Cardiology visit (specialist visit)",
         "specialist", -8, 38000, "paid", None),
        (CL_HADDAD_ECHO, P_HADDAD, COV_HADDAD, DR_OKAFOR, "ECHO", "Echocardiogram", "imaging", -20, 180000, "paid", None),
    ]
    cur.executemany(
        """
        INSERT INTO claims (id, patient_id, coverage_id, practitioner_id, service_code, service_name, category,
                            service_date, billed_cents, status, denial_reason, submitted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(*c[:7], days(c[7]), c[8], c[9], c[10], at(days(c[7] + 1), 9)) for c in claims],
    )

    eobs = [
        # id, claim, patient, allowed, plan paid, copay, deductible, coinsurance, patient resp, day
        (_id(5151), CL_PHYSICAL, P_MAYA, 15000, 12500, 2500, 0, 0, 2500, -185),
        (_id(5153), CL_LIPID_PREV, P_MAYA, 4500, 0, 0, 4500, 0, 4500, -360),
        (_id(5154), CL_CARDIO, P_MAYA, 26000, 21000, 5000, 0, 0, 5000, -1),
        (_id(5156), CL_HADDAD_VISIT, P_HADDAD, 26000, 21000, 5000, 0, 0, 5000, -6),
        # Rana had 30000 of deductible left: 30000 + 20% of the remaining 60000.
        (_id(5157), CL_HADDAD_ECHO, P_HADDAD, 90000, 48000, 0, 30000, 12000, 42000, -15),
    ]
    cur.executemany(
        """
        INSERT INTO explanation_of_benefits (id, claim_id, patient_id, allowed_cents, plan_paid_cents, copay_cents,
                                             deductible_cents, coinsurance_cents, patient_resp_cents, adjudicated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(*e[:9], at(days(e[9]), 10)) for e in eobs],
    )

    statements = [
        (ST_PHYSICAL, P_MAYA, CL_PHYSICAL, 2500, -184, -154),
        (ST_LIPID_PREV, P_MAYA, CL_LIPID_PREV, 4500, -359, -329),
        (ST_CARDIO, P_MAYA, CL_CARDIO, 5000, -1, 29),
        (ST_HADDAD_VISIT, P_HADDAD, CL_HADDAD_VISIT, 5000, -5, 25),
        (ST_HADDAD_ECHO, P_HADDAD, CL_HADDAD_ECHO, 42000, -14, 16),
    ]
    cur.executemany(
        """
        INSERT INTO patient_statements (id, patient_id, claim_id, amount_cents, issued_on, due_on)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(s[0], s[1], s[2], s[3], days(s[4]), days(s[5])) for s in statements],
    )
    cur.executemany(
        """
        INSERT INTO payments (id, patient_id, statement_id, amount_cents, receipt_number, created_at)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (PAY_PHYSICAL, P_MAYA, ST_PHYSICAL, 2500, "R-DEMO-5251", at(days(-170), 18, 5)),
            (PAY_LIPID_PREV, P_MAYA, ST_LIPID_PREV, 4500, "R-DEMO-5253", at(days(-340), 12, 40)),
        ],
    )
    cur.execute(
        """
        INSERT INTO financial_assistance_applications (id, patient_id, household_size, income_band, attestations, created_at)
        VALUES (%s, %s, 2, '200_300_fpl', %s, %s) ON CONFLICT DO NOTHING
        """,
        (FA_HADDAD, P_HADDAD, json.dumps({"information_accurate": True, "will_report_changes": True}),
         at(days(-3), 16, 20)),
    )

    # --- Pharmacy directory -----------------------------------------------------------------
    cur.executemany(
        """
        INSERT INTO pharmacies (id, name, address, phone, hours, distance_km, open_24_hours)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (PH_RIVERSIDE, "Riverside Pharmacy", "14 River Road", "(555) 010-2231", "Mon-Sat 8am-9pm, Sun 10am-6pm", 1.2, False),
            (PH_NORTHSIDE, "Northside Community Pharmacy", "200 Northside Avenue", "(555) 010-4410",
             "Mon-Fri 8am-8pm, Sat 9am-5pm", 2.1, False),
            (PH_EASTGATE, "Eastgate 24-Hour Pharmacy", "5 Eastgate Plaza", "(555) 010-8800", "Open 24 hours", 6.0, True),
            (PH_HARBOR, "Harbor Street Apothecary", "88 Harbor Street", "(555) 010-3172", "Mon-Fri 9am-6pm", 3.7, False),
        ],
    )
    cur.executemany(
        "INSERT INTO patient_pharmacy_preferences (patient_id, pharmacy_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [(P_MAYA, PH_RIVERSIDE), (P_HADDAD, PH_NORTHSIDE)],
    )

    # --- Curated drug information and interaction pairs --------------------------------------
    cur.executemany(
        """
        INSERT INTO drug_monographs (code, name, drug_class, uses, how_to_take, common_side_effects, call_doctor_if)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        MONOGRAPHS,
    )
    cur.executemany(
        """
        INSERT INTO drug_interactions (id, drug_a, drug_b, substance, severity, summary, advice)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        INTERACTIONS,
    )

    # --- Prescriptions and fills ------------------------------------------------------------
    cur.executemany(
        """
        INSERT INTO medication_requests (id, patient_id, prescriber_id, drug_code, drug_name, strength, sig, quantity,
                                         refills_authorized, refills_remaining, status, pharmacy_id, authored_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (RX_MAYA_ATORVA, P_MAYA, DR_OKAFOR, "atorvastatin", "Atorvastatin", "20 mg",
             "Take 1 tablet by mouth once daily in the evening.", 30, 5, 5, "active", PH_RIVERSIDE, at(days(-2), 9, 35)),
            (RX_MAYA_AZITHRO, P_MAYA, DR_LINDQVIST, "azithromycin", "Azithromycin", "250 mg",
             "Take 2 tablets on day 1, then 1 tablet daily for 4 days.", 6, 0, 0, "completed", PH_RIVERSIDE,
             at(days(-420), 10, 15)),
            (RX_HADDAD_AMLO, P_HADDAD, DR_OKAFOR, "amlodipine", "Amlodipine", "5 mg",
             "Take 1 tablet by mouth once daily.", 14, 0, 0, "active", PH_NORTHSIDE, at(days(-8), 11, 0)),
        ],
    )
    cur.executemany(
        """
        INSERT INTO medication_dispenses (id, medication_request_id, patient_id, pharmacy_id, fill_number, status,
                                          sent_at, ready_at, picked_up_at)
        VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (DISP_ATORVA_1, RX_MAYA_ATORVA, P_MAYA, PH_RIVERSIDE, "ready", at(days(-2), 9, 36), at(days(-1), 15, 10), None),
            (DISP_AZITHRO_1, RX_MAYA_AZITHRO, P_MAYA, PH_RIVERSIDE, "picked_up", at(days(-420), 10, 16),
             at(days(-420), 12, 30), at(days(-420), 17, 45)),
            (DISP_AMLO_1, RX_HADDAD_AMLO, P_HADDAD, PH_NORTHSIDE, "picked_up", at(days(-8), 11, 1),
             at(days(-8), 14, 0), at(days(-8), 17, 20)),
        ],
    )

    # Rana's two-week trial supply has no refills: her request waits for Dr. Okafor.
    cur.execute(
        """
        INSERT INTO review_items (id, kind, patient_id, practitioner_id, ref_id, title, body, priority, link, created_at)
        VALUES (%s, 'refill_request', %s, %s, %s, %s, %s, 'routine', '/clinician/refills', %s)
        ON CONFLICT DO NOTHING
        """,
        (REVIEW_HADDAD_REFILL, P_HADDAD, DR_OKAFOR, REFILL_HADDAD, "Refill request · Amlodipine 5 mg",
         "No refills remaining on a 14-tablet trial supply. Patient asks to continue. "
         "Patient-logged adherence is low this week.", at(days(0), 7, 30)),
    )
    cur.execute(
        """
        INSERT INTO refill_requests (id, medication_request_id, patient_id, prescriber_id, pharmacy_id, status,
                                     patient_note, review_item_id, created_at)
        VALUES (%s, %s, %s, %s, %s, 'pending_approval', %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (REFILL_HADDAD, RX_HADDAD_AMLO, P_HADDAD, DR_OKAFOR, PH_NORTHSIDE,
         "Running low. I'd like to keep taking it.", REVIEW_HADDAD_REFILL, at(days(0), 7, 30)),
    )

    # Rana's logged doses since pickup: some missed days.
    cur.executemany(
        """
        INSERT INTO medication_adherence_logs (id, medication_request_id, patient_id, taken_on, logged_at)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(_id(5800 + i), RX_HADDAD_AMLO, P_HADDAD, days(d), at(days(d), 20)) for i, d in enumerate([-8, -7, -6, -4, -1])],
    )
