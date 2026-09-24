"""Front-door routing to photo questions: "what is this pill?" and "can I send a photo of my rash?".

The orchestrator screens every message for red flags BEFORE any intent is tried, so "rash and my throat is
swelling" is an emergency, never a photo link. On top of that, both patterns refuse messages that carry
warning-sign or symptom-severity words, so a worried message falls through to triage (safety check, intake,
Claude's own red-flag judgement) instead of being sent to a camera.

Priority 52: after the core intents and family (50), before wellness (55), documents (60) and pharmacy (62).
"""

from bioverse.agents.intents import register

# Warning signs and severity words: never route these to a photo screen.
_NO_WARNING_SIGNS = (
    r"^(?!.*\b(breath\w*|swell\w*|swollen|throat|tongue|lips?|face|fever\w*|bleed\w*|blood|spreading|severe|"
    r"worst|faint\w*|dizz\w*|chest|pain\w*|hurts?|allerg\w*|reaction|overdos\w*|took too many|swallowed|"
    r"child|baby|toddler|emergency|urgent)\b)"
)

register(
    "photo_medicine",
    description="identifying a pill, tablet or medicine box they have in front of them, e.g. 'what is this "
                "pill' or 'check this medicine box against my prescriptions'",
    pattern=_NO_WARNING_SIGNS + (
        r".*(\b(what|which) (is|are|'s) (this|these|that) (pills?|tablets?|capsules?|medicines?|medications?|meds|drugs?)\b"
        r"|\bwhat'?s (this|that) (pill|tablet|capsule|medicine|medication|drug)\b"
        r"|\bidentify (a |this |my )?(pill|tablet|capsule|medicine|medication)\b"
        r"|\b(photo|picture|pic) of (a |my |this )?(pills?|tablets?|medicine|medication|medicine box|pill bottle|label)\b"
        r"|\b(scan|check) (a |this |my )?(medicine|pill|medication) (box|bottle|label|pack)\b)"
    ),
    to="/ask/photo?kind=medicine",
    label="Take a photo of the box",
    reply="Take a photo of the box or label, and I'll check it against your prescriptions.",
    priority=52,
)

register(
    "photo_skin",
    description="sending a photo of a rash, mole or skin spot to their care team (not describing new symptoms)",
    pattern=_NO_WARNING_SIGNS + (
        r".*(\b(photo|picture|pic|image)s? of (a |my |this |the )?(rash|mole|spot|skin|freckle|lesion)\b"
        r"|\b(rash|mole|skin|spot) (photo|picture|pic)s?\b"
        r"|\b(send|show|share|upload|take) (a |an )?(photo|picture|pic)\b.{0,30}\b(rash|mole|spot|skin)\b)"
    ),
    to="/ask/photo?kind=skin",
    label="Send a skin photo",
    reply="You can send a photo of it. I'll ask a few safety questions first, and I won't try to diagnose it.",
    priority=52,
)
