"""Front-door routing to secure messages ("message my doctor", "my messages")."""

from bioverse.agents.intents import register

register(
    "messages",
    description="to send a message to their doctor or care team, or read their messages and replies",
    pattern=(
        r"\b(message (?:my|the) (?:doctor|care team|nurse|clinic)|send (?:a )?message|my messages|"
        r"contact my (?:doctor|care team)|write to (?:my|the) (?:doctor|care team)|reply from (?:my|the) doctor)"
    ),
    to="/messages",
    label="Open my messages",
    reply="You can message your care team securely. Replies and check-ins appear in your messages.",
    priority=60,
)
