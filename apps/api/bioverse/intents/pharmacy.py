"""Front-door routing for prescriptions, refills and pharmacies.

"medication schedule" belongs to the core care_plan intent (priority 30), which is tried first.
"""

from bioverse.agents.intents import register

# Symptom or side-effect language stays with triage (red-flag screen, intake, Doctor Agent).
_NOT_A_SYMPTOM = r"^(?!.*\b(pain|hurts?|ache|bleed|dizz|faint|breath|chest|fever|rash|vomit|swell|side effects?|reaction|allerg))"

register(
    "pharmacy",
    description="prescriptions, refills, picking up medicine, choosing a pharmacy, or tracking their medication doses",
    pattern=_NOT_A_SYMPTOM + (
        r".*\b(refills?|prescriptions?|pharmacy|pharmacies|pharmacist|pick up my|pick my .{0,30}\bup"
        r"|my (medication|medicine|meds|pills)\b(?! schedule))"
    ),
    to="/pharmacy",
    label="Open my pharmacy",
    reply="Here are your prescriptions, refills and pharmacy.",
    priority=62,
)
