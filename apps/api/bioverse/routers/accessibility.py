"""Display and accessibility preferences: senior mode, text size, contrast, motion and read-aloud.

Every signed-in person has their own row (patients, caregivers, clinicians, staff, admins). The web app
caches the preferences locally for the first paint and syncs them here, so they follow the person
across devices.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from bioverse import audit
from bioverse.auth import CurrentUser
from bioverse.db import DbConn

router = APIRouter(prefix="/api/accessibility", tags=["accessibility"])

MIN_SCALE, MAX_SCALE = 1.0, 1.6
DEFAULTS = {"senior_mode": False, "text_scale": 1.0, "high_contrast": False, "reduce_motion": False,
            "read_aloud": False}
FIELDS = tuple(DEFAULTS)


def _out(row: dict | None) -> dict:
    if row is None:
        return {**DEFAULTS, "updated_at": None, "saved": False}
    out = {k: row[k] for k in FIELDS}
    out["text_scale"] = float(out["text_scale"])
    return {**out, "updated_at": row["updated_at"], "saved": True}


def get_preferences(conn: Connection, user_id: str) -> dict:
    row = conn.execute(
        f"SELECT {', '.join(FIELDS)}, updated_at FROM ui_preferences WHERE user_id = %s", (user_id,)
    ).fetchone()
    return _out(row)


@router.get("/preferences")
def read_preferences(conn: DbConn, user: CurrentUser) -> dict:
    return get_preferences(conn, user.id)


class PreferencesIn(BaseModel):
    """Every field is optional: send only what changed."""

    model_config = ConfigDict(extra="forbid")
    senior_mode: StrictBool | None = None
    text_scale: float | None = Field(default=None, ge=MIN_SCALE, le=MAX_SCALE)
    high_contrast: StrictBool | None = None
    reduce_motion: StrictBool | None = None
    read_aloud: StrictBool | None = None


@router.put("/preferences")
def save_preferences(body: PreferencesIn, conn: DbConn, user: CurrentUser) -> dict:
    current = get_preferences(conn, user.id)
    changes = body.model_dump(exclude_none=True)
    merged = {k: changes.get(k, current[k]) for k in FIELDS}
    merged["text_scale"] = Decimal(str(round(merged["text_scale"], 2)))
    conn.execute(
        """
        INSERT INTO ui_preferences (user_id, senior_mode, text_scale, high_contrast, reduce_motion, read_aloud)
        VALUES (%(u)s, %(senior_mode)s, %(text_scale)s, %(high_contrast)s, %(reduce_motion)s, %(read_aloud)s)
        ON CONFLICT (user_id) DO UPDATE SET
            senior_mode = EXCLUDED.senior_mode, text_scale = EXCLUDED.text_scale,
            high_contrast = EXCLUDED.high_contrast, reduce_motion = EXCLUDED.reduce_motion,
            read_aloud = EXCLUDED.read_aloud, updated_at = now()
        """,
        {"u": user.id, **merged},
    )
    audit.record(conn, action="ui_preferences_updated", entity_type="ui_preferences", entity_id=user.id, actor=user,
                 patient_id=user.patient_id, detail={"changed": sorted(changes)})
    return get_preferences(conn, user.id)
