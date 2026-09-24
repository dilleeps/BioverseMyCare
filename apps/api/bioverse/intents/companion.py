"""Front-door routing to the health companion: dose reminders and "did I take my pill".

Tried before the pharmacy intent (62), whose "my medicine" pattern would otherwise take these. Symptom and
side-effect words veto the match so those messages stay with triage and the red-flag screen.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|bleed\w*|dizz\w*|faint\w*|breath\w*|chest|fever|rash|vomit\w*|nause\w*|"
    r"swell\w*|swollen|side effects?|reaction|allerg\w*|overdos\w*|too many|double dose|took two)\b)"
)

register(
    "companion",
    description="medicine reminders, or checking whether they already took today's dose, e.g. 'remind me to take "
    "my medicine', 'did I take my pill'",
    pattern=_NOT_A_SYMPTOM + (
        r".*\b(remind me to take|(?:medication|medicine|meds|pill|dose) reminders?"
        r"|did i (?:already )?take my|have i (?:already )?taken my|did i miss (?:my|a) (?:dose|pill|medicine|medication)"
        r"|(?:mark|log) (?:my )?(?:dose|pill)s? (?:as )?taken)"
    ),
    to="/companion",
    label="Open Today",
    reply="Here's today: your doses with a tap to mark each one taken, and your reminder settings.",
    priority=58,
)
