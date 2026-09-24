"""Platform demo data: demo-switcher labels and the organization admin."""

from __future__ import annotations

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import ORG, U_ADMIN, U_MAYA, U_OKAFOR


def run(conn, ctx: SeedContext) -> None:
    conn.execute("UPDATE users SET demo_label = 'Patient', demo_order = 10 WHERE id = %s", (U_MAYA,))
    conn.execute("UPDATE users SET demo_label = 'Cardiology', demo_order = 20 WHERE id = %s", (U_OKAFOR,))
    conn.execute(
        """
        INSERT INTO users (id, role, display_name, email, organization_id, demo_label, demo_order)
        VALUES (%s, 'admin', 'Northside Operations', 'ops@northside.example', %s, 'Hospital admin', 30)
        ON CONFLICT (id) DO NOTHING
        """,
        (U_ADMIN, ORG),
    )
