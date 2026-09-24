"""PHQ-9 and GAD-7: exact validated wording, response options, scoring and severity bands.

PHQ-9 and GAD-7 were developed by Drs. Robert L. Spitzer, Janet B.W. Williams, Kurt Kroenke and
colleagues, with an educational grant from Pfizer Inc. No permission is required to reproduce,
translate, display or distribute them. Item wording below is the published English version; do not edit
it, because the scores are only valid for the validated wording.

Severity bands (Kroenke 2001; Spitzer 2006):
    PHQ-9  0-4 minimal, 5-9 mild, 10-14 moderate, 15-19 moderately severe, 20-27 severe
    GAD-7  0-4 minimal, 5-9 mild, 10-14 moderate, 15-21 severe

PHQ-9 item 9 (thoughts of being better off dead or of self-harm) scored above 0 always starts the
crisis path, whatever the total.
"""

from __future__ import annotations

from typing import Any

from bioverse.safety import red_flags

ATTRIBUTION = ("Developed by Drs. Robert L. Spitzer, Janet B.W. Williams, Kurt Kroenke and colleagues, with an "
               "educational grant from Pfizer Inc. No permission required to reproduce, translate, display or "
               "distribute.")

OPTIONS = [
    {"value": 0, "label": "Not at all"},
    {"value": 1, "label": "Several days"},
    {"value": 2, "label": "More than half the days"},
    {"value": 3, "label": "Nearly every day"},
]

DIFFICULTY_OPTIONS = ["Not difficult at all", "Somewhat difficult", "Very difficult", "Extremely difficult"]

PHQ9_ITEMS = [
    "Little interest or pleasure in doing things",
    "Feeling down, depressed, or hopeless",
    "Trouble falling or staying asleep, or sleeping too much",
    "Feeling tired or having little energy",
    "Poor appetite or overeating",
    "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
    "Trouble concentrating on things, such as reading the newspaper or watching television",
    "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety "
    "or restless that you have been moving around a lot more than usual",
    "Thoughts that you would be better off dead or of hurting yourself in some way",
]

GAD7_ITEMS = [
    "Feeling nervous, anxious or on edge",
    "Not being able to stop or control worrying",
    "Worrying too much about different things",
    "Trouble relaxing",
    "Being so restless that it is hard to sit still",
    "Becoming easily annoyed or irritable",
    "Feeling afraid as if something awful might happen",
]

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "phq9": {
        "id": "phq9",
        "title": "PHQ-9",
        "name": "Mood check (PHQ-9)",
        "about": "Nine questions about mood over the last two weeks. Used by doctors worldwide.",
        "stem": "Over the last 2 weeks, how often have you been bothered by any of the following problems?",
        "items": PHQ9_ITEMS,
        "options": OPTIONS,
        "difficulty": "If you checked off any problems, how difficult have these problems made it for you to do "
                      "your work, take care of things at home, or get along with other people?",
        "difficulty_options": DIFFICULTY_OPTIONS,
        "max": 27,
        "loinc": "44261-6",
        "display": "Patient Health Questionnaire 9 item (PHQ-9) total score [Reported]",
        "attribution": ATTRIBUTION,
    },
    "gad7": {
        "id": "gad7",
        "title": "GAD-7",
        "name": "Anxiety check (GAD-7)",
        "about": "Seven questions about worry and anxiety over the last two weeks.",
        "stem": "Over the last 2 weeks, how often have you been bothered by the following problems?",
        "items": GAD7_ITEMS,
        "options": OPTIONS,
        "difficulty": "If you checked any problems, how difficult have they made it for you to do your work, take "
                      "care of things at home, or get along with other people?",
        "difficulty_options": DIFFICULTY_OPTIONS,
        "max": 21,
        "loinc": "70274-6",
        "display": "Generalized anxiety disorder 7 item (GAD-7) total score [Reported.PHQ]",
        "attribution": ATTRIBUTION,
    },
}

# (lowest total, band id, label) in ascending order.
BANDS: dict[str, list[tuple[int, str, str]]] = {
    "phq9": [(0, "minimal", "Minimal"), (5, "mild", "Mild"), (10, "moderate", "Moderate"),
             (15, "moderately_severe", "Moderately severe"), (20, "severe", "Severe")],
    "gad7": [(0, "minimal", "Minimal"), (5, "mild", "Mild"), (10, "moderate", "Moderate"), (15, "severe", "Severe")],
}

REVIEW_BANDS = {"moderate", "moderately_severe", "severe"}

# Plain-language meaning of each band. Screening language only: never a diagnosis.
EXPLAIN: dict[str, dict[str, str]] = {
    "phq9": {
        "minimal": "Your answers suggest few or no symptoms of depression right now.",
        "mild": "Your answers suggest mild symptoms of low mood. Many people have weeks like this. It can help to "
                "keep an eye on it and check again in a few weeks.",
        "moderate": "Your answers suggest moderate symptoms of depression. This is worth talking about with your "
                    "care team, and we've shared your result with them.",
        "moderately_severe": "Your answers suggest moderately severe symptoms of depression. Your care team has "
                             "your result and will follow up with you.",
        "severe": "Your answers suggest severe symptoms of depression. Your care team has your result and will "
                  "follow up with you soon.",
    },
    "gad7": {
        "minimal": "Your answers suggest few or no symptoms of anxiety right now.",
        "mild": "Your answers suggest mild symptoms of anxiety. Breathing exercises, movement and sleep can help, "
                "and you can check again in a few weeks.",
        "moderate": "Your answers suggest moderate symptoms of anxiety. This is worth talking about with your care "
                    "team, and we've shared your result with them.",
        "severe": "Your answers suggest severe symptoms of anxiety. Your care team has your result and will follow "
                  "up with you soon.",
    },
}

SCREENING_NOTE = ("This is a screening questionnaire, not a diagnosis. Only a clinician can tell you what your "
                  "result means for you.")


def band(instrument: str, total: int) -> tuple[str, str]:
    """(band id, label) for a total score."""
    chosen = BANDS[instrument][0]
    for entry in BANDS[instrument]:
        if total >= entry[0]:
            chosen = entry
    return chosen[1], chosen[2]


def score(instrument: str, items: list[int]) -> dict[str, Any]:
    """Validate and score one response. Raises ValueError for a wrong item count or value."""
    spec = INSTRUMENTS.get(instrument)
    if spec is None:
        raise ValueError(f"unknown instrument {instrument!r}")
    if len(items) != len(spec["items"]):
        raise ValueError(f"{spec['title']} has {len(spec['items'])} questions; answer every one")
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 3 for v in items):
        raise ValueError("Each answer is scored 0 to 3")
    total = sum(items)
    severity, label = band(instrument, total)
    item9 = items[8] if instrument == "phq9" else None
    return {
        "instrument": instrument,
        "total": total,
        "max": spec["max"],
        "severity": severity,
        "severity_label": label,
        "item9": item9,
        "crisis": bool(item9),
        "needs_review": severity in REVIEW_BANDS,
        "explanation": EXPLAIN[instrument][severity],
    }


def crisis_support() -> dict[str, Any]:
    """Shown the moment it is needed, and always reachable from the Mind screen. No database needed."""
    return {
        "title": "You don't have to go through this alone",
        "message": ("If you're having thoughts of hurting yourself or that you'd be better off dead, please reach out "
                    f"now. Call or text {red_flags.CRISIS_LINE} to reach the Suicide & Crisis Lifeline, any time, "
                    f"day or night. If you are in immediate danger, call {red_flags.EMERGENCY_NUMBER}."),
        "crisis_line": red_flags.CRISIS_LINE,
        "crisis_line_name": "988 Suicide & Crisis Lifeline",
        "emergency_number": red_flags.EMERGENCY_NUMBER,
        "chat_url": "https://988lifeline.org/chat/",
    }


RESOURCES = [
    {"title": "988 Suicide & Crisis Lifeline", "detail": "Call or text 988, or chat online. Free, confidential, 24/7.",
     "url": "https://988lifeline.org/"},
    {"title": "Crisis Text Line", "detail": "Text HOME to 741741 to reach a trained crisis counselor.",
     "url": "https://www.crisistextline.org/"},
    {"title": "SAMHSA National Helpline", "detail": "1-800-662-4357. Treatment referral and information, 24/7.",
     "url": "https://www.samhsa.gov/find-help/national-helpline"},
    {"title": "NIMH: Anxiety disorders", "detail": "Plain-language information from the National Institute of Mental Health.",
     "url": "https://www.nimh.nih.gov/health/topics/anxiety-disorders"},
    {"title": "NIMH: Depression", "detail": "Signs, treatments and how to find help.",
     "url": "https://www.nimh.nih.gov/health/topics/depression"},
]

MOOD_TAGS = ["sleep", "work", "family", "friends", "exercise", "health", "money", "stress", "rest", "outdoors"]
