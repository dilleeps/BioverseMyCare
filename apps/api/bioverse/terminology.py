"""Terminology service: code lookup, validation, and mapping free text to standard codes.

The tables hold a SMALL, CLEARLY LABELED SUBSET of each code system (the codes Bioverse uses plus a
few common ones), seeded from `CONCEPTS` below. It is not a licensed release of LOINC, SNOMED CT,
ICD-10-CM or RxNorm; a production deployment loads the full releases into the same table.

Agents and adapters call these functions. They never embed codes of their own (docs/05-interoperability.md).
"""

from __future__ import annotations

import re
from typing import Any

from psycopg import Connection

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UCUM = "http://unitsofmeasure.org"

SUBSET_NOTICE = "Bioverse demo subset. Not a complete or licensed release of this code system."

SYSTEMS: dict[str, dict[str, str]] = {
    LOINC: {"name": "LOINC", "title": "LOINC (subset)", "publisher": "Regenstrief Institute"},
    SNOMED: {"name": "SNOMED_CT", "title": "SNOMED CT (subset)", "publisher": "SNOMED International"},
    ICD10CM: {"name": "ICD_10_CM", "title": "ICD-10-CM (subset)", "publisher": "CDC / NCHS"},
    RXNORM: {"name": "RxNorm", "title": "RxNorm (subset)", "publisher": "U.S. National Library of Medicine"},
    UCUM: {"name": "UCUM", "title": "UCUM units (subset)", "publisher": "Regenstrief Institute"},
}

# Names people and HL7 v2 messages use for each system (HL7 table 0396 codes included).
_ALIASES = {
    "loinc": LOINC, "ln": LOINC, "http://loinc.org": LOINC,
    "snomed": SNOMED, "snomedct": SNOMED, "snomed-ct": SNOMED, "sct": SNOMED, "http://snomed.info/sct": SNOMED,
    "icd10": ICD10CM, "icd-10": ICD10CM, "icd10cm": ICD10CM, "icd-10-cm": ICD10CM, "i10": ICD10CM, "i10c": ICD10CM,
    "http://hl7.org/fhir/sid/icd-10-cm": ICD10CM,
    "rxnorm": RXNORM, "rxn": RXNORM, "http://www.nlm.nih.gov/research/umls/rxnorm": RXNORM,
    "ucum": UCUM, "http://unitsofmeasure.org": UCUM,
}


def resolve_system(system: str | None) -> str | None:
    if not system:
        return None
    return _ALIASES.get(system.strip().lower())


def normalize_name(text: str) -> str:
    """Lower-case, alphanumerics only: 'LDL-Cholesterol' and 'ldl cholesterol' compare equal."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


LOINC_CODE = re.compile(r"^\d{1,7}-\d$")


def lookup(conn: Connection, system: str, code: str) -> dict[str, Any] | None:
    canonical = resolve_system(system)
    if canonical is None:
        return None
    row = conn.execute(
        "SELECT system, code, display, synonyms, properties FROM code_system_concepts WHERE system = %s AND code = %s",
        (canonical, code.strip()),
    ).fetchone()
    if row is None:
        return None
    return {**row, **SYSTEMS[canonical]}


def validate(conn: Connection, system: str, code: str, display: str | None = None) -> dict[str, Any]:
    canonical = resolve_system(system)
    if canonical is None:
        return {"result": False, "message": f"Unknown code system '{system}'."}
    concept = lookup(conn, canonical, code)
    if concept is None:
        return {"result": False, "message": f"Code '{code}' is not in the Bioverse subset of {SYSTEMS[canonical]['name']}."}
    if display and normalize_name(display) not in {normalize_name(concept["display"]), *map(normalize_name, concept["synonyms"])}:
        return {"result": False, "display": concept["display"],
                "message": f"Display '{display}' does not match '{concept['display']}'."}
    return {"result": True, "display": concept["display"]}


def map_lab_name(conn: Connection, name: str) -> dict[str, Any] | None:
    """Map a lab test name as printed on a report ('LDL Cholesterol', 'HbA1c') to a LOINC code.

    Exact match on the normalized display or a synonym only. No fuzzy guessing: an unmapped test
    keeps its printed name and a local code, which is safer than a wrong LOINC code.
    """
    key = normalize_name(name)
    if not key:
        return None
    for row in conn.execute(
        "SELECT code, display, synonyms, properties FROM code_system_concepts WHERE system = %s", (LOINC,)
    ).fetchall():
        if key == normalize_name(row["display"]) or key in {normalize_name(s) for s in row["synonyms"]}:
            return {"system": LOINC, "code": row["code"], "display": row["display"], "properties": row["properties"]}
    return None


def ucum_code(conn: Connection, unit: str | None) -> str | None:
    """The UCUM code for a unit as written ('mg/dL', 'K/uL', 'mEq/L'), or None when unknown."""
    if not unit:
        return None
    unit = unit.strip()
    row = conn.execute(
        "SELECT code FROM code_system_concepts WHERE system = %s AND (code = %s OR %s = ANY(synonyms))",
        (UCUM, unit, unit.lower()),
    ).fetchone()
    return row["code"] if row else None


def local_code(name: str) -> str:
    """Code for a test with no LOINC mapping. Stored in observations.loinc_code with a 'local:' prefix."""
    return "local:" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "unnamed")


def is_local(code: str) -> bool:
    return code.startswith("local:")


# ---------------------------------------------------------------------------------------------
# Seed content. (system, code, display, synonyms, properties)
# ---------------------------------------------------------------------------------------------

_LAB = [
    ("13457-7", "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation",
     ["ldl", "ldl cholesterol", "ldl-c", "ldl chol", "ldl cholesterol calc", "ldl calculated", "ldl-cholesterol"], "mg/dL"),
    ("2089-1", "Cholesterol in LDL [Mass/volume] in Serum or Plasma",
     ["ldl direct", "direct ldl", "ldl cholesterol direct"], "mg/dL"),
    ("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma",
     ["hdl", "hdl cholesterol", "hdl-c", "hdl chol", "hdl-cholesterol"], "mg/dL"),
    ("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", ["triglycerides", "triglyceride", "trig", "tg"], "mg/dL"),
    ("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma",
     ["total cholesterol", "cholesterol", "cholesterol total", "tc", "chol"], "mg/dL"),
    ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood",
     ["hba1c", "hemoglobin a1c", "haemoglobin a1c", "a1c", "glycated hemoglobin", "glycohemoglobin"], "%"),
    ("2345-7", "Glucose [Mass/volume] in Serum or Plasma", ["glucose", "blood glucose", "glucose serum", "glu"], "mg/dL"),
    ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma", ["fasting glucose", "glucose fasting", "fbg"], "mg/dL"),
    ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", ["creatinine", "creat", "creatinine serum"], "mg/dL"),
    ("33914-3", "Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] in Serum or Plasma by Creatinine-based formula (MDRD)",
     ["egfr", "estimated gfr", "gfr"], "mL/min/{1.73_m2}"),
    ("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", ["bun", "urea nitrogen", "blood urea nitrogen"], "mg/dL"),
    ("2951-2", "Sodium [Moles/volume] in Serum or Plasma", ["sodium", "na"], "mmol/L"),
    ("2823-3", "Potassium [Moles/volume] in Serum or Plasma", ["potassium", "k"], "mmol/L"),
    ("2075-0", "Chloride [Moles/volume] in Serum or Plasma", ["chloride", "cl"], "mmol/L"),
    ("2028-9", "Carbon dioxide, total [Moles/volume] in Serum or Plasma", ["co2", "carbon dioxide", "bicarbonate", "total co2"], "mmol/L"),
    ("17861-6", "Calcium [Mass/volume] in Serum or Plasma", ["calcium", "ca"], "mg/dL"),
    ("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
     ["alt", "alanine aminotransferase", "sgpt", "alt sgpt"], "U/L"),
    ("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
     ["ast", "aspartate aminotransferase", "sgot", "ast sgot"], "U/L"),
    ("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", ["total bilirubin", "bilirubin", "bilirubin total"], "mg/dL"),
    ("1751-7", "Albumin [Mass/volume] in Serum or Plasma", ["albumin"], "g/dL"),
    ("6690-2", "Leukocytes [#/volume] in Blood by Automated count", ["wbc", "white blood cells", "white blood cell count", "leukocytes"], "10*3/uL"),
    ("789-8", "Erythrocytes [#/volume] in Blood by Automated count", ["rbc", "red blood cells", "red blood cell count", "erythrocytes"], "10*6/uL"),
    ("718-7", "Hemoglobin [Mass/volume] in Blood", ["hemoglobin", "haemoglobin", "hgb", "hb"], "g/dL"),
    ("4544-3", "Hematocrit [Volume Fraction] of Blood by Automated count", ["hematocrit", "haematocrit", "hct"], "%"),
    ("777-3", "Platelets [#/volume] in Blood by Automated count", ["platelets", "platelet count", "plt"], "10*3/uL"),
    ("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", ["tsh", "thyroid stimulating hormone", "thyrotropin"], "m[IU]/L"),
    ("3024-7", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma", ["free t4", "ft4", "t4 free", "thyroxine free"], "ng/dL"),
    ("2276-4", "Ferritin [Mass/volume] in Serum or Plasma", ["ferritin"], "ng/mL"),
    ("2132-9", "Cobalamin (Vitamin B12) [Mass/volume] in Serum or Plasma", ["vitamin b12", "b12", "cobalamin"], "pg/mL"),
    ("1989-3", "25-Hydroxyvitamin D3+25-Hydroxyvitamin D2 [Mass/volume] in Serum or Plasma",
     ["vitamin d", "25-oh vitamin d", "25 hydroxy vitamin d", "vitamin d 25-hydroxy", "25-hydroxyvitamin d"], "ng/mL"),
    ("30522-7", "C reactive protein [Mass/volume] in Serum or Plasma by High sensitivity method",
     ["hs-crp", "hscrp", "high sensitivity crp", "c-reactive protein high sensitivity"], "mg/L"),
    # Panels and document types (used as DiagnosticReport / DocumentReference codes).
    ("24331-1", "Lipid 1996 panel - Serum or Plasma", ["lipid panel", "lipid profile", "lipids"], None),
    ("24323-8", "Comprehensive metabolic 2000 panel - Serum or Plasma", ["comprehensive metabolic panel", "cmp"], None),
    ("51990-0", "Basic metabolic panel - Blood", ["basic metabolic panel", "bmp"], None),
    ("58410-2", "CBC panel - Blood by Automated count", ["cbc", "complete blood count", "full blood count", "fbc"], None),
    ("11502-2", "Laboratory report", ["lab report", "laboratory report"], None),
    # Vital signs.
    ("8480-6", "Systolic blood pressure", ["systolic", "systolic blood pressure"], "mm[Hg]"),
    ("8462-4", "Diastolic blood pressure", ["diastolic", "diastolic blood pressure"], "mm[Hg]"),
]

_SNOMED = [
    ("55822004", "Hyperlipidemia", ["high cholesterol", "hyperlipidaemia"]),
    ("38341003", "Hypertensive disorder, systemic arterial", ["hypertension", "high blood pressure"]),
    ("44054006", "Diabetes mellitus type 2", ["type 2 diabetes", "t2dm"]),
    ("714628002", "Prediabetes", ["prediabetes", "pre-diabetes"]),
    ("29857009", "Chest pain", ["chest pain", "chest discomfort"]),
    ("271807003", "Eruption of skin", ["rash", "skin rash"]),
    ("37796009", "Migraine", ["migraine"]),
    ("764146007", "Penicillin (substance)", ["penicillin"]),
    ("387406002", "Sulfonamide (substance)", ["sulfa drugs", "sulfonamides", "sulfa"]),
]

_ICD10 = [
    ("E78.5", "Hyperlipidemia, unspecified", ["hyperlipidemia"]),
    ("I10", "Essential (primary) hypertension", ["hypertension"]),
    ("E11.9", "Type 2 diabetes mellitus without complications", ["type 2 diabetes"]),
    ("R73.03", "Prediabetes", ["prediabetes"]),
    ("R07.9", "Chest pain, unspecified", ["chest pain"]),
    ("R21", "Rash and other nonspecific skin eruption", ["rash"]),
    ("G43.909", "Migraine, unspecified, not intractable, without status migrainosus", ["migraine"]),
    ("Z88.0", "Allergy status to penicillin", ["penicillin allergy"]),
]

# Ingredient-level RxNorm concepts for the drugs in the demo record.
_RXNORM = [
    ("83367", "atorvastatin", ["atorvastatin", "lipitor"]),
    ("17767", "amlodipine", ["amlodipine", "norvasc"]),
    ("6809", "metformin", ["metformin"]),
    ("29046", "lisinopril", ["lisinopril"]),
    ("70618", "penicillin", ["penicillin"]),
]

# UCUM code, display, and the ways reports write it (lower-case).
_UCUM = [
    ("mg/dL", "milligram per deciliter", ["mg/dl"]),
    ("mmol/L", "millimole per liter", ["mmol/l"]),
    ("meq/L", "milliequivalent per liter", ["meq/l"]),
    ("%", "percent", ["percent"]),
    ("g/dL", "gram per deciliter", ["g/dl"]),
    ("g/L", "gram per liter", ["g/l"]),
    ("U/L", "enzyme unit per liter", ["u/l", "iu/l"]),
    ("10*3/uL", "thousand per microliter", ["k/ul", "x10e3/ul", "10^3/ul", "10*3/ul", "thou/ul", "k/µl"]),
    ("10*6/uL", "million per microliter", ["m/ul", "x10e6/ul", "10^6/ul", "10*6/ul", "mil/ul"]),
    ("10*9/L", "billion per liter", ["x10e9/l", "10^9/l", "10*9/l"]),
    ("mL/min/{1.73_m2}", "milliliter per minute per 1.73 square meter", ["ml/min/1.73m2", "ml/min/1.73 m2", "ml/min/{1.73_m2}"]),
    ("m[IU]/L", "milli international unit per liter", ["miu/l", "uiu/ml", "µiu/ml", "mu/l"]),
    ("ng/dL", "nanogram per deciliter", ["ng/dl"]),
    ("ng/mL", "nanogram per milliliter", ["ng/ml"]),
    ("pg/mL", "picogram per milliliter", ["pg/ml"]),
    ("mg/L", "milligram per liter", ["mg/l"]),
    ("fL", "femtoliter", ["fl"]),
    ("mm[Hg]", "millimeter of mercury", ["mmhg", "mm hg"]),
]


def seed_rows() -> list[tuple[str, str, str, list[str], dict[str, Any]]]:
    rows: list[tuple[str, str, str, list[str], dict[str, Any]]] = []
    for code, display, syn, unit in _LAB:
        rows.append((LOINC, code, display, syn, {"unit": unit} if unit else {"panel_or_document": True}))
    rows += [(SNOMED, c, d, s, {}) for c, d, s in _SNOMED]
    rows += [(ICD10CM, c, d, s, {}) for c, d, s in _ICD10]
    rows += [(RXNORM, c, d, s, {"tty": "IN"}) for c, d, s in _RXNORM]
    rows += [(UCUM, c, d, s, {}) for c, d, s in _UCUM]
    return rows
