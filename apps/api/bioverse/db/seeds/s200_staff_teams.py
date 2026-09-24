"""Staff teams: the front desk and the pharmacy see their own screens and alerts."""

from __future__ import annotations

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import U_FRONTDESK


def run(conn, ctx: SeedContext) -> None:
    conn.execute("UPDATE users SET team = 'front_desk' WHERE id = %s AND team IS NULL", (U_FRONTDESK,))
    conn.execute(
        "UPDATE users SET team = 'pharmacy' WHERE team IS NULL AND id IN (SELECT user_id FROM pharmacy_staff)"
    )
