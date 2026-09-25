"""Which Bioverse user a verified sign-in belongs to.

1. A previously linked identity (provider + subject) signs straight in.
2. Otherwise a *trusted* email (verified by the provider, in an allowed domain) that matches exactly one
   Bioverse user links the identity to that user on first sign-in.
3. Otherwise, an email listed in BIOVERSE_BOOTSTRAP_ADMINS creates an administrator, so the first person
   can set everyone else up. Nobody else is created automatically: clinical roles are granted in Bioverse.
"""

from __future__ import annotations

import os

from psycopg import Connection

from bioverse.sso.oidc import VerifiedIdentity
from bioverse.sso.providers import Provider, SSOError


def _bootstrap_admins() -> set[str]:
    return {x.strip().lower() for x in os.getenv("BIOVERSE_BOOTSTRAP_ADMINS", "").split(",") if x.strip()}


def resolve_user(conn: Connection, p: Provider, ident: VerifiedIdentity) -> tuple[str, str]:
    """(user_id, how) where how is linked | matched_email | bootstrap_admin. Raises SSOError otherwise."""
    if p.allowed_domains:
        domain = (ident.email or "").rsplit("@", 1)[-1]
        if domain not in p.allowed_domains:
            raise SSOError("domain_not_allowed", f"{ident.email} not in {p.allowed_domains}")

    row = conn.execute(
        """
        SELECT i.user_id::text, u.disabled FROM user_identities i JOIN users u ON u.id = i.user_id
        WHERE i.provider = %s AND i.subject = %s
        """,
        (p.key, ident.subject),
    ).fetchone()
    if row:
        if row["disabled"]:
            raise SSOError("account_disabled", row["user_id"])
        conn.execute(
            "UPDATE user_identities SET last_login_at = now(), email = %s WHERE provider = %s AND subject = %s",
            (ident.email, p.key, ident.subject),
        )
        return row["user_id"], "linked"

    if not ident.email or not ident.email_verified:
        raise SSOError("email_unverified", f"{p.key} did not vouch for {ident.email!r}")

    users = conn.execute("SELECT id::text, disabled FROM users WHERE lower(email) = %s", (ident.email,)).fetchall()
    if len(users) == 1:
        if users[0]["disabled"]:
            raise SSOError("account_disabled", users[0]["id"])
        user_id, how = users[0]["id"], "matched_email"
    elif not users and ident.email in _bootstrap_admins():
        org = conn.execute("SELECT id FROM organizations ORDER BY created_at LIMIT 1").fetchone()
        user_id = conn.execute(
            """
            INSERT INTO users (role, display_name, email, organization_id) VALUES ('admin', %s, %s, %s)
            RETURNING id::text
            """,
            (ident.name or ident.email.split("@")[0], ident.email, org["id"] if org else None),
        ).fetchone()["id"]
        how = "bootstrap_admin"
    else:
        raise SSOError("not_registered", ident.email)

    conn.execute(
        """
        INSERT INTO user_identities (user_id, provider, subject, tenant, email, last_login_at)
        VALUES (%s, %s, %s, %s, %s, now())
        """,
        (user_id, p.key, ident.subject, ident.tenant, ident.email),
    )
    return user_id, how
