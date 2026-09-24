"""Notification demo data: a welcome message in every demo user's inbox."""

from __future__ import annotations

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import U_ADMIN, U_MAYA, U_OKAFOR
from bioverse.notify import notify

WELCOME = {
    U_MAYA: ("Welcome to Bioverse One", "Reminders, results and messages from your care team appear here.", "/app"),
    U_OKAFOR: ("Welcome to Bioverse One", "Alerts about your patients and items waiting for review appear here.",
               "/clinician"),
    U_ADMIN: ("Welcome to Bioverse One", "Scheduled jobs and delivery status are under Operations.", "/ops/jobs"),
}


def run(conn, ctx: SeedContext) -> None:
    for user_id, (title, body, link) in WELCOME.items():
        notify(conn, user_id=user_id, kind="welcome", title=title, body=body, link=link,
               due_at=ctx.at(ctx.days(-1), 9, 0), dedupe_key="welcome")
