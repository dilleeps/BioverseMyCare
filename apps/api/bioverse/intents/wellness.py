"""Front-door routing to Wellness & Prevention."""

from bioverse.agents.intents import register

# Symptom words veto the match, so "I can't sleep because my chest hurts" stays with triage.
_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|dizz\w*|fever|bleed\w*|swell\w*|swollen|rash|cough\w*|vomit\w*|nause\w*|"
    r"can'?t sleep|cannot sleep|insomnia|sick)\b)"
)

register(
    "wellness",
    description="preventive care, screenings, vaccines, or wellness goals like exercise, sleep or steps",
    pattern=_NOT_A_SYMPTOM + r".*\b(screenings?|vaccin\w*|shots?|prevent\w*|exercis\w*|sleep|steps|wellness|goals?)\b",
    to="/wellness",
    label="Open wellness and prevention",
    reply="Here's your preventive checklist, your wellness goals and a quick lifestyle check-in.",
    priority=55,
)
