"""Collect 835 remittances from connected payers and post them to billing.

With the simulated clearinghouse this is where claims get "paid": it adjudicates every accepted claim
and returns an 835 (clearly labelled simulation). Idempotent: an 835 already posted (same payer and trace
number) is skipped, and the simulator only remits a claim once.
"""

from __future__ import annotations

from bioverse.jobs import job
from bioverse.payers import services as svc


@job("insurance_remits", every_minutes=15, description="Collect insurance remittances (835) and post payments")
def run(conn, now):
    result = svc.fetch_remittances(conn)
    return {"remittances": result["remittances"], "claims_posted": result["claims_posted"],
            "errors": result["errors"][:5]}
