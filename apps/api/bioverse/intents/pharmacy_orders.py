"""Front-door routing to online ordering: "order my medicine", "deliver my prescription", "buy allergy medicine".

Tried before the pharmacy intent (62), whose symptom veto includes "allerg" and would send "buy allergy medicine"
to triage. Symptom and side-effect language still vetoes this match, so "I need medicine, my chest hurts" stays with
triage and its red-flag screen.
"""

from bioverse.agents.intents import register

_NOT_A_SYMPTOM = (
    r"^(?!.*\b(pain\b|hurts?|ache|aching|bleed|dizz|faint|breath|chest|fever|rash|vomit|swell|swollen|"
    r"side effects?|reaction|overdose|can'?t (breathe|swallow))).*"
)
_WHAT = (r"(medicines?|medications?|meds|pills|tablets|prescriptions?|vitamins?|allergy|cold|flu|antacids?"
         r"|thermometer|blood pressure (cuff|monitor)|first aid|otc|over[- ]the[- ]counter)")

register(
    "pharmacy_orders",
    description="ordering medicines or health products online, home delivery of a prescription, or tracking a "
                "medicine delivery, e.g. 'order my medicine', 'deliver my prescription', 'buy allergy medicine'",
    # The alternatives are grouped so the symptom veto applies to every one of them.
    pattern=_NOT_A_SYMPTOM + r"(?:" + (
        r"\b(order|buy|purchase|shop for)\b.{0,40}\b" + _WHAT
        + r"|\b(deliver|delivered|delivery|home delivery)\b.{0,40}\b" + _WHAT
        + r"|\b" + _WHAT + r"\b.{0,30}\b(delivered|delivery)\b"
        + r"|\b(track|where is|where's) my (medicine |pharmacy |prescription )?(order|delivery)\b"
    ) + r")",
    to="/shop",
    label="Order medicines",
    reply="You can order medicines for home delivery or pickup at the clinic pharmacy. A pharmacist checks anything "
          "that needs it.",
    priority=58,
)
