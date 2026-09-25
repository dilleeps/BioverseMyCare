"""Health check, demo identities, and the signed-in user."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from psycopg import Connection

from bioverse.agents import llm, medgemma
from bioverse.auth import CurrentUser
from bioverse.config import get_settings
from bioverse.db import DbConn
from bioverse.safety.red_flags import RULESET_VERSION
from bioverse.sso.providers import demo_allowed

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/health")
def health(conn: DbConn) -> dict:
    conn.execute("SELECT 1").fetchone()
    settings = get_settings()
    return {
        "status": "ok",
        "database": "ok",
        "ai": llm.active_provider() or "rules",
        "providers": llm.providers() if llm.ai_enabled() else [],
        "model": (medgemma.model_label() if llm.active_provider() == "medgemma"
                  else settings.ai_model if llm.active_provider() == "claude" else None),
        "red_flag_ruleset": RULESET_VERSION,
    }


@router.get("/session/demo-users")
def demo_users(conn: DbConn) -> list[dict]:
    """The identities the demo lets you switch between. Empty when demo sign-in is off."""
    if not demo_allowed():
        return []
    return conn.execute(
        """
        SELECT u.id::text, u.role, u.team, u.display_name, u.demo_label AS subtitle
        FROM users u
        WHERE u.demo_label IS NOT NULL
        ORDER BY u.demo_order, u.display_name
        """
    ).fetchall()


@router.get("/me")
def me(user: CurrentUser, request: Request) -> dict:
    return {
        "auth": getattr(request.state, "auth", None),
        "id": user.id,
        "role": user.role,
        "display_name": user.display_name,
        "patient_id": user.patient_id,
        "practitioner_id": user.practitioner_id,
        "team": user.team,
    }
