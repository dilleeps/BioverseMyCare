"""Front-door routing to the mood and anxiety checks.

The orchestrator runs the red-flag screen before any intent is matched, so "check my mood, I want to end
my life" never reaches this link: it gets crisis support first (tests/test_mind.py proves it).
"""

from bioverse.agents.intents import register

register(
    "mind_check",
    description="check their mood or anxiety, take a depression or anxiety questionnaire (PHQ-9, GAD-7), or keep a mood journal",
    pattern=r"(\b(check|track|log|rate)\b.{0,10}\bmy (mood|anxiety|mental health)\b"
            r"|\b(mood|anxiety|depression|mental health|wellbeing) (test|check|check-?in|screen\w*|quiz|questionnaire|journal|tracker)\b"
            r"|\bphq-?9\b|\bgad-?7\b)",
    to="/mind",
    label="Open mood & mind",
    reply="Here are the mood and anxiety check-ins, your mood journal and a breathing exercise. Support is always one tap away.",
    priority=51,
)
