"""Front-door routing for the insurance card, coverage status and benefits.

Tried before billing (priority 60): "am I covered" and "check my benefits" belong here, while bills,
costs, claims and "is this covered by my insurance" stay with billing.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = r"^(?!.*\b(pain|hurts?|ache|bleed|dizz|faint|breath|chest|fever|rash|vomit|swell)).*"

register(
    "insurance",
    description="their insurance card, member ID, whether their insurance is active, or their plan benefits",
    pattern=_NOT_A_SYMPTOM + (
        r"\b(insurance card|insurance id|member id|digital card|am i (still )?covered|is my (insurance|coverage|plan) "
        r"(still )?(active|valid)|check my (benefits|coverage|eligibility)|my benefits|eligibility"
        r"|new insurance|scan my (insurance )?card|prior auth\w*|pre-?authori[sz]ation)"
    ),
    to="/insurance",
    label="Open my insurance card",
    reply="Here is your insurance card and coverage. You can check your benefits with your plan from there.",
    priority=55,
)
