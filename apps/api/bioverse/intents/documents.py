"""Front-door routing to /records: upload a lab report, or download a copy of the record.

Priority 60, after the core `results` intent (20): a message about reading a result still goes to
/results. This one catches uploading, scanning, adding results from elsewhere, and downloading.
"""

from bioverse.agents.intents import register

register(
    "documents",
    description="uploading or scanning a lab report from another lab, adding a result themselves, "
                "or downloading a copy of their health record",
    pattern=r"\b(upload(?:ing)?\b|scan my\b|my lab report from\b|add (?:a|my) (?:lab )?results?\b|"
            r"download (?:a copy of )?my (?:health )?records?\b|(?:copy|export) of my (?:health )?records?\b)",
    to="/records",
    label="Open my records",
    reply="You can upload a lab report for your care team to review, or download a copy of your record.",
    priority=60,
)
