"""Health check, demo identities, and the signed-in user."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import Connection

from bioverse.agents import llm
from bioverse.auth import CurrentUser
from bioverse.config import get_settings
from bioverse.db import DbConn
from bioverse.safety.red_flags import RULESET_VERSION

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/health")
def health(conn: DbConn) -> dict:
    conn.execute("SELECT 1").fetchone()
    settings = get_settings()
    return {
        "status": "ok",
        "database": "ok",
        "ai": "claude" if llm.ai_enabled() else "rules",
        "model": settings.ai_model if llm.ai_enabled() else None,
        "red_flag_ruleset": RULESET_VERSION,
    }


@router.get("/session/demo-users")
def demo_users(conn: DbConn) -> list[dict]:
    """The identities the demo lets you switch between. Remove with real authentication."""
    return conn.execute(
        """
        SELECT u.id::text, u.role, u.display_name,
               coalesce(pr.specialty, CASE WHEN u.role = 'patient' THEN 'Patient' END) AS subtitle
        FROM users u
        LEFT JOIN practitioners pr ON pr.user_id = u.id
        WHERE u.email IN ('maya@example.com', 'a.okafor@northside.example')
        ORDER BY u.role DESC
        """
    ).fetchall()


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {
        "id": user.id,
        "role": user.role,
        "display_name": user.display_name,
        "patient_id": user.patient_id,
        "practitioner_id": user.practitioner_id,
    }
