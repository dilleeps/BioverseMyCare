"""Front-door routing to challenges and rewards."""

from bioverse.agents.intents import register

register(
    "challenges",
    description="join or check a health challenge, or see their points, badges and rewards",
    pattern=r"(\b(join|start|find|see|show|do)\b.{0,15}\bchallenges?\b|\b(step|steps|walking|hydration|water|veg\w*|family) challenges?\b"
            r"|\bmy (points|badges|rewards)\b|\bredeem\b)",
    to="/challenges",
    label="Open challenges",
    reply="Here are the challenges you can join, your progress, points and rewards. Joining is always your choice.",
    priority=50,
)
