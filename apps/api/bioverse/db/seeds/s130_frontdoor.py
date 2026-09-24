"""Front-door access demo data: Rana Haddad reads Bioverse One in senior mode with slightly larger text,
and appears in the demo identity switcher so the senior front door is one click away.

Idempotent: a person who has since changed their own settings keeps them.
"""

from __future__ import annotations

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import U_HADDAD


def run(conn, ctx: SeedContext) -> None:
    conn.execute(
        """
        INSERT INTO ui_preferences (user_id, senior_mode, text_scale, high_contrast, reduce_motion, read_aloud)
        VALUES (%s, true, 1.20, false, false, false)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (U_HADDAD,),
    )
    # Show her in the demo identity switcher, unless another module already labelled her.
    conn.execute(
        "UPDATE users SET demo_label = 'Patient, senior mode', demo_order = 12 WHERE id = %s AND demo_label IS NULL",
        (U_HADDAD,),
    )
