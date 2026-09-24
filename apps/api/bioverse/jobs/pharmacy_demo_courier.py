"""SIMULATION: a demo courier that completes deliveries once their ETA has passed.

There is no real courier. Every five minutes this marks orders that are out for delivery, and whose ETA is in the
past, as delivered, with proof recorded as simulated. Cold-chain orders are recorded as handed to the recipient
named on the address, never left at the door. Set BIOVERSE_DEMO_COURIER=off to turn the simulation off, so only a
pharmacist marks orders delivered.
"""

from __future__ import annotations

import os

from bioverse.jobs import job

SIMULATION_LABEL = "Demo courier (simulation)"


def enabled() -> bool:
    return os.getenv("BIOVERSE_DEMO_COURIER", "on").strip().lower() not in ("off", "0", "false", "no")


@job("pharmacy_demo_courier", every_minutes=5,
     description="Simulation: the demo courier marks out-for-delivery pharmacy orders delivered after their ETA")
def run(conn, now):
    if not enabled():
        return {"skipped": "disabled by BIOVERSE_DEMO_COURIER=off"}
    from bioverse.routers.pharmacy_orders import ORDER_COLS, transition

    due = conn.execute(
        f"""
        SELECT {ORDER_COLS} FROM pharmacy_orders o
        WHERE o.status = 'out_for_delivery' AND o.eta IS NOT NULL AND o.eta <= %s
        ORDER BY o.eta
        LIMIT 200
        FOR UPDATE OF o SKIP LOCKED
        """,
        (now,),
    ).fetchall()
    for order in due:
        if order["cold_chain"]:
            proof = {"type": "recipient", "recipient_name": (order["address"] or {}).get("recipient_name"),
                     "at": now.isoformat(), "simulated": True, "by": SIMULATION_LABEL}
        else:
            proof = {"type": "left_at_door", "at": now.isoformat(), "simulated": True, "by": SIMULATION_LABEL}
        transition(conn, order, "delivered", actor=None, agent="demo-courier", note="Simulated delivery",
                   sets={"delivery_proof": proof, "completed_at": now}, now=now)
    return {"delivered": len(due), "simulation": True}
