"""Front-door routing to the food log, the photo scan and the weight coach. Patterns stay specific.

Symptom words veto every match, so "I can't eat and I'm losing weight" or "my stomach hurts after lunch"
stays with triage (unintended weight loss is a symptom, not a coaching request).
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain|hurts?|ache|aching|dizz\w*|fever|bleed\w*|swell\w*|swollen|vomit\w*|nause\w*|sick|"
    r"can'?t eat|cannot eat|without trying|not trying|unexplained|diarrh\w*|choking)\b)"
)

register(
    "nutrition_scan",
    description="scan or photograph a meal to add it to their food log",
    pattern=_NOT_A_SYMPTOM + r".*\b(scan|photo(graph)?|picture|snap)\b.{0,20}\b(my |a |this )?(food|meal|plate|lunch|dinner|breakfast|snack)\b",
    to="/nutrition?scan=1",
    label="Scan my food",
    reply="Take a photo of your meal and I'll suggest what's on the plate. You check everything before it's saved.",
    priority=51,
)
register(
    "nutrition_log",
    description="log or track what they ate: a meal, a snack, sodium, or their food diary",
    pattern=_NOT_A_SYMPTOM + r".*(\b(log|track|record|add|enter)\b.{0,15}\b(my |a |the |what i )?(breakfast|lunch|dinner|meal|snack|food|ate|eaten)\b"
            r"|\bfood (diary|log|journal)\b|\bhow much (sodium|salt|sugar|fiber|protein) (did i|have i|i)\b)",
    to="/nutrition",
    label="Open my food log",
    reply="Here's your food log, with today's totals against your targets.",
    priority=52,
)
register(
    "weight_coach",
    description="wanting to lose weight, set a weight goal, or log their weight",
    pattern=_NOT_A_SYMPTOM + r".*(\b(want|like|need|trying|try|hoping|plan|going)\b.{0,10}\bto lose (some |a little )?weight\b"
            r"|\bhelp me lose (some )?weight\b|\bweight[- ]loss (goal|plan|coach\w*)\b|\bweight (goal|coach\w*)\b"
            r"|\b(log|record|track)\b.{0,10}\bmy weight\b)",
    to="/weight",
    label="Open the weight coach",
    reply="The weight coach helps you set a safe, steady goal and see your trend. It starts with a few quick questions.",
    priority=53,
)
