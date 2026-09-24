"""Daily: warn administrators (and the clinician) 60, 30 and 7 days before a license expires, and mark
licenses expired once their date has passed.

The directory and consult gate read expiry dates directly, so an expired license stops a clinician from
taking consults even before this job marks it. This job keeps the records and the admin queue honest.
"""

from __future__ import annotations

from bioverse import audit
from bioverse.config import clinic_tz
from bioverse.jobs import job
from bioverse.notify import notify
from bioverse.routers.credentialing import EXPIRY_NOTICE_DAYS


def _admins(conn, org_id: str) -> list[str]:
    return [r["id"] for r in conn.execute(
        "SELECT id::text FROM users WHERE role = 'admin' AND organization_id = %s", (org_id,)
    ).fetchall()]


@job("credential_expiry", every_minutes=24 * 60, description="Warn before clinician licenses expire; mark expired ones")
def run(conn, now):
    today = now.astimezone(clinic_tz()).date()
    rows = conn.execute(
        """
        SELECT c.id::text, c.practitioner_id::text, c.expires_on, c.license_type, c.jurisdiction,
               pr.name, pr.user_id::text AS clinician_user_id, pr.organization_id::text AS org
        FROM practitioner_credentials c JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.status = 'verified' AND c.expires_on <= %s::date + %s
        FOR UPDATE OF c
        """,
        (today, max(EXPIRY_NOTICE_DAYS)),
    ).fetchall()
    warned = expired = 0
    for r in rows:
        days_left = (r["expires_on"] - today).days
        label = f"{r['license_type']} license ({r['jurisdiction']})"
        if days_left < 0:
            conn.execute(
                "UPDATE practitioner_credentials SET status = 'expired', updated_at = now() WHERE id = %s", (r["id"],)
            )
            audit.record(conn, action="credential_expired", entity_type="practitioner_credential", entity_id=r["id"],
                         agent="job/credential_expiry",
                         detail={"practitioner_id": r["practitioner_id"], "expires_on": r["expires_on"]})
            for uid in _admins(conn, r["org"]):
                notify(conn, user_id=uid, kind="credential", title=f"License expired: {r['name']}",
                       body=f"{label} expired {r['expires_on']:%d %b %Y}. They no longer appear in the online directory.",
                       link="/admin/credentials", priority="high", dedupe_key=f"credential:{r['id']}:expired")
            if r["clinician_user_id"]:
                notify(conn, user_id=r["clinician_user_id"], kind="credential", title="Your license has expired",
                       body="You can't take online consults until a current license is verified.",
                       link="/clinician/consults", priority="high", dedupe_key=f"credential:{r['id']}:expired")
            expired += 1
            continue
        # Only the nearest threshold: a license first seen 5 days out gets the 7-day notice, not all three.
        threshold = min(t for t in EXPIRY_NOTICE_DAYS if days_left <= t)
        key = f"credential:{r['id']}:{r['expires_on']}:{threshold}d"
        when = "today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
        sent = False
        for uid in _admins(conn, r["org"]):
            sent = bool(notify(conn, user_id=uid, kind="credential", title=f"License expiring: {r['name']}",
                               body=f"{label} expires {when} ({r['expires_on']:%d %b %Y}).",
                               link="/admin/credentials", priority="high" if threshold <= 7 else "normal",
                               dedupe_key=key)) or sent
        if r["clinician_user_id"]:
            notify(conn, user_id=r["clinician_user_id"], kind="credential", title="Your license expires soon",
                   body=f"Your {label} expires {when}. Submit the renewal so you can keep taking online consults.",
                   link="/clinician/consults", dedupe_key=key)
        warned += int(sent)
    return {"warned": warned, "expired": expired}
