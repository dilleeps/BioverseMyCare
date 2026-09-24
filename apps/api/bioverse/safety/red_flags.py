"""Deterministic red-flag screening.

This runs on every patient message BEFORE any model sees it, and its verdict can only be
raised by the model, never lowered (docs/04-safety-and-governance.md, "Red-flag and
emergency protocol"). The rules are deliberately conservative: a false alarm costs a
phone call, a miss can cost a life.

The ruleset is illustrative. A production ruleset is clinician-owned, versioned, and
released only after passing a labelled test set.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

RULESET_VERSION = "2026.09.2-demo"

EMERGENCY_NUMBER = os.getenv("BIOVERSE_EMERGENCY_NUMBER", "911")
CRISIS_LINE = os.getenv("BIOVERSE_CRISIS_LINE", "988")

# Words that negate a finding when they appear shortly before it ("no chest pain").
_NEGATION = re.compile(r"\b(no|not|denies|denied|without|never|none|isn't|wasn't|don't|doesn't)\b")
_NEGATION_WINDOW = 4  # words


def _pattern(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(alternatives) + r")", re.IGNORECASE)


# Findings that are emergencies on their own.
EMERGENCY_RULES: dict[str, re.Pattern[str]] = {
    "possible stroke": _pattern(
        r"face (?:is )?droop", r"drooping face", r"slurred speech", r"can'?t speak",
        r"(?:one|left|right) side (?:of my body )?(?:is )?(?:weak|numb)",
        r"sudden(?:ly)? (?:weak|numb|confus)", r"worst headache",
        r"speech (?:is |sounds |seems |has gone |went )?(?:slurred|weird|strange|garbled|funny|wrong)",
        r"(?:trouble|difficulty) (?:speaking|talking|finding (?:my )?words)",
        r"(?:arm|leg|hand|face) (?:is |went |has gone |feels )?(?:suddenly )?numb[^.]{0,60}(?:speech|speak|talk|words|vision)",
    ),
    "breathing emergency": _pattern(
        r"can'?t breathe", r"cannot breathe", r"struggling to breathe", r"choking",
        r"lips (?:are |turning )?blue", r"gasping",
        r"(?:hard|difficult) to breathe", r"difficulty breathing", r"can'?t catch my breath",
    ),
    "possible anaphylaxis": _pattern(
        r"throat (?:is )?(?:closing|swelling|swollen|tight)", r"tongue (?:is )?swell",
        r"severe allergic", r"anaphyla",
    ),
    "severe bleeding": _pattern(
        r"bleeding (?:that )?(?:won'?t|will not|doesn'?t) stop", r"vomiting blood",
        r"coughing (?:up )?blood", r"heavy bleeding", r"bleeding (?:very )?heavily",
    ),
    "bleeding in pregnancy": _pattern(
        r"pregnan[^.]{0,60}bleed", r"bleed[^.]{0,60}pregnan",
    ),
    "possible meningitis or sepsis": _pattern(
        r"stiff neck[^.]{0,80}fever", r"fever[^.]{0,80}stiff neck",
        r"rash (?:that )?(?:doesn'?t|does not|won'?t|will not) fade", r"non-?blanching",
    ),
    "unwell child or baby": _pattern(
        r"(?:baby|infant|newborn|toddler|child|son|daughter)[^.]{0,50}(?:floppy|limp|won'?t wake|can'?t wake|unresponsive|not breathing|turning blue)",
        r"\bfloppy\b",
    ),
    "loss of consciousness": _pattern(
        r"passed out", r"unconscious", r"unresponsive", r"seizure", r"fainted",
    ),
    "possible overdose": _pattern(r"overdos", r"took too many (?:pills|tablets)"),
    "chest pain with warning signs": _pattern(
        r"chest (?:pain|pressure|tightness|discomfort)[^.]{0,60}(?:arm|jaw|back|sweat|short(?:ness)? of breath|breathless|faint)",
        r"(?:pain|pressure|tightness|discomfort) in (?:my |the )?chest[^.]{0,60}(?:arm|jaw|back|sweat|short(?:ness)? of breath|breathless|faint)",
        r"crushing chest",
    ),
}

# Findings that point to a mental-health crisis: routed to a crisis line, not only emergency services.
CRISIS_RULE = _pattern(
    r"suicid", r"kill myself", r"end (?:my|it) (?:life|all)", r"want to die",
    r"self[- ]harm", r"hurt(?:ing)? myself",
    r"can'?t go on", r"no (?:point|reason) (?:in )?(?:living|going on|being alive)",
    r"don'?t want to (?:be here|be alive|live|wake up)", r"better off (?:dead|without me)",
)

# Findings that need a structured safety check before any routine flow continues.
SCREEN_TOPICS: dict[str, re.Pattern[str]] = {
    "chest": _pattern(
        r"chest (?:pain|pressure|tightness|discomfort|ache|hurts)",
        r"(?:pain|pressure|tightness|discomfort) in (?:my |the )?chest",
        r"heart (?:is |keeps |has been |feels like it'?s )?(?:pain|racing|pounding|fluttering|skipping)",
        r"palpitation",
    ),
    "headache": _pattern(r"headache", r"migraine"),
}

SAFETY_CHECKS: dict[str, dict] = {
    "chest": {
        "question": "Right now, do you have any of these?",
        "options": [
            {"id": "breathless", "label": "Shortness of breath"},
            {"id": "sweating", "label": "Sweating, nausea or feeling faint"},
            {"id": "radiating", "label": "Pain spreading to arm, jaw or back"},
            {"id": "ongoing", "label": "The discomfort is happening right now"},
        ],
    },
    "headache": {
        "question": "Is any of this true for your headache?",
        "options": [
            {"id": "sudden_severe", "label": "It came on suddenly and is the worst you've had"},
            {"id": "weakness", "label": "Weakness, numbness or trouble speaking"},
            {"id": "stiff_neck", "label": "Stiff neck with fever"},
            {"id": "head_injury", "label": "It started after a head injury"},
        ],
    },
}


@dataclass
class ScreenResult:
    level: str  # "emergency" | "crisis" | "screen" | "none"
    flags: list[str] = field(default_factory=list)
    topic: str | None = None
    ruleset: str = RULESET_VERSION


def _is_negated(text: str, start: int) -> bool:
    preceding = text[:start].split()[-_NEGATION_WINDOW:]
    return bool(_NEGATION.search(" ".join(preceding).lower()))


def _find(pattern: re.Pattern[str], text: str) -> bool:
    return any(not _is_negated(text, m.start()) for m in pattern.finditer(text))


def screen(text: str) -> ScreenResult:
    """Screen one patient message. Crisis outranks emergency outranks screen."""
    if _find(CRISIS_RULE, text):
        return ScreenResult(level="crisis", flags=["self-harm risk"])

    flags = [name for name, pattern in EMERGENCY_RULES.items() if _find(pattern, text)]
    if flags:
        return ScreenResult(level="emergency", flags=flags)

    for topic, pattern in SCREEN_TOPICS.items():
        if _find(pattern, text):
            return ScreenResult(level="screen", topic=topic)

    return ScreenResult(level="none")


def evaluate_safety_check(topic: str, selected: list[str]) -> ScreenResult:
    """Any positive answer on a safety check is an emergency. Unknown option IDs count as positive."""
    known = {o["id"]: o["label"] for o in SAFETY_CHECKS.get(topic, {}).get("options", [])}
    positives = [s for s in selected if s != "none"]
    if positives:
        return ScreenResult(level="emergency", flags=[known.get(s, s) for s in positives], topic=topic)
    return ScreenResult(level="none", topic=topic)


def emergency_message(result: ScreenResult) -> str:
    if result.level == "crisis":
        return (
            "I'm really glad you told me. You deserve support right now. "
            f"Please call or text {CRISIS_LINE} to reach the Suicide & Crisis Lifeline, available 24 hours a day. "
            f"If you are in immediate danger, call {EMERGENCY_NUMBER}. "
            "I've let your care team know so someone can follow up with you."
        )
    return (
        f"What you've described can be a sign of a medical emergency. Please call {EMERGENCY_NUMBER} now, "
        "or have someone take you to the nearest emergency department. Do not drive yourself. "
        "I've notified your care team and saved what you told me so they have it."
    )
