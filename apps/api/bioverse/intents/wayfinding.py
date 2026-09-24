"""Front-door routing to in-hospital wayfinding ("where is the pharmacy", "where do I park").

Priority 58: before the pharmacy intent (62), which would otherwise take "where is the pharmacy".
Patterns only match questions about finding a place, never symptoms: symptom words veto the match,
so "where do I go with chest pain" stays with triage and its red-flag screen.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|bleed\w*|dizz\w*|faint\w*|breath\w*|chest|fever|rash|vomit\w*|swell\w*|"
    r"swollen|sick|fell|fall(?:en|ing)?|unconscious|seizure|emergency)\b)"
)
_WHERE = r"(?:where(?:'s| is| are| do i find| can i find)|how do i (?:get|go) to|how do i find|directions to|way to)"

register(
    "wayfinding_pharmacy",
    description="finding the pharmacy inside the hospital building, e.g. 'where is the pharmacy'",
    pattern=_NOT_A_SYMPTOM + r".*\b" + _WHERE + r"\s+(?:the\s+)?(?:hospital\s+|outpatient\s+)?pharmacy\b",
    to="/find-your-way?to=pharmacy",
    label="Show me the way",
    reply="The Outpatient Pharmacy is on Level 1. Here are step-by-step directions and a map.",
    priority=58,
)

register(
    "wayfinding_cardiology",
    description="getting to the cardiology clinic (Northside Heart Centre) inside the hospital, "
                "e.g. 'how do I get to cardiology'",
    pattern=_NOT_A_SYMPTOM + r".*\b" + _WHERE
    + r"\s+(?:the\s+)?(?:cardiology|heart (?:centre|center|clinic))\b",
    to="/find-your-way?to=cardiology",
    label="Show me the way",
    reply="Cardiology is in the Northside Heart Centre on Level 3. Here are step-by-step directions and a map.",
    priority=58,
)

register(
    "wayfinding_parking",
    description="where to park at the hospital, e.g. 'where do I park'",
    pattern=_NOT_A_SYMPTOM
    + r".*\b(?:where (?:do|can|should) i park|" + _WHERE
    + r"\s+(?:the\s+)?(?:visitor\s+|accessible\s+)?(?:parking|car park|parking garage))\b",
    to="/find-your-way?to=parking",
    label="Show parking and directions",
    reply="Visitor parking is on Level P, under the main building. Here's how to get from there to where you're going.",
    priority=58,
)

register(
    "wayfinding",
    description="finding a place inside the hospital building: restrooms, cafe, elevators, registration, "
                "the information desk, imaging or the blood draw lab, or a hospital map",
    pattern=_NOT_A_SYMPTOM
    + r".*\b(?:find my way|hospital map|map of the hospital|you are here|"
    + _WHERE + r"\s+(?:the\s+)?(?:restrooms?|toilets?|bathrooms?|cafe|cafeteria|elevators?|lifts?|"
    r"information desk|registration(?: desk)?|imaging|x-?ray|radiology|blood draw))\b",
    to="/find-your-way",
    label="Find your way",
    reply="Here's a map of the hospital with step-by-step directions.",
    priority=58,
)
