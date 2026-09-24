"""Front-door routing to the health misinformation checker.

Specific phrases only, so a symptom message ("is this rash serious?") is never taken for a fact check.
"""

from bioverse.agents.intents import register

register(
    "factcheck",
    description="checking whether a health claim they read or were sent is true, e.g. 'is this true?' about a "
                "forwarded message, or 'fact check this post'",
    pattern=r"\b(fact[- ]?check|is (?:this|that|it) (?:claim |message |post |article )?(?:true|real|legit|a myth)\b|"
            r"is this (?:health )?(?:misinformation|fake news)|(?:someone|somebody|a friend) (?:sent|forwarded) me)",
    to="/factcheck",
    label="Check a health claim",
    reply="Paste the message or post and I'll check each health claim against published evidence.",
    priority=58,
)
