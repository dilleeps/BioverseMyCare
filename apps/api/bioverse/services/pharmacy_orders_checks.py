"""Safety checks for online pharmacy orders: pure functions over a cart and a patient profile.

Everything here is a small, static DEMO table. It is not a clinical reference and is not exhaustive: the
patient sees a notice saying so, and anything that matters routes the order to a pharmacist, who decides.

A check produces findings. Each finding has a `severity`:

    block     the order can't go ahead as it is (quantity limit, age limit, controlled substance by delivery)
    high      serious warning; the patient must acknowledge it and a pharmacist reviews the order
    moderate  caution; acknowledged by the patient and reviewed by a pharmacist
    info      good to know; `review` may still be true (prescriptions, pharmacist-only products)

and `review: true` when it sends the order to pharmacist review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NOTICE = (
    "These checks use a short demo list of ingredients, interactions and allergies. They are not complete. "
    "A pharmacist reviews anything flagged, and you can always ask a pharmacist before you order."
)

# --- Prescription drugs: classes, controlled schedules, cold chain -------------------------------------------
# Keyed by `medication_requests.drug_code`. Codes not listed here are treated as a single ingredient with no class.

RX_PROFILE: dict[str, dict] = {
    "atorvastatin": {"classes": ["statin"]},
    "simvastatin": {"classes": ["statin"]},
    "amlodipine": {"classes": ["calcium_channel_blocker", "antihypertensive"]},
    "lisinopril": {"classes": ["ace_inhibitor", "antihypertensive"]},
    "enalapril": {"classes": ["ace_inhibitor", "antihypertensive"]},
    "losartan": {"classes": ["arb", "antihypertensive"]},
    "hydrochlorothiazide": {"classes": ["diuretic", "antihypertensive"]},
    "metoprolol": {"classes": ["beta_blocker", "antihypertensive"]},
    "warfarin": {"classes": ["anticoagulant"]},
    "apixaban": {"classes": ["anticoagulant"]},
    "rivaroxaban": {"classes": ["anticoagulant"]},
    "clopidogrel": {"classes": ["antiplatelet"]},
    "sertraline": {"classes": ["ssri"]},
    "fluoxetine": {"classes": ["ssri"]},
    "phenelzine": {"classes": ["maoi"]},
    "levothyroxine": {"classes": ["thyroid_hormone"]},
    "azithromycin": {"classes": ["macrolide", "antibiotic"]},
    "clarithromycin": {"classes": ["macrolide", "antibiotic"]},
    "amoxicillin": {"classes": ["penicillin", "antibiotic"]},
    "doxycycline": {"classes": ["tetracycline", "antibiotic"]},
    "sulfamethoxazole": {"classes": ["sulfonamide", "antibiotic"]},
    "oxycodone": {"classes": ["opioid"], "schedule": "II"},
    "hydrocodone": {"classes": ["opioid"], "schedule": "II", "ingredients": ["hydrocodone", "acetaminophen"]},
    "codeine": {"classes": ["opioid"], "schedule": "II"},
    "tramadol": {"classes": ["opioid"], "schedule": "IV"},
    "alprazolam": {"classes": ["benzodiazepine"], "schedule": "IV"},
    "lorazepam": {"classes": ["benzodiazepine"], "schedule": "IV"},
    "zolpidem": {"classes": ["sedative_hypnotic"], "schedule": "IV"},
    "methylphenidate": {"classes": ["stimulant"], "schedule": "II"},
    "insulin_glargine": {"classes": ["insulin"], "refrigerated": True},
    "semaglutide": {"classes": ["glp1_agonist"], "refrigerated": True},
}

INGREDIENT_NAMES = {
    "acetaminophen": "Acetaminophen", "hydrocodone": "Hydrocodone", "ibuprofen": "Ibuprofen",
    "naproxen": "Naproxen", "aspirin": "Aspirin", "diphenhydramine": "Diphenhydramine",
    "pseudoephedrine": "Pseudoephedrine", "phenylephrine": "Phenylephrine", "dextromethorphan": "Dextromethorphan",
}

CLASS_LABELS = {
    "nsaid": "anti-inflammatory pain relievers (NSAIDs)",
    "sedating_antihistamine": "sedating antihistamines",
    "decongestant": "decongestants",
    "antihistamine": "antihistamines",
    "statin": "statins",
    "opioid": "opioid pain relievers",
}

# --- Interactions ----------------------------------------------------------------------------------------------
# Each side is a class ("nsaid"), an ingredient ("ingredient:dextromethorphan"), a condition ("condition:hypertension")
# or a food ("food:grapefruit", which only needs side A to be present).


@dataclass(frozen=True)
class Rule:
    a: str
    b: str
    severity: str  # high | moderate | info
    title: str
    message: str


INTERACTIONS: list[Rule] = [
    Rule("nsaid", "anticoagulant", "high", "Bleeding risk",
         "Anti-inflammatory pain relievers such as ibuprofen, naproxen or aspirin raise the risk of bleeding when "
         "taken with a blood thinner. Acetaminophen is often a safer choice. A pharmacist will check with you."),
    Rule("nsaid", "antiplatelet", "high", "Bleeding risk",
         "Anti-inflammatory pain relievers raise the risk of stomach bleeding with antiplatelet medicines."),
    Rule("nsaid", "ace_inhibitor", "moderate", "May affect blood pressure and kidneys",
         "Anti-inflammatory pain relievers can make ACE inhibitors work less well and can strain the kidneys, "
         "especially with regular use."),
    Rule("nsaid", "arb", "moderate", "May affect blood pressure and kidneys",
         "Anti-inflammatory pain relievers can make blood pressure medicines such as losartan work less well and "
         "can strain the kidneys."),
    Rule("nsaid", "diuretic", "moderate", "May affect blood pressure and kidneys",
         "Anti-inflammatory pain relievers can make water pills work less well and can strain the kidneys."),
    Rule("nsaid", "ssri", "moderate", "Bleeding risk",
         "Anti-inflammatory pain relievers taken with SSRI antidepressants raise the risk of stomach bleeding."),
    Rule("decongestant", "condition:hypertension", "moderate", "Can raise blood pressure",
         "Decongestants such as pseudoephedrine and phenylephrine can raise blood pressure. With high blood pressure "
         "or blood pressure medicine, a pharmacist should check this first."),
    Rule("decongestant", "maoi", "high", "Dangerous rise in blood pressure",
         "Decongestants must not be taken with MAO inhibitor antidepressants."),
    Rule("sedating_antihistamine", "opioid", "high", "Extra drowsiness and slowed breathing",
         "Sedating antihistamines add to the drowsiness caused by opioid pain medicines."),
    Rule("sedating_antihistamine", "benzodiazepine", "high", "Extra drowsiness",
         "Sedating antihistamines add to the drowsiness caused by benzodiazepines."),
    Rule("sedating_antihistamine", "sedative_hypnotic", "high", "Extra drowsiness",
         "Sedating antihistamines add to the drowsiness caused by sleep medicines."),
    Rule("ingredient:dextromethorphan", "ssri", "moderate", "Serotonin effects",
         "Dextromethorphan cough medicine taken with SSRI antidepressants can rarely cause serotonin syndrome."),
    Rule("ingredient:dextromethorphan", "maoi", "high", "Serotonin effects",
         "Dextromethorphan must not be taken with MAO inhibitor antidepressants."),
    Rule("antacid", "tetracycline", "moderate", "Take at different times",
         "Antacids stop some antibiotics from being absorbed. Take them at least 2 hours apart."),
    Rule("antacid", "thyroid_hormone", "moderate", "Take at different times",
         "Antacids and calcium can stop levothyroxine from being absorbed. Take them at least 4 hours apart."),
    Rule("calcium", "thyroid_hormone", "moderate", "Take at different times",
         "Calcium can stop levothyroxine from being absorbed. Take them at least 4 hours apart."),
    Rule("calcium", "tetracycline", "moderate", "Take at different times",
         "Calcium stops some antibiotics from being absorbed. Take them at least 2 hours apart."),
    Rule("statin", "food:grapefruit", "info", "Grapefruit note",
         "Large amounts of grapefruit juice can raise statin levels. Avoid more than a small glass a day."),
]

# Allergy words on the patient record, mapped to what they cover. Anything else is matched by name.
ALLERGY_ALIASES: dict[str, dict[str, list[str]]] = {
    "penicillin": {"classes": ["penicillin"]},
    "sulfa": {"classes": ["sulfonamide"]},
    "sulfonamide": {"classes": ["sulfonamide"]},
    "nsaid": {"classes": ["nsaid"]},
    "aspirin": {"ingredients": ["aspirin"], "cross_classes": ["nsaid"]},
    "ibuprofen": {"ingredients": ["ibuprofen"], "cross_classes": ["nsaid"]},
    "latex": {"allergens": ["latex"]},
    "codeine": {"ingredients": ["codeine"]},
}

CARD_LIKE = re.compile(r"(?:\d[ -]?){12,19}")


@dataclass
class Line:
    """One thing in the cart or order: an OTC product or a prescription."""

    key: str
    kind: str                       # otc | rx
    name: str
    quantity: int = 1
    ingredients: list[dict] = field(default_factory=list)  # [{"code", "name"}]
    classes: list[str] = field(default_factory=list)
    allergens: list[str] = field(default_factory=list)
    pharmacist_only: bool = False
    min_age: int | None = None
    max_qty: int | None = None
    controlled_schedule: str | None = None
    refrigerated: bool = False
    medication_request_id: str | None = None


@dataclass
class Med:
    """A current medicine on the patient's record (an active prescription)."""

    id: str
    code: str
    name: str
    classes: list[str] = field(default_factory=list)
    ingredients: list[dict] = field(default_factory=list)


@dataclass
class PatientProfile:
    age: int | None
    allergies: list[str] = field(default_factory=list)
    meds: list[Med] = field(default_factory=list)
    hypertension: bool = False
    hypertension_reason: str = ""   # e.g. "you take Amlodipine 5 mg for blood pressure"


def rx_profile(code: str) -> dict:
    p = RX_PROFILE.get(code, {})
    ingredients = p.get("ingredients") or [code]
    return {
        "classes": list(p.get("classes", [])),
        "ingredients": [{"code": i, "name": INGREDIENT_NAMES.get(i, i.replace("_", " ").title())} for i in ingredients],
        "schedule": p.get("schedule"),
        "refrigerated": bool(p.get("refrigerated")),
    }


def _norm_allergy(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"\b(allerg(y|ies|ic)|drugs?|antibiotics?|medicines?|products?)\b", "", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t).strip()
    t = re.sub(r"\s+", " ", t)
    return t[:-1] if t.endswith("s") and not t.endswith("ss") and len(t) > 4 else t


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def run_checks(lines: list[Line], patient: PatientProfile, fulfillment: str | None = None) -> dict:
    """Every check over the cart plus current medicines. `fulfillment` is None while shopping."""
    findings: list[dict] = []

    def add(code, severity, title, message, keys, review):
        findings.append({"code": code, "severity": severity, "title": title, "message": message,
                         "lines": sorted(set(keys)), "review": review})

    # Current medicines that are not themselves in the cart as a prescription being ordered.
    in_cart_rx = {ln.medication_request_id for ln in lines if ln.medication_request_id}
    meds = [m for m in patient.meds if m.id not in in_cart_rx]

    # Sources: cart lines and current medicines, with what they contain.
    sources: list[dict] = [
        {"key": ln.key, "name": ln.name, "in_cart": True, "ingredients": {i["code"]: i["name"] for i in ln.ingredients},
         "classes": set(ln.classes)} for ln in lines
    ] + [
        {"key": f"med:{m.id}", "name": f"{m.name} (current medicine)", "in_cart": False,
         "ingredients": {i["code"]: i["name"] for i in m.ingredients}, "classes": set(m.classes)} for m in meds
    ]

    # 1. Quantity limits and age restrictions: hard stops.
    for ln in lines:
        if ln.max_qty is not None and ln.quantity > ln.max_qty:
            add("quantity_limit", "block", "Quantity limit",
                f"You can order up to {ln.max_qty} of {ln.name} in one order.", [ln.key], False)
        if ln.min_age is not None and patient.age is not None and patient.age < ln.min_age:
            add("age_restriction", "block", "Age restriction",
                f"{ln.name} is only sold to people aged {ln.min_age} or over.", [ln.key], False)

    # 2. Controlled substances: never delivered.
    for ln in lines:
        if ln.controlled_schedule:
            if fulfillment == "delivery":
                add("controlled_not_deliverable", "block", "Can't be delivered",
                    f"{ln.name} is a controlled medicine (schedule {ln.controlled_schedule}). Controlled medicines are "
                    "never delivered. Choose pickup at the clinic pharmacy, or remove it from this order.",
                    [ln.key], True)
            else:
                add("controlled_substance", "high", "Pickup only, with ID",
                    f"{ln.name} is a controlled medicine (schedule {ln.controlled_schedule}). It can't be delivered: "
                    "collect it at the clinic pharmacy with photo ID. A pharmacist reviews the order.",
                    [ln.key], True)

    # 3. Duplicate active ingredients across the cart and current medicines.
    dup_ingredient_keys: set[frozenset] = set()
    all_codes = sorted({c for s in sources for c in s["ingredients"]})
    for code in all_codes:
        having = [s for s in sources if code in s["ingredients"]]
        if len(having) >= 2 and any(s["in_cart"] for s in having):
            name = having[0]["ingredients"][code]
            dup_ingredient_keys.add(frozenset(s["key"] for s in having))
            add("duplicate_ingredient", "high", f"Two products with {name.lower()}",
                f"{name} is in {', '.join(s['name'] for s in having)}. Taking more than one product with the same "
                "ingredient can add up to too much. Use only one, or ask the pharmacist.",
                [s["key"] for s in having if s["in_cart"]] , True)

    # 4. Same class, different ingredients (e.g. ibuprofen and naproxen).
    for cls, label in CLASS_LABELS.items():
        having = [s for s in sources if cls in s["classes"]]
        if len(having) >= 2 and any(s["in_cart"] for s in having):
            if frozenset(s["key"] for s in having) in dup_ingredient_keys:
                continue
            add("duplicate_class", "moderate", f"More than one of the {label}",
                f"{', '.join(s['name'] for s in having)} are all {label}. Taking them together adds side effects "
                "without more benefit.", [s["key"] for s in having if s["in_cart"]], True)

    # 5. Interactions from the static table.
    def has(src: dict, side: str) -> bool:
        if side.startswith("ingredient:"):
            return side.split(":", 1)[1] in src["ingredients"]
        return side in src["classes"]

    for rule in INTERACTIONS:
        a_src = [s for s in sources if has(s, rule.a)]
        if not a_src:
            continue
        if rule.b.startswith("food:"):
            cart_a = [s for s in a_src if s["in_cart"]]
            if cart_a:
                add("advisory", rule.severity, rule.title, rule.message, [s["key"] for s in cart_a], False)
            continue
        if rule.b == "condition:hypertension":
            cart_a = [s for s in a_src if s["in_cart"]]
            if cart_a and patient.hypertension:
                why = f" (Your record: {patient.hypertension_reason}.)" if patient.hypertension_reason else ""
                add("interaction", rule.severity, rule.title,
                    f"{', '.join(s['name'] for s in cart_a)}: {rule.message}{why}",
                    [s["key"] for s in cart_a], rule.severity != "info")
            continue
        b_src = [s for s in sources if has(s, rule.b)]
        pairs = [(a, b) for a in a_src for b in b_src if a["key"] != b["key"] and (a["in_cart"] or b["in_cart"])]
        if pairs:
            names = sorted({a["name"] for a, _ in pairs} | {b["name"] for _, b in pairs})
            keys = [s["key"] for a, b in pairs for s in (a, b) if s["in_cart"]]
            add("interaction", rule.severity, rule.title, f"{' + '.join(names)}: {rule.message}", keys,
                rule.severity != "info")

    # 6. Allergies on the patient record.
    for raw in patient.allergies:
        term = _norm_allergy(raw)
        if not term:
            continue
        alias = ALLERGY_ALIASES.get(term) or next(
            (v for k, v in ALLERGY_ALIASES.items() if term.startswith(k) or k in term.split()), None)
        for ln in lines:
            ing = {i["code"] for i in ln.ingredients} | {i["name"].lower() for i in ln.ingredients}
            direct = cross = False
            if alias:
                direct = bool(set(alias.get("ingredients", [])) & ing
                              or set(alias.get("classes", [])) & set(ln.classes)
                              or set(alias.get("allergens", [])) & set(ln.allergens))
                cross = not direct and bool(set(alias.get("cross_classes", [])) & set(ln.classes))
            else:
                words = ing | set(ln.classes) | set(ln.allergens)
                direct = any(term == w or term in w.split() for w in words)
            if direct:
                add("allergy", "high", "Allergy on your record",
                    f"Your record lists an allergy to {raw}. {ln.name} may contain it. A pharmacist will check "
                    "before this is sent.", [ln.key], True)
            elif cross:
                add("allergy", "high", "Possible allergy",
                    f"Your record lists an allergy to {raw}. People with that allergy can react to {ln.name} too. "
                    "A pharmacist will check before this is sent.", [ln.key], True)

    # 7. Items that always need a pharmacist.
    for ln in lines:
        if ln.kind == "rx":
            add("rx_verification", "info", "Pharmacist check",
                f"A pharmacist checks every prescription before it's packed: {ln.name}.", [ln.key], True)
        elif ln.pharmacist_only and not ln.controlled_schedule:
            add("pharmacist_only", "info", "Pharmacist product",
                f"{ln.name} is sold only after a pharmacist has checked it's right for you.", [ln.key], True)

    # 8. Cold chain.
    cold = [ln for ln in lines if ln.refrigerated]
    if cold:
        add("cold_chain", "info", "Keep cold",
            f"{', '.join(ln.name for ln in cold)} must stay refrigerated. It's packed with an ice pack and handed to "
            "someone at the address, not left at the door.", [ln.key for ln in cold], False)

    order = {"block": 0, "high": 1, "moderate": 2, "info": 3}
    findings.sort(key=lambda f: (order[f["severity"]], f["code"], f["title"]))
    return {
        "findings": findings,
        "blocks": [f for f in findings if f["severity"] == "block"],
        "needs_acknowledgement": any(f["severity"] in ("high", "moderate") for f in findings),
        "requires_review": any(f["review"] for f in findings),
        "review_reasons": sorted({f["code"] for f in findings if f["review"]}),
        "cold_chain": bool(cold),
        "deliverable": not any(ln.controlled_schedule for ln in lines),
        "notice": NOTICE,
    }


# --- Demo payment tokens ---------------------------------------------------------------------------------------

DEMO_CARDS = {
    "demo_tok_visa": ("Visa", "4242"),
    "demo_tok_mastercard": ("Mastercard", "4444"),
    "demo_tok_amex": ("Amex", "0005"),
}
DECLINED_TOKEN = "demo_tok_declined"


class PaymentTokenError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_demo_token(token: str) -> tuple[str, str]:
    """Brand and last four of a demo card. Anything resembling a card number is refused, never stored."""
    if not isinstance(token, str) or not token.strip():
        raise PaymentTokenError("invalid_token", "Choose one of the demo cards.")
    if CARD_LIKE.search(token):
        raise PaymentTokenError(
            "card_number_rejected",
            "That looks like a card number. This is a demo: never enter real card details. Choose a demo card instead.",
        )
    token = token.strip()
    if token == DECLINED_TOKEN:
        raise PaymentTokenError("payment_declined", "The demo card was declined. Choose another demo card.")
    if token not in DEMO_CARDS:
        raise PaymentTokenError("invalid_token", "Only demo payment tokens are accepted. Choose one of the demo cards.")
    return DEMO_CARDS[token]
