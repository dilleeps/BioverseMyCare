"""Front-door routing to public specialist AI assistants (general education in a clinician's voice)."""

from bioverse.agents.intents import register

register(
    "specialists",
    description="a general question for a specialist's public AI assistant, e.g. 'ask a cardiologist AI'",
    pattern=r"\b(ask (?:a|the) (?:cardiologist|neurologist|specialist|doctor)(?:'s)? (?:ai|assistant|bot)|"
            r"(?:specialist|cardiologist|neurologist) (?:ai|assistant|bot)s?\b|digital doubles?)",
    to="/specialists",
    label="Browse specialist AI assistants",
    reply="Specialists' AI assistants answer general health questions from their approved guidance. They can't "
          "advise on your own situation.",
    priority=59,
)
