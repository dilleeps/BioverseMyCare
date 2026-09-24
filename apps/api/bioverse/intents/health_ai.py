"""Front-door routing to the Personal Health AI (factual questions about the patient's own record).

Priority 40: after the core intents, so "what happened with my health this year" stays with My Health Story.
"""

from bioverse.agents.intents import register

register(
    "health_ai",
    description="a factual question about their own record, e.g. 'when was my last flu shot' or "
                "'how many times did I see cardiology'",
    pattern=r"\b(when was my last|what was my last|how many times|remind me what|ask about my record)\b",
    to="/health-ai",
    label="Ask about my record",
    reply="I can look that up in your record and show you exactly where the answer comes from.",
    priority=40,
)
