"""Server-side sessions behind an opaque cookie. Only the SHA-256 of the cookie value is stored."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from psycopg import Connection

SESSION_COOKIE = "bv_session"
STATE_COOKIE = "bv_oidc_state"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def idle_minutes() -> int:
    return int(os.getenv("BIOVERSE_SESSION_IDLE_MINUTES", "60"))


def max_hours() -> int:
    return int(os.getenv("BIOVERSE_SESSION_MAX_HOURS", "12"))


def cookie_secure() -> bool:
    return not os.getenv("BIOVERSE_PUBLIC_URL", "https://").startswith("http://")


def create(conn: Connection, *, user_id: str, provider: str, id_token: str | None, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO auth_sessions (token_hash, user_id, provider, id_token_hint, expires_at, user_agent)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (_hash(token), user_id, provider, id_token,
         datetime.now(timezone.utc) + timedelta(hours=max_hours()), (user_agent or "")[:300]),
    )
    return token


def resolve(conn: Connection, token: str) -> dict | None:
    """The live session for a cookie value, refreshing its idle timer; None when absent, expired or revoked."""
    row = conn.execute(
        """
        UPDATE auth_sessions s SET last_seen_at = now()
        FROM users u
        WHERE s.token_hash = %s AND u.id = s.user_id AND NOT u.disabled
          AND s.revoked_at IS NULL AND s.expires_at > now()
          AND s.last_seen_at > now() - make_interval(mins => %s)
        RETURNING s.id::text, s.user_id::text, s.provider
        """,
        (_hash(token), idle_minutes()),
    ).fetchone()
    return row


def revoke(conn: Connection, token: str) -> dict | None:
    return conn.execute(
        """
        UPDATE auth_sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL
        RETURNING user_id::text, provider, id_token_hint
        """,
        (_hash(token),),
    ).fetchone()


def revoke_all(conn: Connection, user_id: str) -> int:
    cur = conn.execute("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                       (user_id,))
    return cur.rowcount
