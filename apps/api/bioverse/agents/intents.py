"""Front-door intents that send the patient to a screen ("show me my bills" -> /billing).

The orchestrator and the triage agent read this registry, so a module adds front-door routing
by dropping a file in `bioverse/intents/` that calls `register(...)`. No edits to the
orchestrator or triage agent are needed.

Symptom routing (intake, specialty, urgency) is not an intent link: it stays in triage.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentLink:
    name: str               # stable id, snake_case; becomes a value of TriageResult.intent
    description: str        # one line, shown to Claude so it can pick this intent
    pattern: re.Pattern[str]  # rules-mode matcher, tried against the patient's latest message
    to: str                 # web route to open
    label: str              # button text
    reply: str              # what Bioverse says before the button
    priority: int = 100     # lower is tried first in rules mode


REGISTRY: dict[str, IntentLink] = {}


def register(
    name: str,
    *,
    description: str,
    pattern: str,
    to: str,
    label: str,
    reply: str,
    priority: int = 100,
) -> None:
    if name in REGISTRY:
        raise ValueError(f"intent {name!r} registered twice")
    REGISTRY[name] = IntentLink(
        name=name,
        description=description,
        pattern=re.compile(pattern, re.IGNORECASE),
        to=to,
        label=label,
        reply=reply,
        priority=priority,
    )


# Core intents.
register(
    "health_story",
    description="a summary of their health over time, e.g. 'what happened with my health this year'",
    pattern=r"\b(this year|my health|health story|summary of my|what happened)",
    to="/story", label="Open my health story",
    reply="Here is your health story, built from your visits, results and care plan.",
    priority=10,
)
register(
    "results",
    description="a lab or test result or report",
    pattern=r"\b(lab|result|report|blood test|cholesterol level|explain my)",
    to="/results", label="Open my results",
    reply="I can walk you through your results. Your latest reports are ready to open.",
    priority=20,
)
register(
    "care_plan",
    description="their care plan, tasks, or medication schedule",
    pattern=r"\b(care plan|my plan|my tasks|medication schedule)",
    to="/plan", label="Open my care plan",
    reply="Here is your care plan, with what's done and what's next.",
    priority=30,
)


def load_all() -> None:
    """Import every module in bioverse/intents so their register() calls run. Idempotent."""
    import bioverse.intents as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{info.name}")


def ordered() -> list[IntentLink]:
    return sorted(REGISTRY.values(), key=lambda i: (i.priority, i.name))


load_all()
