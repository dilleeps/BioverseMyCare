"""Front-door routing to online consultations ("talk to a doctor online", "see a doctor now", "video visit").

Symptom language stays with triage: the red-flag screen, safety checks and intake come first. Someone who
describes a symptom is routed by triage; someone who asks for an online doctor comes here, where the consult
request itself is screened again.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = r"^(?!.*\b(pain|hurts?|ache|bleed|dizz|faint|breath|chest|fever|rash|vomit|swell|numb|suicid|kill myself))"

register(
    "online_consult",
    description="an online consultation with a doctor now or soon, by message, video or phone, e.g. "
                "'talk to a doctor online', 'see a doctor now', 'video visit'",
    pattern=_NOT_A_SYMPTOM + (
        r".*\b(talk (?:to|with) (?:a |an )?(?:doctor|clinician|physician|gp)(?: online| now| today)?\b"
        r"|(?:see|speak (?:to|with)|chat (?:to|with)) (?:a |an )?(?:doctor|clinician|physician|gp) "
        r"(?:now|online|today|right now|virtually)"
        r"|video (?:visit|consult\w*|appointment|call with (?:a |my )?doctor)"
        r"|online (?:consult\w*|doctor|visit|appointment)"
        r"|virtual (?:visit|consult\w*|appointment)|telehealth|telemedicine|e-?visit)"
    ),
    to="/consult",
    label="See a doctor online",
    reply="You can consult a verified clinician online, by secure message, video or phone. "
          "Choose someone, or ask for the first available in a specialty.",
    priority=58,
)
