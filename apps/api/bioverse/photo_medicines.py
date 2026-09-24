"""Medicine photo questions: plain-language information for the demo drugs, and matching a name read from a
package (or typed by the patient) against the patient's own active prescriptions.

What this module will say, and nothing more:
- which of the patient's active prescriptions the package looks like,
- the instructions on that prescription (its `sig`, written by the prescriber),
- the short, static, plain-language facts below.

It never gives new dosing advice. Matching is exact on a generic or brand name (after removing salts and
dosage-form words): similar-looking names are a known source of medication errors, so a near miss is
reported as "can't confirm", never as a match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from psycopg import Connection

CAUTION = "Check the label; if in doubt, ask your pharmacist."

# Plain-language information for the demo drugs. Static and curated for this demo: not complete,
# and not medical advice. Keys are the pharmacy module's drug codes.
DRUG_INFO: dict[str, dict] = {
    "atorvastatin": {
        "name": "Atorvastatin",
        "brands": ["lipitor"],
        "what_for": "A statin. It lowers LDL (\"bad\") cholesterol, which lowers the chance of a heart attack or stroke.",
        "good_to_know": ["It works quietly: you won't feel it working.",
                         "Large amounts of grapefruit juice can raise its level in your blood."],
        "common_side_effects": ["Muscle aches", "Diarrhea", "Joint pain", "Stuffy nose"],
        "call_if": ["Unexplained muscle pain, tenderness or weakness", "Dark or cola-colored urine",
                    "Yellowing of the skin or eyes"],
    },
    "amlodipine": {
        "name": "Amlodipine",
        "brands": ["norvasc"],
        "what_for": "A calcium channel blocker. It lowers blood pressure and can ease some kinds of chest pain.",
        "good_to_know": ["Swollen ankles are a common side effect; tell your care team if it bothers you."],
        "common_side_effects": ["Swollen ankles or feet", "Flushing", "Headache", "Dizziness"],
        "call_if": ["Fainting or feeling like you might faint", "Fast or pounding heartbeat"],
    },
    "azithromycin": {
        "name": "Azithromycin",
        "brands": ["zithromax", "zpak", "z-pak"],
        "what_for": "An antibiotic. It treats some bacterial infections. It does not work for colds or flu.",
        "good_to_know": ["Antibiotics are prescribed for one illness at a time. Leftover tablets are not for "
                         "a new illness."],
        "common_side_effects": ["Upset stomach", "Diarrhea", "Nausea"],
        "call_if": ["Severe or watery diarrhea", "Fast or irregular heartbeat", "Rash, swelling or trouble breathing"],
    },
    "clarithromycin": {
        "name": "Clarithromycin",
        "brands": ["biaxin"],
        "what_for": "An antibiotic. It treats some bacterial infections.",
        "good_to_know": ["It can interact with statins such as atorvastatin and simvastatin. Tell your pharmacist "
                         "about every medicine you take."],
        "common_side_effects": ["Upset stomach", "Change in taste", "Diarrhea"],
        "call_if": ["Severe or watery diarrhea", "Fast or irregular heartbeat", "Rash, swelling or trouble breathing"],
    },
    "simvastatin": {
        "name": "Simvastatin",
        "brands": ["zocor"],
        "what_for": "A statin. It lowers LDL (\"bad\") cholesterol, which lowers the chance of a heart attack or stroke.",
        "good_to_know": ["Some antibiotics and heart medicines change how much of it is in your blood."],
        "common_side_effects": ["Muscle aches", "Constipation", "Headache"],
        "call_if": ["Unexplained muscle pain, tenderness or weakness", "Dark or cola-colored urine"],
    },
}

# Words printed on packages that are not the drug's name.
_NOISE = {
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps", "film", "coated", "filmcoated",
    "oral", "suspension", "solution", "mg", "mcg", "g", "ml", "calcium", "besylate", "besilate", "sodium",
    "hydrochloride", "hcl", "dihydrate", "monohydrate", "trihydrate", "extended", "release", "er", "xr", "sr",
    "usp", "bp", "generic", "by", "mouth", "rx", "only", "pill", "pills", "medicine", "medication", "box",
    "bottle", "my", "the", "a",
}

_BRANDS = {brand.replace("-", ""): code for code, info in DRUG_INFO.items() for brand in info["brands"]}

# Questions that ask for dosing beyond the prescription. These always go to a pharmacist.
DOSING_QUESTION = re.compile(
    r"\b(miss(ed)?|forg[eo]t|skip(ped)?|double|extra|another|more than|less than|too many|too much|how many|"
    r"how much|increase|decrease|stop(ping)?|half|halve|split|crush|chew|dose|dosage|overdos|with alcohol|"
    r"instead of|switch)\b",
    re.IGNORECASE,
)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower().replace("-", "")) if t]


def _name_words(name: str | None) -> set[str]:
    return {t for t in _tokens(name or "") if t not in _NOISE and not re.fullmatch(r"\d+(\.\d+)?(mg|mcg|g|ml)?", t)}


def drug_code_for(name: str | None) -> str | None:
    """The demo drug code a printed or typed name refers to, by exact generic or brand name. None otherwise."""
    words = _name_words(name)
    codes = {w if w in DRUG_INFO else _BRANDS.get(w) for w in words}
    # Every remaining word must name the same drug. "Amlodipine and benazepril" is a different product
    # from amlodipine, so a second, unknown word means "can't confirm".
    if len(codes) == 1 and None not in codes:
        return codes.pop()
    return None


def norm_strength(text: str | None) -> str | None:
    """'20 mg', '20mg', '20 MG' -> '20mg'. None when there's no number with a unit."""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|%)\b", text.lower())
    if not m:
        return None
    number = m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
    return f"{number}{m.group(2)}"


@dataclass
class Match:
    status: str                       # matched | not_active | unmatched
    code: str | None = None
    prescription: dict | None = None
    strength_mismatch: bool = False


def active_prescriptions(conn: Connection, patient_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT m.id::text, m.drug_code, m.drug_name, m.strength, m.sig, m.status, pr.name AS prescriber_name
        FROM medication_requests m JOIN practitioners pr ON pr.id = m.prescriber_id
        WHERE m.patient_id = %s AND m.status = 'active'
        ORDER BY m.authored_at DESC
        """,
        (patient_id,),
    ).fetchall()


def match(conn: Connection, patient_id: str, name: str | None, strength: str | None) -> Match:
    code = drug_code_for(name)
    active = active_prescriptions(conn, patient_id)
    if code is None:
        # Not a demo drug: the same name as the prescription, word for word, is still a match.
        words = _name_words(name)
        hits = [rx for rx in active if words and words == _name_words(rx["drug_name"])]
    else:
        hits = [rx for rx in active if rx["drug_code"] == code]
    if not hits:
        return Match(status="not_active" if code else "unmatched", code=code)
    wanted = norm_strength(strength)
    same = [rx for rx in hits if wanted and norm_strength(rx["strength"]) == wanted]
    rx = (same or hits)[0]
    mismatch = bool(wanted) and not same
    return Match(status="matched", code=code or rx["drug_code"], prescription=rx, strength_mismatch=mismatch)


def answer(m: Match, *, read_name: str | None, read_strength: str | None, question: str | None) -> dict:
    """The patient-facing answer. Only the prescription's own sig and the static facts above."""
    question = (question or "").strip()
    asks_dosing = bool(question) and bool(DOSING_QUESTION.search(question))
    if m.status != "matched":
        seen = " ".join(x for x in (read_name, read_strength) if x) or None
        if m.status == "not_active":
            headline = "I can't confirm this medicine."
            message = (f"It looks like {DRUG_INFO[m.code]['name'].lower()}, but that isn't one of your current "
                       "prescriptions, so I can't tell you anything about taking it.")
        else:
            headline = "I can't confirm this medicine."
            message = ("It doesn't match any of your current prescriptions. A pharmacist can identify it "
                       "for you.")
        return {"status": "unmatched", "headline": headline, "message": message, "seen": seen,
                "question_reply": ("Please ask a pharmacist before taking it." if question else None),
                "caution": CAUTION, "offer_pharmacist": True}

    rx = m.prescription
    info = DRUG_INFO.get(m.code or "")
    headline = f"This looks like your {rx['drug_name'].lower()} {rx['strength']}."
    warnings = []
    if m.strength_mismatch:
        warnings.append(f"The strength on this package ({read_strength}) is different from your prescription "
                        f"({rx['strength']}). Check with your pharmacist before taking it.")
    if asks_dosing:
        question_reply = ("I can't give dosing advice beyond what your prescription says. "
                          "Your pharmacist can answer this.")
    elif question:
        question_reply = ("I can only share your prescription's instructions and the basic information below. "
                          "For anything else, ask your pharmacist.")
    else:
        question_reply = None
    return {
        "status": "matched",
        "headline": headline,
        "message": f"Your prescription from {rx['prescriber_name']} says: {rx['sig']}",
        "prescription": {"id": rx["id"], "drug_name": rx["drug_name"], "strength": rx["strength"], "sig": rx["sig"],
                         "prescriber_name": rx["prescriber_name"]},
        "info": ({k: info[k] for k in ("what_for", "good_to_know", "common_side_effects", "call_if")}
                 if info else None),
        "warnings": warnings,
        "question_reply": question_reply,
        "caution": CAUTION,
        "offer_pharmacist": bool(warnings) or asks_dosing or bool(question),
    }
