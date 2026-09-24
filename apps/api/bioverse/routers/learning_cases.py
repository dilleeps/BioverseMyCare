"""De-identified teaching cases, built from demo records. No router here: bioverse/routers/learning.py serves them.

`build_case` reads one patient's record once and returns a case with:
- no names (patients, clinicians, users), record numbers, addresses, phone numbers, e-mail addresses or
  facility names;
- no exact dates: every date is shifted by one offset per case (derived from the case id), so intervals stay
  true within the case and never match the source;
- ages over 89 reported as "90 or older";
- the clinical content kept: presentation, history, medicines, results, what happened next.

The stored case has no column pointing back to the patient, and nothing at request time joins to patient
tables. Teaching content (differentials, key points, model answers, quiz) comes from TOPICS below, chosen by the
case's findings; quiz questions use the case's own values.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any

from psycopg import Connection

from bioverse.agents import evidence

# --- De-identification ---------------------------------------------------------------------------

_DR = re.compile(r"\bDr\.?\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?")
_MONTH_DATE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{4})?\b"
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.+\-]+Z?)?")
_OLD_AGE = re.compile(r"\b(?:9\d|1[0-2]\d)(?=\s?(?:-?\s?years?[- ]old|yo\b|y/o|[FM]\b))")
_ADDRESS = re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct)\b\.?")
_MRN_LIKE = re.compile(r"\b[A-Z]{2,5}-\d{3,}\b")


def identifier_lists(conn: Connection, organization_id: str) -> dict[str, list[str]]:
    """Every person and place name the org's records could mention."""
    people = [r["name"] for r in conn.execute(
        "SELECT name FROM patients WHERE organization_id = %s", (organization_id,)).fetchall()]
    people += [re.sub(r"^Dr\.?\s+", "", r["name"]) for r in conn.execute(
        "SELECT name FROM practitioners WHERE organization_id = %s AND (name LIKE 'Dr%%' OR user_id IS NOT NULL)",
        (organization_id,)).fetchall()]
    people += [r["display_name"] for r in conn.execute(
        "SELECT display_name FROM users WHERE organization_id = %s AND role IN ('patient', 'clinician', 'student')",
        (organization_id,)).fetchall()]
    people += [r["name"] for r in conn.execute(
        "SELECT ec.name FROM emergency_contacts ec JOIN patients p ON p.id = ec.patient_id WHERE p.organization_id = %s",
        (organization_id,)).fetchall()]
    places = [r["n"] for r in conn.execute(
        """
        SELECT name AS n FROM organizations WHERE id = %(org)s
        UNION SELECT location_name FROM practitioners WHERE organization_id = %(org)s AND location_name IS NOT NULL
        UNION SELECT lab_name FROM diagnostic_reports d JOIN patients p ON p.id = d.patient_id
              WHERE p.organization_id = %(org)s AND lab_name IS NOT NULL
        UNION SELECT location FROM immunizations i JOIN patients p ON p.id = i.patient_id
              WHERE p.organization_id = %(org)s AND location IS NOT NULL
        """,
        {"org": organization_id},
    ).fetchall() if r["n"]]
    identifiers = [r["value"] for r in conn.execute(
        "SELECT value FROM patient_identifiers pi JOIN patients p ON p.id = pi.patient_id WHERE p.organization_id = %s",
        (organization_id,)).fetchall()]
    places = [p for p in set(places) if p.lower() not in ("video visit", "remote", "home")]
    return {"people": sorted(set(people), key=len, reverse=True), "places": sorted(places, key=len, reverse=True),
            "identifiers": identifiers}


def scrub(text: str, ids: dict[str, list[str]]) -> str:
    """Remove identifiers from free text. Clinical words stay."""
    if not text:
        return ""
    for value in ids["identifiers"]:
        text = text.replace(value, "[removed]")
    text = _DR.sub("the clinician", text)
    for place in ids["places"]:
        text = re.sub(r"\b" + re.escape(place) + r"\b", "a clinic", text, flags=re.IGNORECASE)
    text = _ISO_DATE.sub("[date removed]", text)
    text = _MONTH_DATE.sub("[date removed]", text)
    text = _OLD_AGE.sub("90+", text)
    text = _ADDRESS.sub("[address removed]", text)
    text = _MRN_LIKE.sub("[removed]", text)
    text, _ = evidence.deidentify(text, ids["people"])
    return re.sub(r"\s+", " ", text).strip()


def date_shift(case_id: str) -> int:
    """Days to shift every date in a case: fixed per case, never zero, large enough to miss real dates."""
    return -(1000 + int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 700)


def age_text(birth: date, on: date) -> str:
    age = on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))
    return "90 or older" if age >= 90 else str(age)


# --- Teaching topics ------------------------------------------------------------------------------


def kp(label: str, terms: list[str], ask: str) -> dict[str, Any]:
    return {"label": label, "terms": terms, "ask": ask}


def _labs(ctx: dict[str, Any], display: str) -> list[dict[str, Any]]:
    return [o for o in ctx["labs"] if o["display"].lower() == display.lower()]


def _q(question: str, options: list[str], answer: int, explanation: str) -> dict[str, Any]:
    return {"question": question, "options": options, "answer": answer, "explanation": explanation}


def _quiz_lipids(ctx):
    ldl = [float(o["value"]) for o in _labs(ctx, "LDL cholesterol")]
    qs = []
    if len(ldl) >= 2:
        if all(b > a for a, b in zip(ldl, ldl[1:])):
            ans = 0
        elif all(b < a for a, b in zip(ldl, ldl[1:])):
            ans = 1
        elif abs(ldl[-1] - ldl[0]) < 5:
            ans = 2
        else:
            ans = 3
        qs.append(_q("Across the lipid panels in this case, how did LDL cholesterol change?",
                     ["It rose at every panel", "It fell at every panel", "It stayed about the same", "It went up and down"],
                     ans, f"The LDL values were {', '.join(f'{v:g}' for v in ldl)} mg/dL, in date order."))
    qs.append(_q("Under the 2018 AHA/ACC cholesterol guideline, which LDL-C level calls for a high-intensity statin "
                 "without calculating 10-year risk?",
                 ["130 mg/dL or higher", "160 mg/dL or higher", "190 mg/dL or higher", "220 mg/dL or higher"], 2,
                 "Adults with LDL-C of 190 mg/dL or higher should receive a high-intensity statin without risk calculation."))
    qs.append(_q("When should a lipid panel be rechecked after starting a statin?",
                 ["After 1 week", "After 4 to 12 weeks", "After 1 to 2 years", "Only if symptoms develop"], 1,
                 "Check adherence and LDL response 4 to 12 weeks after starting or changing the dose."))
    return qs


def _quiz_prediabetes(ctx):
    a1c = _labs(ctx, "Hemoglobin A1c")
    qs = []
    if a1c:
        v = float(a1c[-1]["value"])
        ans = 0 if v < 5.7 else 1 if v < 6.5 else 2
        qs.append(_q(f"This case's HbA1c was {v:g}%. Which category is that?",
                     ["Normal (below 5.7%)", "Prediabetes (5.7% to 6.4%)", "Diabetes (6.5% or higher)"], ans,
                     "ADA: prediabetes is an HbA1c of 5.7% to 6.4%; diabetes is 6.5% or higher, confirmed by repeat testing."))
    qs.append(_q("In the Diabetes Prevention Program, which approach cut type 2 diabetes incidence by 58%?",
                 ["Metformin alone", "Intensive lifestyle intervention", "Placebo", "Bariatric surgery"], 1,
                 "Lifestyle reduced incidence by 58% and metformin by 31% compared with placebo."))
    qs.append(_q("What weight-loss goal do lifestyle programs modeled on the DPP aim for?",
                 ["At least 2%", "At least 7%", "At least 15%", "Any amount"], 1,
                 "ADA recommends at least 7% weight loss and at least 150 minutes a week of moderate activity."))
    return qs


def _quiz_hyperkalemia(ctx):
    k = _labs(ctx, "Potassium")
    qs = []
    if k:
        o = k[-1]
        v, lo, hi = float(o["value"]), o["ref_low"], o["ref_high"]
        ans = 3 if v >= 6.5 else 2 if hi is not None and v > float(hi) else 0 if lo is not None and v < float(lo) else 1
        ref = f"{float(lo):g} to {float(hi):g}" if lo is not None and hi is not None else "not given"
        qs.append(_q(f"Potassium was {v:g} mmol/L (reference {ref}). How would you describe it?",
                     ["Low", "Within range", "Mildly high", "Severely high (6.5 or more)"], ans,
                     "Compare with the laboratory's reference range, and remember severity guides urgency."))
    qs.append(_q("A well patient has an unexpected, mildly high potassium. What comes first?",
                 ["Start a potassium binder", "Repeat the test with a careful sample and check an ECG",
                  "Admit to intensive care", "No action"], 1,
                 "Exclude a haemolysed sample (pseudohyperkalaemia) and look for ECG changes before anything else."))
    qs.append(_q("Which drug class commonly raises potassium?",
                 ["ACE inhibitors", "Loop diuretics", "Inhaled beta-2 agonists", "Insulin"], 0,
                 "ACE inhibitors, ARBs, potassium-sparing diuretics and NSAIDs can all raise potassium."))
    return qs


def _quiz_vitamin_d(ctx):
    d = _labs(ctx, "25-hydroxy vitamin D")
    qs = []
    if d:
        o = d[-1]
        ans = {"L": 0, "LL": 0, "N": 1, "H": 2, "HH": 2}.get(o["interpretation"], 1)
        qs.append(_q(f"Vitamin D was {float(o['value']):g} ng/mL. Compared with the laboratory's reference range it was:",
                     ["Below the range", "Within the range", "Above the range"], ans,
                     "The laboratory flagged the result against its own reference range."))
    qs.append(_q("This older adult walks with a stick. Which risk should the plan address first?",
                 ["Falls and fractures", "Sunburn", "Kidney stones", "Weight gain"], 0,
                 "Low vitamin D, reduced mobility and age together raise the risk of falls and fractures."))
    return qs


def _quiz_orthostatic(ctx):
    med = next((m for m in ctx["meds"] if m["drug_name"].lower() == "amlodipine"), None)
    qs = [
        _q("According to its label, what is the most common adverse reaction to amlodipine?",
           ["Peripheral edema", "Dry cough", "Hyperkalemia", "Weight loss"], 0,
           "Peripheral edema is the most common adverse reaction and is dose related."),
        _q("Which bedside test best checks dizziness on standing?",
           ["Lying and standing blood pressure", "Peak flow", "Finger-prick glucose", "Visual acuity"], 0,
           "A fall in blood pressure on standing confirms orthostatic hypotension."),
    ]
    if med:
        qs.append(_q(f"The medicine in this case was amlodipine {med['strength']}. Which drug class is it?",
                     ["ACE inhibitor", "Calcium channel blocker", "Beta blocker", "Thiazide diuretic"], 1,
                     "Amlodipine is a dihydropyridine calcium channel blocker."))
    return qs


TOPICS: dict[str, dict[str, Any]] = {
    "orthostatic": {
        "specialty": "Cardiology", "difficulty": "intermediate",
        "title": "Dizziness after a new blood pressure tablet",
        "presentation": "started a new blood pressure tablet about a week ago and now reports dizziness on standing.",
        "complaint": r"dizz|light-?headed|faint|amlodipine|blood pressure",
        "evidence_query": "amlodipine side effects dizziness hypotension",
        "prompts": [
            "What is your differential for dizziness after starting a new blood pressure medicine? Which red flags would you ask about?",
            "What would you examine and test?",
            "Outline your management plan and the safety-net advice you would give.",
        ],
        "key_points": [
            [kp("Orthostatic hypotension", ["orthostatic", "postural", "hypotension", "low blood pressure"],
                "What happens to blood pressure when this person stands up?"),
             kp("Medication side effect", ["side effect", "adverse", "amlodipine", "medication", "drug"],
                "What changed eight days ago, and could it explain the symptom?"),
             kp("Dehydration", ["dehydrat", "fluid", "volume"], "How might fluid intake contribute?"),
             kp("Arrhythmia", ["arrhythm", "rhythm", "palpitation", "atrial"],
                "Which cardiac cause of dizziness must you not miss?"),
             kp("Vestibular causes", ["vestibul", "vertigo", "bppv", "inner ear"],
                "How would you tell spinning vertigo from light-headedness?"),
             kp("Red flags: syncope, chest pain, falls", ["faint", "syncope", "chest pain", "fall", "collapse"],
                "Which answers would make this an emergency?")],
            [kp("Lying and standing blood pressure", ["lying and standing", "orthostatic", "postural", "standing blood pressure",
                                                     "sitting and standing", "lying to standing"],
                "Which bedside measurement confirms the leading diagnosis?"),
             kp("ECG", ["ecg", "ekg", "electrocardiogram"], "Which quick test rules out a rhythm problem?"),
             kp("Electrolytes and kidney function", ["electrolyte", "sodium", "potassium", "creatinine", "renal", "kidney"],
                "Which blood tests matter in someone on antihypertensives?"),
             kp("Ankle swelling", ["edema", "oedema", "swelling", "ankle"],
                "What is the commonest side effect of this medicine, and where would you look for it?"),
             kp("Medication review", ["medication review", "adherence", "other medic", "all medic", "interaction"],
                "What else might they be taking that lowers blood pressure?")],
            [kp("Review dose or timing", ["dose", "timing", "evening", "reduce", "lower"],
                "Could the same drug be given differently?"),
             kp("Fluids and rising slowly", ["hydrat", "fluid", "slowly", "rise", "stand up slowly"],
                "What simple advice reduces symptoms on standing?"),
             kp("Alternative agent if it persists", ["switch", "alternative", "different medic", "another", "change"],
                "What would you do if symptoms continue?"),
             kp("Follow-up readings", ["home blood pressure", "home reading", "follow-up", "follow up", "recheck", "monitor"],
                "How will you know the plan worked?"),
             kp("Safety-net advice", ["faint", "fall", "chest pain", "return", "urgent", "safety", "911", "emergency"],
                "What should make them seek help urgently?")],
        ],
        "model_answers": [
            "Most likely orthostatic (postural) hypotension from the new antihypertensive, possibly worsened by low fluid "
            "intake. Also consider an arrhythmia, a vestibular cause, and other medicines that lower blood pressure. Ask about "
            "fainting, falls, chest pain, palpitations and breathlessness: any of these changes the urgency.",
            "Measure lying and standing blood pressure and pulse, examine for ankle edema (the commonest amlodipine side "
            "effect), and review every medicine and how it is taken. Check an ECG and electrolytes with kidney function.",
            "If orthostatic hypotension is confirmed and there are no red flags: advise fluids and rising slowly, review the "
            "dose or timing, and arrange home blood pressure readings with early follow-up. Consider a different agent if "
            "symptoms persist. Safety-net: fainting, a fall with injury or chest pain needs urgent care.",
        ],
        "teaching_points": [
            "Dizziness in the first weeks of a new antihypertensive is often orthostatic: measure lying and standing blood pressure.",
            "Peripheral edema is the most common adverse reaction to amlodipine and is dose related.",
            "Always ask about syncope, chest pain and palpitations before calling dizziness benign.",
        ],
        "quiz": _quiz_orthostatic,
    },
    "lipids": {
        "specialty": "Cardiology", "difficulty": "core",
        "title": "Rising LDL cholesterol",
        "presentation": "is seen in cardiology after routine blood tests showed LDL cholesterol rising over time.",
        "complaint": r"chest|cholesterol|ldl|heart",
        "evidence_query": "statin LDL cholesterol primary prevention monitoring",
        "prompts": [
            "What is on your differential for this presentation, and which cardiovascular risk factors would you ask about?",
            "What investigations would you order next, and why?",
            "How do you interpret these results? What management would you propose, and how would you monitor it?",
        ],
        "key_points": [
            [kp("Must-not-miss cardiac causes", ["acute coronary", "acs", "angina", "myocardial", "heart attack", "ischaem", "ischem"],
                "Which cause of chest discomfort must you rule out first?"),
             kp("Family history", ["family history", "familial", "fh"], "What in the family history would change your thinking about LDL?"),
             kp("Smoking", ["smok", "tobacco", "cigarette"], "Which modifiable habit multiplies cardiovascular risk?"),
             kp("Diabetes", ["diabet", "glucose", "a1c"], "Which metabolic condition changes the statin decision on its own?"),
             kp("Blood pressure", ["blood pressure", "hypertens", "bp"], "What did the earlier physical show about blood pressure?"),
             kp("Secondary causes of high LDL", ["hypothyroid", "thyroid", "nephrotic", "liver", "cholesta", "secondary"],
                "Which conditions can raise LDL secondarily?")],
            [kp("Lipid panel and trend", ["lipid", "ldl", "cholesterol panel", "fasting lipid"], "What does the trend over time add to one value?"),
             kp("ECG", ["ecg", "ekg", "electrocardiogram"], "Which quick test belongs with any chest discomfort?"),
             kp("10-year risk estimate", ["ascvd", "risk score", "risk calculat", "pooled cohort", "qrisk", "10-year", "10 year"],
                "How would you quantify this person's risk before deciding on a statin?"),
             kp("HbA1c or glucose", ["a1c", "glucose", "diabet"], "How would you screen for diabetes here?"),
             kp("Thyroid function", ["tsh", "thyroid"], "Which simple blood test excludes a secondary cause?")],
            [kp("LDL above target and rising", ["rising", "increas", "trend", "above target", "elevated", "high"],
                "What does the direction of change tell you?"),
             kp("Lifestyle", ["diet", "exercise", "lifestyle", "activity", "weight"], "What should every plan include regardless of medicine?"),
             kp("Statin therapy", ["statin", "atorvastatin", "rosuvastatin"], "Which medicine class is first line, and at what intensity?"),
             kp("Shared decision-making", ["shared decision", "discuss", "risk discussion", "preference"],
                "How should intermediate risk be turned into a decision?"),
             kp("Recheck in 4 to 12 weeks", ["recheck", "repeat", "4 to 12", "4-12", "monitor", "follow-up lipid", "follow up lipid"],
                "When and how would you check the response?"),
             kp("Watch for muscle symptoms", ["muscle", "myopathy", "myalgia", "side effect", "ck", "creatine kinase"],
                "Which adverse effect should the patient report promptly?")],
        ],
        "model_answers": [
            "With chest discomfort, first exclude an acute coronary syndrome or angina (the red-flag screen was negative "
            "and the pain was not present at intake). Then take a full cardiovascular risk history: family history of "
            "premature heart disease or familial hypercholesterolaemia, smoking, diabetes, blood pressure, diet and activity, "
            "and secondary causes of high LDL such as hypothyroidism, nephrotic syndrome, cholestatic liver disease or medicines.",
            "A lipid panel with the trend over time, an ECG for the chest discomfort, a 10-year ASCVD risk estimate, HbA1c or "
            "fasting glucose, thyroid function, and a repeat blood pressure (the last reading was high).",
            "LDL is above target and has risen at every panel. Recommend lifestyle change for everyone, and after a "
            "risk discussion a moderate-intensity statin for intermediate risk. Recheck the lipid panel in 4 to 12 weeks "
            "for adherence and response, and ask the patient to report unexplained muscle pain or weakness.",
        ],
        "teaching_points": [
            "Decide on statins using estimated 10-year risk and risk enhancers, not a single LDL value.",
            "LDL-C of 190 mg/dL or higher calls for a high-intensity statin without risk calculation.",
            "Recheck lipids 4 to 12 weeks after starting or changing a statin.",
        ],
        "quiz": _quiz_lipids,
    },
    "prediabetes": {
        "specialty": "Primary care", "difficulty": "core",
        "title": "A borderline HbA1c",
        "presentation": "is reviewed after a routine HbA1c came back above the reference range.",
        "complaint": r"a1c|glucose|sugar|diabet",
        "evidence_query": "prediabetes HbA1c lifestyle prevention metformin",
        "prompts": [
            "What conditions are you thinking about, and what risk factors would you ask about?",
            "Which investigations would confirm the diagnosis and assess cardiovascular risk?",
            "Interpret the result and propose a plan.",
        ],
        "key_points": [
            [kp("Prediabetes", ["prediabet", "impaired glucose", "impaired fasting", "insulin resist"],
                "What do we call glucose that is raised but below the diabetes threshold?"),
             kp("Type 2 diabetes", ["type 2", "diabet"], "Which diagnosis must the next test confirm or exclude?"),
             kp("Family history", ["family"], "Whose health history would you ask about?"),
             kp("Weight", ["weight", "bmi", "obes", "overweight", "waist"], "Which measurement is the strongest modifiable risk factor?"),
             kp("Activity and diet", ["activity", "exercise", "diet", "food"], "What about daily habits?"),
             kp("When HbA1c is unreliable", ["anaemia", "anemia", "haemoglobinopath", "hemoglobinopath", "red cell", "pregnan"],
                "When can an HbA1c mislead you?")],
            [kp("Confirm with a repeat test", ["repeat", "fasting glucose", "fasting plasma", "ogtt", "glucose tolerance", "confirm"],
                "How is a single abnormal HbA1c confirmed?"),
             kp("Lipids", ["lipid", "cholesterol"], "Which other cardiovascular risk marker belongs in this workup?"),
             kp("Blood pressure", ["blood pressure", "bp"], "Which bedside measurement would you add?"),
             kp("BMI", ["bmi", "weight", "waist"], "What would you measure to set a goal?"),
             kp("Kidney function", ["kidney", "creatinine", "egfr", "albumin", "urine"], "Which organ function do you baseline in dysglycaemia?")],
            [kp("Prediabetes range 5.7 to 6.4%", ["prediabet", "5.7", "6.4"], "Which band does this value fall in?"),
             kp("Structured lifestyle program", ["lifestyle", "diabetes prevention", "dpp", "program", "programme"],
                "What intervention has the strongest trial evidence?"),
             kp("About 7% weight loss", ["7%", "7 %", "seven percent", "weight loss", "lose weight"], "What weight goal would you set?"),
             kp("150 minutes of activity a week", ["150", "activity", "exercise", "walking"], "How much activity would you recommend?"),
             kp("Consider metformin", ["metformin"], "Which medicine could be considered for higher-risk people?"),
             kp("Yearly monitoring", ["annual", "yearly", "every year", "12 months", "monitor", "recheck"], "How often would you retest?")],
        ],
        "model_answers": [
            "The likely picture is prediabetes, with type 2 diabetes to exclude. Ask about family history, weight, activity "
            "and diet, previous gestational diabetes, and conditions that make HbA1c unreliable (anaemia, haemoglobinopathies, "
            "pregnancy).",
            "Confirm with a repeat HbA1c or a fasting plasma glucose, and assess overall cardiovascular risk: lipids, blood "
            "pressure, BMI and kidney function.",
            "An HbA1c of 5.7% to 6.4% is prediabetes. Refer to a structured lifestyle program modeled on the Diabetes "
            "Prevention Program: at least 7% weight loss and 150 minutes a week of moderate activity. Consider metformin in "
            "higher-risk adults. Retest at least yearly.",
        ],
        "teaching_points": [
            "Prediabetes is an HbA1c of 5.7% to 6.4%; confirm an abnormal result before labelling diabetes.",
            "Intensive lifestyle change reduced progression to type 2 diabetes by 58% in the DPP.",
            "Monitor people with prediabetes for progression at least yearly.",
        ],
        "quiz": _quiz_prediabetes,
    },
    "hyperkalemia": {
        "specialty": "Primary care", "difficulty": "intermediate",
        "title": "An unexpected high potassium",
        "presentation": "had a basic metabolic panel at a routine visit, and the laboratory flagged a high potassium.",
        "complaint": r"potassium|kidney",
        "evidence_query": "potassium hyperkalemia ACE inhibitor kidney",
        "prompts": [
            "What could explain a high potassium result? What must you rule out first?",
            "What investigations would you do now?",
            "Interpret the panel and outline your management.",
        ],
        "key_points": [
            [kp("Spurious result (haemolysis)", ["pseudo", "haemoly", "hemoly", "sample", "tourniquet", "spurious"],
                "Could the result be wrong before it is right?"),
             kp("Kidney disease", ["kidney", "renal", "ckd", "egfr"], "Which organ normally clears potassium?"),
             kp("Medicines", ["ace inhibitor", "acei", "arb", "spironolactone", "potassium-sparing", "nsaid", "medication", "drug"],
                "Which medicines raise potassium?"),
             kp("Diet and supplements", ["diet", "supplement", "salt substitute"], "What might they be eating or taking?"),
             kp("Shift out of cells", ["acidosis", "shift", "insulin deficien", "cell"], "What moves potassium out of cells?"),
             kp("Adrenal causes", ["addison", "adrenal", "aldosterone"], "Which hormone deficiency raises potassium?")],
            [kp("Repeat potassium", ["repeat", "recheck", "redo"], "What is the first test to repeat?"),
             kp("ECG", ["ecg", "ekg", "electrocardiogram"], "Which test tells you if this is dangerous right now?"),
             kp("Kidney function", ["creatinine", "egfr", "renal function", "kidney function"], "Which blood test shows clearance?"),
             kp("Glucose", ["glucose", "sugar"], "Which metabolic value would you add?"),
             kp("Medication review", ["medication", "drug", "medicine"], "What would you ask the patient to bring?")],
            [kp("Mild hyperkalaemia", ["mild", "5.5", "5.6", "slightly"], "How severe is this value?"),
             kp("Kidney function normal", ["creatinine", "normal kidney", "renal function normal", "kidney function normal", "normal renal"],
                "What does the creatinine tell you?"),
             kp("Urgent if ECG changes or level rises", ["ecg change", "peaked", "urgent", "emergency", "calcium gluconate", "6.5"],
                "When does this become an emergency?"),
             kp("Stop contributing medicines or supplements", ["stop", "hold", "review medic", "withhold"], "What would you stop?"),
             kp("Dietary advice", ["diet", "low potassium", "food"], "What advice about food would you give?"),
             kp("Repeat test", ["repeat", "recheck"], "When would you recheck?")],
        ],
        "model_answers": [
            "First exclude a spurious result from a haemolysed or delayed sample. True causes include reduced kidney "
            "function, medicines (ACE inhibitors, ARBs, potassium-sparing diuretics, NSAIDs), supplements or salt substitutes, "
            "shift out of cells (acidosis, insulin deficiency) and adrenal insufficiency.",
            "Repeat the potassium with a careful sample, get an ECG, check kidney function and glucose, and review all "
            "medicines and supplements.",
            "A potassium just above range with normal sodium and creatinine is mild hyperkalaemia. With a normal ECG, "
            "repeat promptly, stop contributing medicines or supplements, and give dietary advice. ECG changes or a level of "
            "6.5 mmol/L or more needs emergency treatment.",
        ],
        "teaching_points": [
            "Repeat an unexpected high potassium before acting on it: haemolysis is common.",
            "The ECG, not the number alone, decides how urgent hyperkalaemia is.",
            "ACE inhibitors, ARBs, potassium-sparing diuretics and NSAIDs are frequent causes.",
        ],
        "quiz": _quiz_hyperkalemia,
    },
    "vitamin_d": {
        "specialty": "Primary care", "difficulty": "core",
        "title": "An annual review in an older adult",
        "presentation": "attends an annual review.",
        "complaint": r"vitamin|fall|bone",
        "evidence_query": "vitamin D falls older adults bone",
        "prompts": [
            "What would you assess at an annual review of an older adult? Which risks matter most?",
            "Which investigations would you order?",
            "Interpret the results and propose a plan.",
        ],
        "key_points": [
            [kp("Falls", ["fall"], "The person walks with a stick. What risk does that suggest?"),
             kp("Bone health", ["bone", "osteopor", "fracture"], "What happens if they fall?"),
             kp("Kidney function", ["kidney", "renal", "egfr"], "Which organ function declines with age and affects dosing?"),
             kp("Medication review", ["medication", "polypharm", "medicine"], "What review is due every year?"),
             kp("Blood pressure", ["blood pressure", "bp", "hypertens"], "What did the reading show?"),
             kp("Nutrition and sunlight", ["diet", "nutrition", "sun", "vitamin d"], "What about diet and time outdoors?")],
            [kp("Vitamin D level", ["vitamin d", "25-hydroxy", "25 hydroxy"], "Which vitamin matters for bone and muscle?"),
             kp("Kidney function", ["egfr", "creatinine", "kidney"], "Which blood test would you repeat yearly?"),
             kp("Calcium", ["calcium"], "Which mineral goes with vitamin D?"),
             kp("Bone density", ["dexa", "dxa", "bone density"], "Which scan assesses fracture risk?")],
            [kp("Low vitamin D", ["low", "insufficien", "deficien", "below"], "How would you describe the level?"),
             kp("Supplementation", ["supplement", "vitamin d3", "cholecalciferol", "replace"], "What would you offer?"),
             kp("Falls prevention", ["fall", "balance", "strength", "exercise"], "What else reduces fracture risk?"),
             kp("Kidney function mildly reduced", ["egfr", "kidney", "renal"], "What did the eGFR show?"),
             kp("Recheck", ["recheck", "repeat", "monitor", "follow"], "How will you follow up?")],
        ],
        "model_answers": [
            "Focus on falls and bone health (they walk with a stick), a medication review, blood pressure, kidney function, "
            "and nutrition and time outdoors.",
            "Vitamin D, kidney function (eGFR and creatinine), calcium, and consider bone density assessment if fracture risk "
            "is raised.",
            "Vitamin D is below range: offer supplementation and falls prevention (strength and balance exercise, home "
            "safety). eGFR is mildly reduced, which is common with age but worth tracking yearly. Recheck vitamin D after "
            "replacement if symptoms or risk warrant.",
        ],
        "teaching_points": [
            "In older adults, frame findings around falls and fractures.",
            "A mildly reduced eGFR is common with age but should be tracked, and it affects medicine dosing.",
        ],
        "quiz": _quiz_vitamin_d,
    },
}


def detect_topic(ctx: dict[str, Any]) -> str | None:
    text = " ".join(ctx["notes"]).lower()
    if any(m["drug_name"].lower() == "amlodipine" for m in ctx["meds"]) and "dizz" in text:
        return "orthostatic"
    flagged = {o["display"] for o in ctx["labs"] if o["interpretation"] in ("H", "HH", "L", "LL")}
    for display, topic in (("LDL cholesterol", "lipids"), ("Hemoglobin A1c", "prediabetes"),
                           ("Potassium", "hyperkalemia"), ("25-hydroxy vitamin D", "vitamin_d")):
        if display in flagged:
            return topic
    return None


# --- Building ---------------------------------------------------------------------------------------


def _gather(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    p = conn.execute(
        "SELECT organization_id::text, birth_date, pronouns, sex_at_birth, allergies FROM patients WHERE id = %s",
        (patient_id,),
    ).fetchone()
    if p is None:
        return None
    labs = conn.execute(
        """
        SELECT display, value, unit, ref_low, ref_high, interpretation, effective_at
        FROM observations WHERE patient_id = %s AND category = 'laboratory' ORDER BY effective_at, display
        """,
        (patient_id,),
    ).fetchall()
    vitals = conn.execute(
        """
        SELECT display, value, unit, interpretation, effective_at FROM observations
        WHERE patient_id = %s AND category = 'vital-signs' ORDER BY effective_at DESC LIMIT 6
        """,
        (patient_id,),
    ).fetchall()
    encounters = conn.execute(
        "SELECT kind, summary, occurred_at FROM encounters WHERE patient_id = %s ORDER BY occurred_at", (patient_id,)
    ).fetchall()
    meds = conn.execute(
        "SELECT drug_name, strength, sig, status, authored_at FROM medication_requests WHERE patient_id = %s ORDER BY authored_at",
        (patient_id,),
    ).fetchall()
    intake = conn.execute(
        "SELECT chief_complaint, clinician_summary, created_at FROM intakes WHERE patient_id = %s ORDER BY created_at DESC LIMIT 1",
        (patient_id,),
    ).fetchone()
    reviews = conn.execute(
        """
        SELECT kind, body, created_at FROM review_items
        WHERE patient_id = %s AND kind IN ('agent_escalation', 'referral') ORDER BY created_at
        """,
        (patient_id,),
    ).fetchall()
    tasks = conn.execute(
        """
        SELECT t.kind, t.title, t.due_on, c.started_at FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        WHERE c.patient_id = %s ORDER BY c.started_at, t.position
        """,
        (patient_id,),
    ).fetchall()
    notes = [e["summary"] or "" for e in encounters] + [r["body"] or "" for r in reviews]
    return {"patient": p, "labs": labs, "vitals": vitals, "encounters": encounters, "meds": meds, "intake": intake,
            "reviews": reviews, "tasks": tasks, "notes": notes}


def _day(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def build_case(conn: Connection, patient_id: str, *, case_id: str, today: date | None = None) -> dict[str, Any] | None:
    """A de-identified case from one record, or None when no teaching topic fits it."""
    ctx = _gather(conn, patient_id)
    if ctx is None:
        return None
    topic_key = detect_topic(ctx)
    if topic_key is None:
        return None
    topic = TOPICS[topic_key]
    p = ctx["patient"]
    ids = identifier_lists(conn, p["organization_id"])
    today = today or date.today()
    shift = timedelta(days=date_shift(case_id))

    def sd(value) -> str | None:
        d = _day(value)
        return (d + shift).isoformat() if d else None

    age = age_text(p["birth_date"], today) if p["birth_date"] else "Adult"
    sex = (p["sex_at_birth"] or "").lower()
    noun = "woman" if sex == "female" or (not sex and (p["pronouns"] or "").startswith("she")) else \
        "man" if sex == "male" or (not sex and (p["pronouns"] or "").startswith("he")) else "adult"
    article = "An" if age.startswith("8") or age in ("11", "18") else "A"
    who = f"{article} {age}-year-old {noun}" if age != "90 or older" else f"A {noun} aged 90 or older"
    if age == "Adult":
        who = f"An adult {noun}" if noun != "adult" else "An adult"
    complaint_re = re.compile(topic["complaint"], re.IGNORECASE)

    presentation = [f"{who} {topic['presentation']}"]
    intake = ctx["intake"]
    if intake and complaint_re.search(f"{intake['chief_complaint']} {intake['clinician_summary']}"):
        presentation.append(f"Presenting concern: {scrub(intake['chief_complaint'], ids)}.")
        if intake["clinician_summary"]:
            presentation.append(f"Intake note: {scrub(intake['clinician_summary'], ids)}")
    for r in ctx["reviews"]:
        if r["kind"] == "agent_escalation" and complaint_re.search(r["body"] or ""):
            presentation.append(f"Message to the care team: {scrub(r['body'], ids)}")
    allergies = ", ".join(scrub(a, ids) for a in (p["allergies"] or [])) or "none recorded"
    presentation.append(f"Allergies: {allergies}.")

    # What was known before the index result goes in the history; what was done on or after it is the outcome.
    flagged = [_day(o["effective_at"]) for o in ctx["labs"] if o["interpretation"] in ("H", "HH", "L", "LL")]
    index_day = max(flagged) if flagged else None

    def before_index(value) -> bool:
        return index_day is None or (_day(value) or index_day) < index_day

    history, later = [], []
    for e in ctx["encounters"]:
        line = f"{sd(e['occurred_at'])}: {scrub(e['kind'], ids)}. {scrub(e['summary'] or '', ids)}".strip()
        (history if before_index(e["occurred_at"]) else later).append(line)
    for m in ctx["meds"]:
        line = (f"Medicine: {m['drug_name']} {m['strength']}. {scrub(m['sig'] or '', ids)} "
                f"({m['status']}, prescribed {sd(m['authored_at'])})")
        (history if before_index(m["authored_at"]) else later).append(line)
    for v in ctx["vitals"]:
        history.append(f"{sd(v['effective_at'])}: {v['display']} {float(v['value']):g} {v['unit'] or ''}".strip())
    if not history:
        history.append("No earlier visits, vital signs or medicines are recorded for this presentation.")

    table = [{
        "test": o["display"], "value": f"{float(o['value']):g}", "unit": o["unit"] or "",
        "reference": (f"{float(o['ref_low']):g} to {float(o['ref_high']):g}" if o["ref_low"] is not None and o["ref_high"] is not None
                      else f"below {float(o['ref_high']):g}" if o["ref_high"] is not None
                      else f"above {float(o['ref_low']):g}" if o["ref_low"] is not None else ""),
        "flag": {"H": "High", "HH": "Critically high", "L": "Low", "LL": "Critically low"}.get(o["interpretation"] or "", ""),
        "date": sd(o["effective_at"]),
    } for o in ctx["labs"]]

    outcome = list(later)
    for t in ctx["tasks"]:
        outcome.append(f"Care plan ({t['kind']}): {scrub(t['title'], ids)}")
    for r in ctx["reviews"]:
        if r["kind"] == "referral":
            outcome.append(f"Referral: {scrub(r['body'], ids)}")
    if not outcome:
        outcome.append("The record does not show what happened next. Compare your plan with the model answer.")

    items = evidence.search(conn, topic["evidence_query"], limit=3)
    sources = [{"title": i["title"], "source": i["publisher"], "year": i["published_on"].year, "url": i["url"],
                "item_id": i["id"]} for i in items]

    stages = [
        {"n": 1, "title": "Presentation", "lines": presentation, "table": None},
        {"n": 2, "title": "History and examination", "lines": history, "table": None},
        {"n": 3, "title": "Investigations",
         "lines": [] if table else ["No laboratory results are recorded. What would you expect them to show?"],
         "table": table or None},
        {"n": 4, "title": "What happened", "lines": outcome, "table": None},
    ]
    for i, prompt in enumerate(topic["prompts"]):
        stages[i]["prompt"] = prompt
        stages[i]["key_points"] = topic["key_points"][i]
        stages[i]["model_answer"] = topic["model_answers"][i]
    if not intake or not complaint_re.search(f"{intake['chief_complaint']}"):
        # "Must-not-miss cardiac causes" only applies when there was a chest complaint.
        stages[0]["key_points"] = [k for k in stages[0]["key_points"] if k["label"] != "Must-not-miss cardiac causes"]

    title = topic["title"]
    if topic_key == "lipids" and intake and re.search(r"chest", intake["chief_complaint"] or "", re.IGNORECASE):
        title += " with chest discomfort"
    return {
        "topic": topic_key,
        "title": title,
        "specialty": topic["specialty"],
        "difficulty": topic["difficulty"],
        "summary": f"{who} {topic['presentation']}",
        "demographics": {"age": age, "sex": noun},
        "stages": stages,
        "teaching_points": topic["teaching_points"],
        "evidence": sources,
        "quiz": topic["quiz"](ctx),
        "deidentification": {
            "method": "Names, record numbers, contacts, addresses and facility names removed; dates shifted by a "
                      "fixed per-case offset; ages over 89 grouped.",
        },
    }


def store_case(conn: Connection, case_id: str, organization_id: str, case: dict[str, Any]) -> bool:
    from psycopg.types.json import Jsonb

    row = conn.execute(
        """
        INSERT INTO learning_cases (id, organization_id, title, specialty, difficulty, summary, content)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id
        """,
        (case_id, organization_id, case["title"], case["specialty"], case["difficulty"], case["summary"], Jsonb(case)),
    ).fetchone()
    return row is not None

