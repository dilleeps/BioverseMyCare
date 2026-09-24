"""Front-door routing for logging and viewing home vital signs.

Only explicit logging or tracking language matches ("log my blood pressure", "record my glucose", "my BP
readings"). Symptom language vetoes the match, so "my blood pressure is high and I have a headache" stays
with triage and its red-flag screen.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|dizz\w*|faint\w*|breath\w*|chest|headache|vision|numb\w*|weak\w*|"
    r"confus\w*|bleed\w*|vomit\w*|nause\w*|fever|sick|emergency)\b)"
)
_ACTION = r"(log|record|enter|add|track|save|input|upload|measure|check|see|show|view)"
_MEASURE = (r"(blood pressure|bp|blood sugar|glucose|sugar levels?|weight|heart rate|pulse|oxygen|spo2|"
            r"sats?|temperature|vitals?|vital signs)")

register(
    "vitals",
    description="logging or viewing home readings: blood pressure, glucose, weight, heart rate, oxygen or temperature",
    pattern=_NOT_A_SYMPTOM + (
        rf".*(\b{_ACTION}\b.{{0,20}}\b(my|a|the|new|today'?s)\b.{{0,12}}\b{_MEASURE}\b"
        rf"|\b{_MEASURE}\s+(readings?|log|numbers|trends?|history|meter|monitor|cuff)\b"
        r"|\bmy (bp|blood pressure|glucose|blood sugar) (today|this morning|tonight)\b"
        r"|\b(home|connect\w*|pair)\b.{0,20}\b(bp cuff|blood pressure (cuff|monitor)|glucometer|glucose meter|"
        r"scale|pulse oximeter|oximeter)\b)"
    ),
    to="/vitals",
    label="Open my vitals",
    reply="You can log a reading, snap a photo of your meter, or see your trends here.",
    priority=52,
)
