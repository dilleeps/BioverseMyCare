"""Front-door routing to the Privacy Center (Trust and Safety)."""

from bioverse.agents.intents import register

register(
    "privacy",
    description="their privacy, consents, AI opt-out, or who has accessed their record",
    pattern=(
        r"\b(privacy|my consents?|opt (?:me )?out of ai|ai processing|"
        r"who (?:has |have )?(?:accessed|looked at|viewed|seen) my (?:record|records|data|chart)|"
        r"access log|download my data)"
    ),
    to="/privacy",
    label="Open my privacy center",
    reply="Your privacy center shows what you've agreed to, lets you change it, and lists who has opened your record.",
    priority=60,
)
