"""Front-door routing for bills, costs and insurance coverage."""

from bioverse.agents.intents import register

# Symptom language never routes here: the lookahead leaves "my insurance won't cover my chest pain"
# style messages to triage, which runs the red-flag screen and intake.
_NOT_A_SYMPTOM = r"^(?!.*\b(pain|hurts?|ache|bleed|dizz|faint|breath|chest|fever|rash|vomit|swell)).*"

register(
    "billing",
    description="bills, invoices, what something costs, copays, deductibles, insurance coverage or claims",
    pattern=_NOT_A_SYMPTOM + (
        r"\b(my bills?\b|a bill\b|the bill\b|billing|invoices?|copays?|co-pays?|deductible"
        r"|insurance|coverage|covered\b|claims?\b|out[- ]of[- ]pocket|payment plan|financial assistance"
        r"|pay (my|a|the|this)\b|how much (does|do|will|would|is|did|am i|do i)\b.{0,40}\b(cost|pay|owe|charge)"
        r"|what (does|will|would) .{0,40}\bcost|cost of\b|price of\b|estimate\b)"
    ),
    to="/billing",
    label="Open bills and coverage",
    reply="Here are your bills, coverage and cost estimates.",
    priority=60,
)
