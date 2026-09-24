"""Evidence library and demo research studies. IDs 7000-7999. Idempotent.

Evidence snippets are short paraphrases of public guidance, each linked to its public source.
They are demo content: clinical governance must re-verify every snippet against its source,
and replace the library with a licensed, maintained index, before any real clinical use.

Every research study here is fictional and titled "Demo study" so no one mistakes it for a real trial.
"""

from __future__ import annotations

import json
from datetime import date

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import P_PARK, U_PARK, _id

LDL, TC, HDL, TG, A1C = "13457-7", "2093-3", "2085-9", "2571-8", "4548-4"
SBP, DBP = "8480-6", "8462-4"
LABEL_CHECKED = date(2026, 9, 1)

# (n, title, publisher, url, published_on, date_kind, type, quality, quality_note, specialties, loinc, keywords, snippet)
EVIDENCE = [
    (7001,
     "Statin Use for the Primary Prevention of Cardiovascular Disease in Adults: Preventive Medication",
     "US Preventive Services Task Force",
     "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/statin-use-in-adults-preventive-medication",
     date(2022, 8, 23), "published", "guideline", "high", "USPSTF grade B / C",
     ["Cardiology", "Primary care"], [LDL, TC],
     "statin primary prevention LDL cholesterol dyslipidemia cardiovascular risk atorvastatin",
     "Prescribe a statin for primary prevention of cardiovascular disease in adults aged 40 to 75 years who have "
     "one or more risk factors (dyslipidemia, diabetes, hypertension or smoking) and an estimated 10-year CVD risk "
     "of 10% or greater (grade B). Selectively offer a statin to adults aged 40 to 75 with one or more risk factors "
     "and a 10-year risk of 7.5% to less than 10% (grade C). Evidence is insufficient for adults 76 years or older."),
    (7002,
     "2018 AHA/ACC Guideline on the Management of Blood Cholesterol: primary prevention",
     "American Heart Association / American College of Cardiology",
     "https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
     date(2018, 11, 10), "published", "guideline", "high", "Class I recommendations",
     ["Cardiology", "Primary care"], [LDL, TC],
     "statin LDL cholesterol primary prevention ASCVD risk moderate-intensity high-intensity atorvastatin",
     "For adults 40 to 75 years without diabetes and with LDL-C of 70 mg/dL or higher, a 10-year ASCVD risk of "
     "7.5% to less than 20% (intermediate risk) supports starting a moderate-intensity statin after a clinician-patient "
     "risk discussion. Adults with LDL-C of 190 mg/dL or higher should receive a high-intensity statin without risk "
     "calculation. Adults 40 to 75 with diabetes should receive a moderate-intensity statin."),
    (7003,
     "2018 AHA/ACC Guideline on the Management of Blood Cholesterol: risk-enhancing factors and coronary calcium",
     "American Heart Association / American College of Cardiology",
     "https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
     date(2018, 11, 10), "published", "guideline", "high", "Class IIa-IIb recommendations",
     ["Cardiology", "Primary care"], [LDL, TC, TG],
     "risk enhancers family history coronary artery calcium CAC score statin decision LDL 160 lipoprotein(a)",
     "In borderline or intermediate-risk adults, risk-enhancing factors favor starting a statin. They include a "
     "family history of premature ASCVD, persistently elevated LDL-C of 160 mg/dL or higher, metabolic syndrome, "
     "chronic kidney disease, chronic inflammatory conditions, and elevated lipoprotein(a) or apoB. When the statin "
     "decision is uncertain, a coronary artery calcium score can help: a score of zero makes it reasonable to "
     "withhold a statin in many patients, and a score of 100 or higher favors starting one."),
    (7004,
     "2018 AHA/ACC Guideline on the Management of Blood Cholesterol: monitoring response to therapy",
     "American Heart Association / American College of Cardiology",
     "https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
     date(2018, 11, 10), "published", "guideline", "high", "Class I recommendation",
     ["Cardiology", "Primary care"], [LDL],
     "statin monitoring lipid panel recheck follow-up adherence LDL response 4 to 12 weeks",
     "Assess adherence and the percentage LDL-C response with a fasting or nonfasting lipid panel 4 to 12 weeks "
     "after starting a statin or changing the dose, and every 3 to 12 months thereafter as needed. A "
     "moderate-intensity statin typically lowers LDL-C by 30% to 49% and a high-intensity statin by 50% or more."),
    (7005,
     "Efficacy and safety of more intensive lowering of LDL cholesterol: meta-analysis of 170,000 participants "
     "in 26 randomised trials",
     "Cholesterol Treatment Trialists' Collaboration (The Lancet)",
     "https://pubmed.ncbi.nlm.nih.gov/21067804/",
     date(2010, 11, 13), "published", "systematic_review", "high", "Individual-participant meta-analysis of RCTs",
     ["Cardiology"], [LDL],
     "statin LDL lowering major vascular events meta-analysis benefit",
     "Across 26 randomised statin trials, each 1.0 mmol/L (about 39 mg/dL) reduction in LDL cholesterol reduced "
     "the annual rate of major vascular events by about a fifth (rate ratio about 0.78), with no evidence of a "
     "threshold within the cholesterol range studied."),
    (7006,
     "Atorvastatin calcium tablets: prescribing information, adverse reactions",
     "US National Library of Medicine, DailyMed",
     "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=atorvastatin",
     LABEL_CHECKED, "label_checked", "drug_label", "high", "FDA-approved labeling",
     ["Cardiology", "Primary care"], [LDL],
     "atorvastatin Lipitor side effects adverse reactions statin",
     "The most common adverse reactions to atorvastatin (incidence of 5% or more) are nasopharyngitis, arthralgia, "
     "diarrhea, pain in extremity and urinary tract infection. Increases in HbA1c and fasting glucose have been "
     "reported with statins."),
    (7007,
     "Atorvastatin calcium tablets: prescribing information, myopathy and liver warnings",
     "US National Library of Medicine, DailyMed",
     "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=atorvastatin",
     LABEL_CHECKED, "label_checked", "drug_label", "high", "FDA-approved labeling",
     ["Cardiology", "Primary care"], [],
     "atorvastatin statin myopathy rhabdomyolysis muscle pain weakness CK liver enzymes",
     "Atorvastatin can cause myopathy and rhabdomyolysis. Risk is higher at higher doses, in patients 65 or older, "
     "with uncontrolled hypothyroidism or renal impairment, and with certain interacting drugs. Patients should "
     "promptly report unexplained muscle pain, tenderness or weakness; discontinue if CK is markedly elevated or "
     "myopathy is suspected. Consider liver enzyme testing before starting and when clinically indicated."),
    (7008,
     "Amlodipine besylate tablets: prescribing information, adverse reactions and hypotension",
     "US National Library of Medicine, DailyMed",
     "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=amlodipine",
     LABEL_CHECKED, "label_checked", "drug_label", "high", "FDA-approved labeling",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "amlodipine Norvasc calcium channel blocker side effects dizziness edema swelling flushing palpitations hypotension",
     "Peripheral edema is the most common adverse reaction to amlodipine and is dose related (about 10.8% at 10 mg "
     "versus 0.6% with placebo). Dizziness, flushing, palpitations and fatigue are also reported. Symptomatic "
     "hypotension is possible, particularly in patients with severe aortic stenosis, although acute hypotension is "
     "unlikely because the drug's onset is gradual."),
    (7009,
     "2017 ACC/AHA Guideline for High Blood Pressure in Adults: blood pressure categories",
     "American College of Cardiology / American Heart Association",
     "https://www.ahajournals.org/doi/10.1161/HYP.0000000000000065",
     date(2017, 11, 13), "published", "guideline", "high", "Class I recommendations",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "hypertension blood pressure thresholds stage 1 stage 2 elevated home monitoring diagnosis",
     "Blood pressure is categorized as normal (below 120/80 mm Hg), elevated (120-129 systolic and below 80 "
     "diastolic), stage 1 hypertension (130-139 systolic or 80-89 diastolic) and stage 2 hypertension (140 or higher "
     "systolic or 90 or higher diastolic). Classify using the average of two or more readings on two or more "
     "occasions, and use home or ambulatory readings to confirm the diagnosis."),
    (7010,
     "2017 ACC/AHA Guideline for High Blood Pressure in Adults: when to start medication",
     "American College of Cardiology / American Heart Association",
     "https://www.ahajournals.org/doi/10.1161/HYP.0000000000000065",
     date(2017, 11, 13), "published", "guideline", "high", "Class I recommendations",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "hypertension treatment threshold antihypertensive medication target 130/80 ASCVD risk",
     "Start blood-pressure-lowering medication for stage 1 hypertension when the patient has clinical cardiovascular "
     "disease or a 10-year ASCVD risk of 10% or higher, and for all adults with stage 2 hypertension, alongside "
     "lifestyle changes. A target below 130/80 mm Hg is recommended for most of these adults."),
    (7011,
     "Hypertension in Adults: Screening",
     "US Preventive Services Task Force",
     "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/hypertension-in-adults-screening",
     date(2021, 4, 27), "published", "guideline", "high", "USPSTF grade A",
     ["Primary care", "Cardiology"], [SBP, DBP],
     "hypertension screening blood pressure office measurement home confirmation",
     "Screen for hypertension in adults 18 years or older with office blood pressure measurement (grade A), and "
     "obtain measurements outside the clinical setting to confirm the diagnosis before starting treatment."),
    (7012,
     "Standards of Care in Diabetes 2025, Section 2: Diagnosis and Classification of Diabetes",
     "American Diabetes Association (Diabetes Care)",
     "https://doi.org/10.2337/dc25-S002",
     date(2024, 12, 9), "published", "guideline", "high", "ADA evidence grades A-E",
     ["Primary care", "Endocrinology"], [A1C],
     "prediabetes diabetes diagnosis HbA1c A1C 5.7 6.4 fasting glucose criteria",
     "Prediabetes is defined by an HbA1c of 5.7% to 6.4% (39-47 mmol/mol), a fasting plasma glucose of 100-125 "
     "mg/dL, or a 2-hour glucose of 140-199 mg/dL during an oral glucose tolerance test. Diabetes is diagnosed at an "
     "HbA1c of 6.5% or higher, confirmed by repeat testing unless hyperglycemia is unequivocal. Conditions that "
     "change red cell turnover, such as anemia, hemoglobinopathies or pregnancy, can make HbA1c unreliable."),
    (7013,
     "Standards of Care in Diabetes 2025, Section 3: Prevention or Delay of Diabetes",
     "American Diabetes Association (Diabetes Care)",
     "https://doi.org/10.2337/dc25-S003",
     date(2024, 12, 9), "published", "guideline", "high", "ADA grade A-B recommendations",
     ["Primary care", "Endocrinology"], [A1C],
     "prediabetes prevention lifestyle program weight loss physical activity metformin monitoring HbA1c",
     "Refer adults with prediabetes and overweight or obesity to an intensive lifestyle program modeled on the "
     "Diabetes Prevention Program, aiming for at least 7% weight loss and at least 150 minutes a week of "
     "moderate-intensity activity. Consider metformin, especially for adults aged 25 to 59 with a BMI of 35 or "
     "higher, higher fasting glucose or HbA1c, or prior gestational diabetes. Monitor for progression at least yearly."),
    (7014,
     "Reduction in the incidence of type 2 diabetes with lifestyle intervention or metformin (Diabetes Prevention Program)",
     "Diabetes Prevention Program Research Group (New England Journal of Medicine)",
     "https://pubmed.ncbi.nlm.nih.gov/11832527/",
     date(2002, 2, 7), "published", "rct", "high", "Large multicentre randomised trial",
     ["Primary care", "Endocrinology"], [A1C],
     "prediabetes lifestyle intervention metformin diabetes prevention randomised trial",
     "In adults with elevated fasting and post-load glucose, an intensive lifestyle intervention reduced the "
     "incidence of type 2 diabetes by 58% and metformin by 31% compared with placebo over an average follow-up of "
     "2.8 years."),
    (7015,
     "Screening for Prediabetes and Type 2 Diabetes",
     "US Preventive Services Task Force",
     "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/screening-for-prediabetes-and-type-2-diabetes",
     date(2021, 8, 24), "published", "guideline", "high", "USPSTF grade B",
     ["Primary care"], [A1C],
     "prediabetes diabetes screening overweight obesity HbA1c",
     "Screen for prediabetes and type 2 diabetes in adults aged 35 to 70 years who have overweight or obesity "
     "(grade B), and offer or refer patients with prediabetes to effective preventive interventions."),
    (7016,
     "2021 AHA/ACC Guideline for the Evaluation and Diagnosis of Chest Pain",
     "American Heart Association / American College of Cardiology",
     "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001029",
     date(2021, 10, 28), "published", "guideline", "high", "Class I recommendations",
     ["Cardiology", "Emergency medicine"], [],
     "chest pain discomfort evaluation risk stratification atypical noncardiac emergency",
     "Chest pain includes pressure, tightness or discomfort in the chest, shoulders, arms, neck, back, upper abdomen "
     "or jaw. Describe it as cardiac, possibly cardiac or noncardiac rather than 'atypical'. Patients with acute chest "
     "pain should seek emergency care, and structured risk assessment should guide further testing."),
]

# Structured eligibility. See bioverse/trials.py for criterion shapes.
STUDIES = [
    {
        "n": 7101,
        "short_title": "LOWER-LDL",
        "title": "Demo study: LOWER-LDL, a daily walking and diet coaching program for high LDL cholesterol",
        "sponsor": "Northside Health Research Institute (fictional)",
        "phase": "Not applicable (behavioral)",
        "status": "recruiting",
        "conditions": ["High LDL cholesterol"],
        "summary": "This fictional demo study tests whether 12 weeks of phone coaching on walking and eating habits "
                   "lowers LDL cholesterol more than usual care, for adults whose LDL is above target.",
        "what_happens": "Three clinic visits over 12 weeks, two blood tests, and a short weekly coaching call.",
        "sites": [{"name": "Northside Heart Centre", "city": "Northside", "distance_km": 3.4}],
        "contact": {"name": "Demo research coordinator", "phone": "555-0170", "email": "research@northside.example"},
        "eligibility": {
            "age": {"min": 45, "max": 75},
            "sex": "any",
            "include": [
                {"id": "ldl", "kind": "lab", "loinc": LDL, "min": 130, "unit": "mg/dL", "within_days": 365,
                 "if_missing": "fail", "label": "LDL cholesterol of 130 mg/dL or higher in the last 12 months"},
            ],
            "exclude": [
                {"id": "long_statin", "kind": "medication", "match": "statin", "min_days": 180, "if_missing": "pass",
                 "label": "Taking a statin for more than 6 months"},
            ],
        },
    },
    {
        "n": 7102,
        "short_title": "HOME-BP",
        "title": "Demo study: HOME-BP, home blood pressure monitoring with pharmacist check-ins",
        "sponsor": "Riverside Medical Centre (fictional)",
        "phase": "Not applicable (care delivery)",
        "status": "recruiting",
        "conditions": ["High blood pressure", "Heart health"],
        "summary": "This fictional demo study looks at whether measuring your blood pressure at home, with a monthly "
                   "call from a pharmacist, helps people keep their blood pressure in a healthy range.",
        "what_happens": "You get a home blood pressure cuff, take readings twice a week, and have a monthly call "
                        "for six months.",
        "sites": [{"name": "Riverside Medical Centre", "city": "Riverside", "distance_km": 4.8}],
        "contact": {"name": "Demo research coordinator", "phone": "555-0171", "email": "bp-study@riverside.example"},
        "eligibility": {
            "age": {"min": 45, "max": 80},
            "sex": "any",
            "include": [
                {"id": "sbp", "kind": "lab", "loinc": SBP, "min": 130, "unit": "mm Hg", "within_days": 365,
                 "if_missing": "unknown", "label": "Systolic blood pressure of 130 mm Hg or higher in the last 12 months"},
            ],
            "exclude": [
                {"id": "pregnancy", "kind": "not_recorded", "label": "Pregnant or planning a pregnancy",
                 "note": "Not recorded in Bioverse; the study team asks at screening."},
            ],
        },
    },
    {
        "n": 7103,
        "short_title": "PREVENT-T2D",
        "title": "Demo study: PREVENT-T2D, a group lifestyle program for prediabetes",
        "sponsor": "Eastgate Community Health (fictional)",
        "phase": "Not applicable (behavioral)",
        "status": "recruiting",
        "conditions": ["Prediabetes"],
        "summary": "This fictional demo study compares a 16-week group program on food, activity and sleep with "
                   "written advice alone, for adults whose blood sugar is a little above the normal range.",
        "what_happens": "Weekly group sessions for 16 weeks (in person or video), then two follow-up blood tests "
                        "over a year.",
        "sites": [
            {"name": "Eastgate Family Practice", "city": "Eastgate", "distance_km": 6.2},
            {"name": "Video sessions", "city": "Online", "distance_km": 0},
        ],
        "contact": {"name": "Demo research coordinator", "phone": "555-0172", "email": "prevent@eastgate.example"},
        "eligibility": {
            "age": {"min": 30, "max": 65},
            "sex": "any",
            "include": [
                {"id": "a1c", "kind": "lab", "loinc": A1C, "min": 5.7, "max": 6.4, "unit": "%", "within_days": 365,
                 "if_missing": "fail", "label": "HbA1c between 5.7% and 6.4% in the last 12 months"},
            ],
            "exclude": [
                {"id": "diabetes_meds", "kind": "medication", "match": "diabetes", "if_missing": "pass",
                 "label": "Already taking a diabetes medicine"},
            ],
        },
    },
    {
        "n": 7104,
        "short_title": "STATIN-SWITCH",
        "title": "Demo study: STATIN-SWITCH, comparing two statin schedules for people with muscle aches",
        "sponsor": "Northside Health Research Institute (fictional)",
        "phase": "Phase 4",
        "status": "recruiting",
        "conditions": ["High LDL cholesterol", "Statin side effects"],
        "summary": "This fictional demo study compares taking a statin every day with taking it every other day, "
                   "for people who have been on a statin for a while and have muscle aches.",
        "what_happens": "Four clinic visits over six months, with blood tests and a short symptom diary.",
        "sites": [{"name": "Northside Heart Centre", "city": "Northside", "distance_km": 3.4}],
        "contact": {"name": "Demo research coordinator", "phone": "555-0170", "email": "research@northside.example"},
        "eligibility": {
            "age": {"min": 18, "max": 80},
            "sex": "any",
            "include": [
                {"id": "on_statin", "kind": "medication", "match": "statin", "min_days": 180, "if_missing": "fail",
                 "label": "Taking a statin for at least 6 months"},
            ],
            "exclude": [],
        },
    },
    {
        "n": 7105,
        "short_title": "HEART-KITCHEN",
        "title": "Demo study: HEART-KITCHEN, a cooking class registry",
        "sponsor": "Northside Health Research Institute (fictional)",
        "phase": "Observational",
        "status": "completed",
        "conditions": ["Heart health"],
        "summary": "This fictional demo study followed people who took heart-healthy cooking classes. It has "
                   "finished and is no longer recruiting.",
        "what_happens": "Enrollment has closed.",
        "sites": [{"name": "Northside Clinic", "city": "Northside", "distance_km": 2.1}],
        "contact": {"name": "Demo research coordinator", "phone": "555-0170", "email": "research@northside.example"},
        "eligibility": {"age": {"min": 18, "max": 90}, "sex": "any", "include": [], "exclude": []},
    },
]

JUN_INTEREST = _id(7201)


def run(conn, ctx: SeedContext) -> None:
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO evidence_items (id, title, publisher, url, published_on, date_kind, evidence_type, quality,
                                    quality_note, specialties, loinc_codes, keywords, snippet)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [(_id(e[0]), *e[1:]) for e in EVIDENCE],
    )
    cur.executemany(
        """
        INSERT INTO research_studies (id, title, short_title, sponsor, phase, status, conditions, summary,
                                      what_happens, sites, contact, eligibility, is_demo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
        ON CONFLICT (id) DO NOTHING
        """,
        [
            (_id(s["n"]), s["title"], s["short_title"], s["sponsor"], s["phase"], s["status"], s["conditions"],
             s["summary"], s["what_happens"], json.dumps(s["sites"]), json.dumps(s["contact"]),
             json.dumps(s["eligibility"]))
            for s in STUDIES
        ],
    )

    # Jun Park has opted in to research matching and asked about the prediabetes study, so the
    # coordinator pipeline has something to show. Maya has not opted in: she decides in the app.
    inserted = cur.execute(
        """
        INSERT INTO consents (patient_id, scope, status, detail, updated_by)
        VALUES (%s, 'research_matching', 'granted', %s, %s)
        ON CONFLICT (patient_id, scope, grantee) DO NOTHING
        RETURNING id
        """,
        (P_PARK, json.dumps({"source": "demo seed"}), U_PARK),
    ).fetchone()
    if inserted:
        at = ctx.at(ctx.days(-3), 18, 5)
        cur.execute(
            """
            INSERT INTO research_subjects (id, study_id, patient_id, status, history, created_at, updated_at)
            VALUES (%s, %s, %s, 'interested', %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (JUN_INTEREST, _id(7103), P_PARK,
             json.dumps([{"status": "interested", "at": at.isoformat(), "by_role": "patient", "note": None}]), at, at),
        )
