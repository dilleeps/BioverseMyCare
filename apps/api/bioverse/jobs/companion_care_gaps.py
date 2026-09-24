"""Care-gap nudges, weekly: a gentle reminder about preventive care that is due, at most once per gap per 30 days
and at most one nudge per patient per run, so nobody gets a pile of them at once.

Gaps come from the preventive-care rules in `bioverse/prevention.py`, evaluated on the patient's record for
the patient's own date. The notification says only whether a screening or a vaccine may be due; which one,
and why, is on the wellness page behind the link.
"""

from __future__ import annotations

from datetime import timedelta

from bioverse import audit, companion, prevention
from bioverse.jobs import job
from bioverse.notify import notify

REPEAT_AFTER = timedelta(days=30)        # per gap
WEEK = timedelta(days=6, hours=12)        # per patient: one nudge a week (a little slack for job timing)


@job("companion_care_gaps", every_minutes=7 * 24 * 60, description="Weekly nudge about preventive care that is due")
def run(conn, now):
    patients = conn.execute(
        "SELECT id::text, user_id::text FROM patients WHERE user_id IS NOT NULL ORDER BY id"
    ).fetchall()
    settings = companion.settings_for(conn, [p["id"] for p in patients])
    created, considered = 0, 0
    for p in patients:
        if not settings[p["id"]]["care_gap_nudges"]:
            continue
        this_week = conn.execute(
            "SELECT 1 FROM notifications WHERE user_id = %s AND dedupe_key LIKE 'gap:%%' AND due_at > %s LIMIT 1",
            (p["user_id"], now - WEEK),
        ).fetchone()
        if this_week:
            continue
        tz = companion.patient_tz(conn, p["id"])
        today = now.astimezone(tz).date()
        # evaluate() orders overdue before due; each run nudges about the first gap not nudged recently.
        items = [i for i in prevention.evaluate(prevention.load_record(conn, p["id"]), today)["items"]
                 if i["status"] in ("due", "overdue")]
        considered += len(items)
        for item in items:
            prefix = f"gap:{item['rule_id']}:"
            recent = conn.execute(
                """
                SELECT 1 FROM notifications WHERE user_id = %s AND dedupe_key LIKE %s AND due_at > %s LIMIT 1
                """,
                (p["user_id"], prefix + "%", now - REPEAT_AFTER),
            ).fetchone()
            if recent:
                continue
            what = "A vaccine" if item["kind"] == "vaccine" else "A health check"
            row = notify(conn, user_id=p["user_id"], patient_id=p["id"], kind="care_gap_nudge",
                         title=f"{what} may be due",
                         body="A gentle reminder from Bioverse One. See what's due and book when it suits you.",
                         link="/wellness", priority="low", due_at=now, dedupe_key=f"{prefix}{today.isoformat()}")
            if row is not None:
                created += 1
                audit.record(conn, action="care_gap_nudged", entity_type="care_gap", agent="companion/jobs",
                             patient_id=p["id"], detail={"rule_id": item["rule_id"], "ruleset": prevention.RULESET_VERSION})
            break   # one gentle nudge per patient per week
    return {"created": created, "due_items": considered}
