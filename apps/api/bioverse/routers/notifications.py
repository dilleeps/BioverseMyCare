"""Notification center for every role, delivery preferences, and the admin view of scheduled jobs."""

from __future__ import annotations

import re
from datetime import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from psycopg.types.json import Jsonb

from bioverse import audit, jobs
from bioverse.auth import Admin, CurrentUser
from bioverse.db import DbConn

inbox_router = APIRouter(prefix="/api/notifications", tags=["notifications"])
admin_router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])

CHANNELS = ("in_app", "email", "sms", "push")


@inbox_router.get("")
def inbox(conn: DbConn, user: CurrentUser, unread: bool = False, limit: int = 50) -> dict:
    limit = max(1, min(limit, 200))
    items = conn.execute(
        f"""
        SELECT id::text, kind, title, body, link, priority, due_at, read_at
        FROM notifications
        WHERE user_id = %s AND status <> 'cancelled' AND due_at <= now()
          {"AND read_at IS NULL" if unread else ""}
        ORDER BY due_at DESC
        LIMIT %s
        """,
        (user.id, limit),
    ).fetchall()
    count = conn.execute(
        """
        SELECT count(*) AS n FROM notifications
        WHERE user_id = %s AND status <> 'cancelled' AND due_at <= now() AND read_at IS NULL
        """,
        (user.id,),
    ).fetchone()["n"]
    upcoming = conn.execute(
        """
        SELECT count(*) AS n FROM notifications
        WHERE user_id = %s AND status = 'pending' AND due_at > now()
        """,
        (user.id,),
    ).fetchone()["n"]
    return {"items": items, "unread": count, "upcoming": upcoming}


@inbox_router.post("/{notification_id}/read")
def mark_read(notification_id: str, conn: DbConn, user: CurrentUser) -> dict:
    row = conn.execute(
        """
        UPDATE notifications SET read_at = coalesce(read_at, now())
        WHERE id::text = %s AND user_id = %s RETURNING id::text, read_at
        """,
        (notification_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Notification not found")
    return row


@inbox_router.post("/read-all")
def mark_all_read(conn: DbConn, user: CurrentUser) -> dict:
    cur = conn.execute(
        "UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL AND due_at <= now()",
        (user.id,),
    )
    return {"marked": cur.rowcount}


class Preferences(BaseModel):
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    channels: dict[str, list[str]] = {}
    quiet_start: time | None = None
    quiet_end: time | None = None
    timezone: str = "America/New_York"

    @field_validator("phone")
    @classmethod
    def e164(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        v = re.sub(r"[\s().-]", "", v)
        if not re.fullmatch(r"\+[1-9]\d{6,14}", v):
            raise ValueError("Use international format, for example +15555550123")
        return v

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("That doesn't look like an email address")
        return v

    @field_validator("channels")
    @classmethod
    def known_channels(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for kind, chans in v.items():
            bad = [c for c in chans if c not in CHANNELS]
            if bad:
                raise ValueError(f"Unknown channel for {kind}: {', '.join(bad)}")
        return v


@inbox_router.get("/preferences")
def get_preferences(conn: DbConn, user: CurrentUser) -> dict:
    row = conn.execute(
        """
        SELECT email, phone, channels, quiet_start, quiet_end, timezone
        FROM notification_preferences WHERE user_id = %s
        """,
        (user.id,),
    ).fetchone()
    kinds = conn.execute(
        "SELECT DISTINCT kind FROM notifications WHERE user_id = %s ORDER BY kind", (user.id,)
    ).fetchall()
    prefs = row or Preferences().model_dump()
    return {**prefs, "known_kinds": [k["kind"] for k in kinds], "channels_available": list(CHANNELS)}


@inbox_router.put("/preferences")
def put_preferences(body: Preferences, conn: DbConn, user: CurrentUser) -> dict:
    conn.execute(
        """
        INSERT INTO notification_preferences (user_id, email, phone, channels, quiet_start, quiet_end, timezone)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET email = excluded.email, phone = excluded.phone,
            channels = excluded.channels, quiet_start = excluded.quiet_start, quiet_end = excluded.quiet_end,
            timezone = excluded.timezone, updated_at = now()
        """,
        (user.id, body.email, body.phone, Jsonb(body.channels), body.quiet_start, body.quiet_end, body.timezone),
    )
    audit.record(conn, action="notification_preferences.update", entity_type="user", entity_id=user.id,
                 actor=user, patient_id=user.patient_id)
    return get_preferences(conn, user)


@admin_router.get("")
def list_jobs(conn: DbConn, _: Admin) -> dict:
    registry = jobs.load_all()
    last = jobs.last_runs(conn)
    history = conn.execute(
        "SELECT id, name, started_at, finished_at, status, detail FROM job_runs ORDER BY started_at DESC LIMIT 30"
    ).fetchall()
    return {
        "jobs": [
            {"name": j.name, "description": j.description, "every_minutes": j.every_minutes,
             "last_run": last.get(j.name)}
            for j in sorted(registry.values(), key=lambda j: j.name)
        ],
        "history": history,
    }


@admin_router.post("/run")
def run_due_jobs(conn: DbConn, user: Admin, force: bool = False) -> dict:
    results = jobs.run_due(conn, force=force)
    audit.record(conn, action="jobs.run_due", entity_type="job", actor=user,
                 detail={"ran": [r["name"] for r in results], "force": force})
    return {"results": results}


@admin_router.post("/{name}/run")
def run_one(name: str, conn: DbConn, user: Admin) -> dict:
    if name not in jobs.load_all():
        raise HTTPException(404, "Unknown job")
    result = jobs.run_job(conn, name)
    audit.record(conn, action="jobs.run", entity_type="job", entity_id=None, actor=user, detail={"name": name})
    return result


router = APIRouter()
router.include_router(inbox_router)
router.include_router(admin_router)
