"""Public learning: the medical-student demo user, fact-check evidence and claim reviews, public specialist
agents, and de-identified teaching cases. IDs 16000-16999. Idempotent.

Evidence rows are short, accurate paraphrases of well-known public sources, each linked to its source.
As with the core library (s070), clinical governance must re-verify them before any real use.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from psycopg.rows import dict_row

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import DR_OKAFOR, DR_WEISS, ORG, P_HADDAD, P_MAYA, P_PARK, U_MAYA, _id

U_STUDENT = _id(16001)
AGENT_OKAFOR, AGENT_WEISS = _id(16101), _id(16102)
SBP, DBP = "8480-6", "8462-4"

# (n, title, publisher, url, published_on, type, quality, quality_note, specialties, loinc, keywords, snippet)
EVIDENCE = [
    (16011,
     "Vaccines for measles, mumps, rubella, and varicella in children",
     "Cochrane Database of Systematic Reviews (Di Pietrantonj et al.)",
     "https://www.cochranelibrary.com/cdsr/doi/10.1002/14651858.CD004407.pub4/full",
     date(2020, 4, 20), "systematic_review", "high", "Cochrane systematic review",
     ["Primary care", "Pediatrics"], [],
     "vaccine vaccines vaccination MMR measles mumps rubella varicella autism autistic safety children immunization",
     "A Cochrane review of 138 studies involving about 23 million children found no evidence of an association "
     "between MMR vaccination and autism. The review concluded that the existing evidence on the safety and "
     "effectiveness of MMR vaccines supports their use for mass immunisation."),
    (16012,
     "Vaccines are not associated with autism: an evidence-based meta-analysis of case-control and cohort studies",
     "Vaccine (Taylor, Swerdfeger and Eslick)",
     "https://pubmed.ncbi.nlm.nih.gov/24814559/",
     date(2014, 6, 17), "systematic_review", "moderate", "Meta-analysis of observational studies",
     ["Primary care", "Pediatrics"], [],
     "vaccine vaccines vaccination autism autistic MMR thimerosal mercury children",
     "A meta-analysis of five cohort studies (more than 1.2 million children) and five case-control studies found "
     "no relationship between vaccination and autism, and none for MMR, thimerosal or mercury specifically."),
    (16013,
     "Garlic for the prevention of cardiovascular morbidity and mortality in hypertensive patients",
     "Cochrane Database of Systematic Reviews (Stabler et al.)",
     "https://www.cochranelibrary.com/cdsr/doi/10.1002/14651858.CD007653.pub2/full",
     date(2012, 8, 15), "systematic_review", "moderate", "Cochrane systematic review of few, small trials",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "garlic supplement hypertension blood pressure cardiovascular mortality herbal remedy",
     "A Cochrane review found insufficient evidence to determine whether garlic reduces deaths or cardiovascular "
     "events in people with hypertension. Two small trials reported lower blood pressure with garlic than with "
     "placebo, but the evidence was too limited to recommend garlic as a treatment."),
    (16014,
     "Garlic lowers blood pressure in hypertensive individuals, regulates serum cholesterol, and stimulates "
     "immunity: an updated meta-analysis and review",
     "The Journal of Nutrition (Ried)",
     "https://pubmed.ncbi.nlm.nih.gov/26764326/",
     date(2016, 2, 1), "systematic_review", "moderate", "Meta-analysis of randomized trials",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "garlic supplement aged garlic extract hypertension blood pressure cholesterol",
     "In a meta-analysis of randomized trials, garlic supplements lowered systolic blood pressure by about 8 mm Hg "
     "and diastolic by about 5 mm Hg on average in people with hypertension. Most trials were small and lasted a "
     "few months."),
    (16015,
     "2017 ACC/AHA Guideline for High Blood Pressure in Adults: nonpharmacological interventions",
     "American College of Cardiology / American Heart Association",
     "https://www.ahajournals.org/doi/10.1161/HYP.0000000000000065",
     date(2017, 11, 13), "guideline", "high", "Class I recommendation",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "exercise physical activity aerobic walking blood pressure hypertension lifestyle nonpharmacological",
     "Increased physical activity with a structured exercise program is recommended for adults with elevated blood "
     "pressure or hypertension. Aerobic activity for 90 to 150 minutes a week is expected to lower systolic blood "
     "pressure by about 5 to 8 mm Hg in adults with hypertension and 2 to 4 mm Hg in adults with normal blood pressure."),
    (16016,
     "Physical Activity Guidelines for Americans, 2nd edition",
     "US Department of Health and Human Services",
     "https://health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines/current-guidelines",
     date(2018, 11, 12), "guideline", "high", "Federal guideline",
     ["Primary care", "Cardiology"], [SBP, DBP],
     "physical activity exercise walking brisk aerobic minutes week blood pressure hypertension adults",
     "Adults should do at least 150 to 300 minutes a week of moderate-intensity aerobic activity, such as brisk "
     "walking. Regular physical activity lowers blood pressure in adults with hypertension and reduces the risk of "
     "developing high blood pressure."),
    (16017,
     "Exercise training for blood pressure: a systematic review and meta-analysis",
     "Journal of the American Heart Association (Cornelissen and Smart)",
     "https://pubmed.ncbi.nlm.nih.gov/23525435/",
     date(2013, 2, 1), "systematic_review", "high", "Meta-analysis of 93 randomized trials",
     ["Cardiology", "Primary care"], [SBP, DBP],
     "exercise training aerobic endurance walking blood pressure hypertension",
     "Across 93 randomized trials, aerobic endurance training lowered systolic blood pressure by about 3.5 mm Hg on "
     "average, and by about 8.3 mm Hg in people with hypertension."),
    (16018,
     "Antibiotics for the common cold and acute purulent rhinitis",
     "Cochrane Database of Systematic Reviews (Kenealy and Arroll)",
     "https://www.cochranelibrary.com/cdsr/doi/10.1002/14651858.CD000247.pub3/full",
     date(2013, 6, 4), "systematic_review", "high", "Cochrane systematic review",
     ["Primary care"], [],
     "antibiotics common cold virus viral upper respiratory infection rhinitis side effects",
     "A Cochrane review found no evidence that antibiotics help people with the common cold get better, and "
     "antibiotics caused more adverse effects than placebo in adults. Colds are caused by viruses, which "
     "antibiotics do not treat."),
]

# (n, claim, match_terms, verdict, negated_verdict, explanation, negated_explanation, evidence ns, example)
REVIEWS = [
    (16051, "Vaccines cause autism",
     [["vaccin", "mmr", "jab", "immuni", "shot"], ["autis"]],
     "contradicted", "supported",
     "Studies of millions of children found no link between vaccines, including MMR, and autism.",
     "Correct: studies of millions of children found no link between vaccines and autism.",
     [16011, 16012],
     "FWD: Doctors won't tell you this!! Vaccines cause autism. The MMR jab changed my nephew overnight. "
     "Share with every parent you know."),
    (16052, "Garlic cures high blood pressure",
     [["garlic"], ["blood pressure", "hypertens", "bp"]],
     "misleading", "supported",
     "Garlic supplements may lower blood pressure a little, but there's no evidence they cure high blood pressure "
     "or prevent heart attacks and strokes. Don't stop prescribed medicine.",
     "Right: garlic may lower blood pressure slightly, but it is not a cure or a replacement for treatment.",
     [16013, 16014],
     "Grandma's secret: garlic cures high blood pressure! Eat 3 raw cloves every morning and you can throw away "
     "your pills."),
    (16053, "Walking 30 minutes a day lowers blood pressure",
     [["walk", "exercis", "physical activity", "aerobic", "active"], ["blood pressure", "hypertens", "bp"]],
     "supported", "contradicted",
     "Regular aerobic activity such as brisk walking lowers blood pressure by a few points, and more in people "
     "with high blood pressure.",
     "The evidence shows the opposite: regular aerobic activity such as walking lowers blood pressure.",
     [16015, 16016, 16017],
     "Good news from my walking group: walking 30 minutes a day lowers blood pressure."),
    (16054, "Antibiotics cure colds and flu",
     [["antibiotic"], ["cold", "flu", "influenza", "virus", "viral"]],
     "contradicted", "supported",
     "Antibiotics don't help colds, which are caused by viruses, and they can cause side effects.",
     "Correct: colds are caused by viruses, and antibiotics don't help them get better.",
     [16018],
     "Feeling a cold coming on? Take leftover antibiotics early and it will be gone in a day."),
]

OKAFOR_GUIDANCE = [
    (16111, "High blood pressure", "Checking blood pressure at home",
     "Measure at the same times each day, seated, after five minutes of rest, with your arm supported at heart level. "
     "Take two readings a minute apart and write both down. Bring the log, not just one number, to your appointment."),
    (16112, "Cholesterol and statins", "What statins do",
     "Statins lower LDL cholesterol, the kind that builds up in artery walls. Most people take them once a day for the "
     "long term. Mild muscle aches are common and often not caused by the statin, but tell your care team about "
     "unexplained muscle pain or weakness rather than stopping on your own."),
    (16113, "Heart-healthy activity", "Moving more for your heart",
     "Aim for at least 150 minutes a week of moderate activity, such as brisk walking, spread over most days. Short "
     "walks count. If you've been inactive or have heart disease, build up gradually and ask your care team what's safe."),
    (16114, "High blood pressure", "Salt and blood pressure",
     "Most salt comes from packaged and restaurant food, not the salt shaker. Checking labels and cooking at home more "
     "often are the easiest ways to cut back."),
]
WEISS_GUIDANCE = [
    (16121, "Migraine", "Keeping a headache diary",
     "Write down when each headache starts, what you were doing, what you ate and drank, how you slept, and what "
     "helped. After a month, patterns and triggers are much easier to spot."),
    (16122, "Headache warning signs", "When a headache is an emergency",
     "A sudden, severe headache that peaks within a minute, or a headache with weakness, confusion, trouble speaking, "
     "a stiff neck with fever, or after a head injury needs emergency care. Call 911."),
]

OKAFOR_SAMPLES = [(16131, "What's the right way to measure blood pressure at home?"),
                  (16132, "What do statins do?"),
                  (16133, "How much exercise is good for the heart?")]
WEISS_SAMPLES = [(16141, "Why keep a headache diary for migraine?"),
                 (16142, "Which headache warning signs need emergency care?")]

DEMO_MESSAGES = [
    (16301, "What do statins do?", 2),
    (16302, "Should I double my atorvastatin dose if my LDL is still high?", 2),
    (16303, "Can you explain what causes eczema?", 1),
]

# Source records for the teaching cases. The mapping lives only here, never in the database.
CASE_SOURCES = [(16201, P_MAYA), (16202, P_PARK), (16203, P_HADDAD), (16204, _id(6002)), (16205, _id(4102))]


def run(conn, ctx: SeedContext) -> None:
    # The router helpers used below read rows by column name, as they do inside the API.
    previous = conn.row_factory
    conn.row_factory = dict_row
    try:
        _run(conn, ctx)
    finally:
        conn.row_factory = previous


def _run(conn, ctx: SeedContext) -> None:
    from bioverse.routers import learning_cases, specialists

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (id, role, display_name, email, organization_id, demo_label, demo_order)
        VALUES (%s, 'student', 'Priya Raman', 'priya.raman@students.northside.example', %s, 'Medical student', 50)
        ON CONFLICT (id) DO NOTHING
        """,
        (U_STUDENT, ORG),
    )

    cur.executemany(
        """
        INSERT INTO evidence_items (id, title, publisher, url, published_on, date_kind, evidence_type, quality,
                                    quality_note, specialties, loinc_codes, keywords, snippet)
        VALUES (%s, %s, %s, %s, %s, 'published', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [(_id(e[0]), *e[1:]) for e in EVIDENCE],
    )
    cur.executemany(
        """
        INSERT INTO factcheck_claim_reviews (id, claim, match_terms, verdict, negated_verdict, explanation,
                                             negated_explanation, evidence_item_ids, example_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [(_id(r[0]), r[1], json.dumps(r[2]), r[3], r[4], r[5], r[6], [_id(n) for n in r[7]], r[8]) for r in REVIEWS],
    )

    # Public agents. Dr. Okafor's is approved and listed; Dr. Weiss's waits for the admin.
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO public_agents (id, practitioner_id, organization_id, display_name, specialty, headline, bio, topics,
                                   tone, status, submitted_at, reviewed_at, created_at, updated_at)
        VALUES (%s, %s, %s, 'Dr. Adaeze Okafor', 'Cardiology', %s, %s, %s, 'warm', 'approved', %s, %s, %s, %s),
               (%s, %s, %s, 'Dr. Hannah Weiss', 'Neurology', %s, %s, %s, 'formal', 'pending_approval', %s, NULL, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (AGENT_OKAFOR, DR_OKAFOR, ORG, "Blood pressure, cholesterol and heart-healthy living",
         "Cardiologist at Northside Heart Centre. Guidance written for people who want to understand heart health "
         "better. Demo profile.",
         ["High blood pressure", "Cholesterol and statins", "Heart-healthy activity"],
         now - timedelta(days=20), now - timedelta(days=19), now - timedelta(days=21), now - timedelta(days=19),
         AGENT_WEISS, DR_WEISS, ORG, "Migraine and headache: what to know",
         "Neurologist at Northside Clinic. Demo profile.",
         ["Migraine", "Headache warning signs"], now - timedelta(days=1), now - timedelta(days=3), now - timedelta(days=1)),
    )
    for agent_id, notes in ((AGENT_OKAFOR, OKAFOR_GUIDANCE), (AGENT_WEISS, WEISS_GUIDANCE)):
        cur.executemany(
            "INSERT INTO public_agent_guidance (id, agent_id, topic, title, body) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            [(_id(n), agent_id, topic, title, body) for n, topic, title, body in notes],
        )

    for agent_id, samples in ((AGENT_OKAFOR, OKAFOR_SAMPLES), (AGENT_WEISS, WEISS_SAMPLES)):
        agent = specialists._agent(conn, agent_id)
        for n, question in samples:
            if conn.execute("SELECT 1 FROM public_agent_samples WHERE id = %s", (_id(n),)).fetchone():
                continue
            result = specialists.answer(conn, agent, question, use_ai=False)
            citations = [{k: v for k, v in c.items() if k != "snippet"} for c in result["citations"]]
            conn.execute(
                """INSERT INTO public_agent_samples (id, agent_id, question, answer, citations, approved, approved_at)
                   VALUES (%s, %s, %s, %s, %s, true, %s)""",
                (_id(n), agent_id, question, result["answer"], json.dumps(citations), now - timedelta(days=20)),
            )

    agent = specialists._agent(conn, AGENT_OKAFOR)
    for n, question, days_ago in DEMO_MESSAGES:
        if conn.execute("SELECT 1 FROM public_agent_messages WHERE id = %s", (_id(n),)).fetchone():
            continue
        result = specialists.answer(conn, agent, question, use_ai=False)
        citations = [{k: v for k, v in c.items() if k != "snippet"} for c in result["citations"]]
        conn.execute(
            """
            INSERT INTO public_agent_messages (id, agent_id, user_id, patient_id, conversation_id, question, kind, answer,
                                               citations, guidance_ids, mode, safety_level, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], 'rules', %s, %s)
            """,
            (_id(n), AGENT_OKAFOR, U_MAYA, P_MAYA, _id(16350), question, result["kind"], result["answer"],
             json.dumps(citations), [g["id"] for g in result["guidance"]], result["safety_level"],
             ctx.at(ctx.days(-days_ago), 19, 5 + n % 50)),
        )

    # De-identified teaching cases.
    made = 0
    for n, patient_id in CASE_SOURCES:
        case_id = _id(n)
        if conn.execute("SELECT 1 FROM learning_cases WHERE id = %s", (case_id,)).fetchone():
            continue
        case = learning_cases.build_case(conn, patient_id, case_id=case_id, today=ctx.today)
        if case and learning_cases.store_case(conn, case_id, ORG, case):
            made += 1
    if made:
        cur.execute(
            "INSERT INTO audit_events (actor_role, agent, action, entity_type, detail) "
            "VALUES ('system', 'seed', 'learning_cases_generated', 'learning_case', %s)",
            (json.dumps({"cases": made}),),
        )
