"""Front-door routing for the Appointment and Visit Navigator and the Referral Manager."""

from bioverse.agents.intents import register

register(
    "visit_prep",
    description="getting ready for, checking in to, or following up on an appointment they already have, "
    "e.g. 'help me prepare questions for my next visit', 'what should I bring', 'I'm here for my appointment'",
    pattern=(
        r"\b(before my (?:next )?(?:visit|appointment)"
        r"|prepar\w*\s+(?:some\s+|my\s+)?(?:questions|for)"
        r"|check(?:ing)?[- ]in\b"
        r"|checklist"
        r"|(?<!book )(?<!schedule )my (?:next |upcoming )?(?:appointment|visit)\b)"
    ),
    to="/visits",
    label="Open my visits",
    reply="Here are your upcoming visits, with a checklist, directions, and a place to write down your questions.",
    priority=60,
)

register(
    "referrals",
    description="a referral to a specialist or service, e.g. 'where is my referral', 'the specialist said...'",
    pattern=r"\b(referral|referred|specialist said)",
    to="/referrals",
    label="Open my referrals",
    reply="Here are your referrals, where each one is, and what to do next.",
    priority=61,
)
