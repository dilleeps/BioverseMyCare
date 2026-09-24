"""Front-door routing to Family & Caregivers."""

from bioverse.agents.intents import register

# Symptom words veto the match: "my son has a rash" is a symptom for triage, not a request for this screen.
_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|dizz\w*|fever|bleed\w*|swell\w*|swollen|rash|cough\w*|vomit\w*|nause\w*|"
    r"sick|fell|fall(?:en|ing)?|breath\w*|unconscious|seizure)\b)"
)

register(
    "family",
    description="caring for a family member or dependent, caregiver access, or acting on someone's behalf",
    pattern=_NOT_A_SYMPTOM
    + r".*\b(my mother|my mom|my father|my dad|my child|my son|my daughter|caregivers?|family members?|on behalf of)\b",
    to="/family",
    label="Open family and caregivers",
    reply="Here are the people you care for, and who can see your care.",
    priority=50,
)
