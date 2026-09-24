"""Front-door routing to research studies and clinical trials."""

from bioverse.agents.intents import register

register(
    "research",
    description="clinical trials or research studies they could join, e.g. 'is there a clinical trial for me'",
    # "trial of" is left alone: "a trial of a new tablet" is about medication, not research.
    pattern=r"\b(clinical trials?|research stud(?:y|ies)|trials?\b(?!\s+of\b)|stud(?:y|ies) for)",
    to="/research",
    label="Open research studies",
    reply="Here are research studies you can browse. You choose whether Bioverse may match you to studies.",
    priority=60,
)
