"""My availability: a clinician's weekly hours, time off and online consult profile.

Clinicians manage their own under `/api/clinician/...`. Administrators and the front desk (staff with the
front_desk team, or no team) manage any clinician in their organization under
`/api/admin/practitioners/{practitioner_id}/...`, with the same request and response shapes. A clinician in
another organization is a 404, never a 403: we don't confirm that it exists.

Saving hours or time off regenerates the clinician's free slots straight away (see bioverse/availability.py);
the `availability_slots` job keeps the horizon rolling forward. Every change is audited.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from bioverse import audit
from bioverse import availability as av
from bioverse.auth import Clinician, CurrentUser, User
from bioverse.db import DbConn
from bioverse.routers.credentialing import credential_state

router = APIRouter(prefix="/api", tags=["availability"])

Conn = DbConn

CONSULT_MODES = ("message", "video", "phone")
CONSULT_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
IN_PERSON_NOTE = ("Online consults are by message, video or phone. In-person visits are booked from the weekly "
                  "hours above, not from the consult profile.")
DIRECTORY_NOTE = ("Patients find you in the online consult directory only while you have a verified, unexpired "
                  "license on file and are accepting new patients. Licenses are verified by an administrator "
                  "under Credentialing.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------
# Who may edit whose availability
# ---------------------------------------------------------------------------------------------


def require_scheduler(user: CurrentUser) -> User:
    """Administrators, and staff on the front desk (or on no particular team)."""
    if user.role == "admin" or (user.role == "staff" and user.team in (None, "front_desk")):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators and the front desk manage clinicians' availability")


Scheduler = Annotated[User, Depends(require_scheduler)]


def _practitioner(conn: Connection, org_id: str, practitioner_id: str | None) -> dict:
    try:
        pid = str(UUID(practitioner_id or ""))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinician not found") from None
    row = conn.execute(
        """
        SELECT id::text, name, specialty, location_name, languages, (user_id IS NOT NULL) AS has_login
        FROM practitioners WHERE id = %s AND organization_id = %s
        """,
        (pid, org_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinician not found")
    return row


def _mine(conn: Connection, user: User) -> dict:
    return _practitioner(conn, user.organization_id, user.practitioner_id)


# ---------------------------------------------------------------------------------------------
# Weekly hours
# ---------------------------------------------------------------------------------------------


class WindowIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weekday: int = Field(ge=0, le=6)                       # 0 = Monday
    start: time
    end: time
    mode: Literal["in_person", "video"] = "in_person"
    location: str | None = Field(default=None, max_length=120)
    slot_minutes: int = Field(default=20, ge=av.MIN_SLOT_MINUTES, le=av.MAX_SLOT_MINUTES)
    effective_from: date | None = None
    effective_until: date | None = None


class TemplateIn(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    horizon_days: int | None = Field(default=None, ge=av.MIN_HORIZON_DAYS, le=av.MAX_HORIZON_DAYS)
    windows: list[WindowIn] = Field(max_length=av.MAX_WINDOWS)


class TimeOffIn(BaseModel):
    starts_on: date
    ends_on: date
    reason: str | None = Field(default=None, max_length=200)


def _state(conn: Connection, pr: dict) -> dict:
    now = _now()
    conf = av.settings(conn, pr["id"])
    tz = av.practitioner_tz(conn, pr["id"])
    counts = conn.execute(
        """
        SELECT count(*) FILTER (WHERE status = 'free') AS free,
               count(*) FILTER (WHERE status = 'booked') AS booked,
               count(*) FILTER (WHERE status = 'free' AND source = 'template') AS generated
        FROM slots WHERE practitioner_id = %s AND starts_at > %s
        """,
        (pr["id"], now),
    ).fetchone()
    return {
        "practitioner": {k: pr[k] for k in ("id", "name", "specialty", "location_name", "has_login")},
        "timezone": conf["timezone"],
        "timezone_is_default": conf["timezone_is_default"],
        "horizon_days": conf["horizon_days"],
        "updated_at": conf["updated_at"],
        "today": now.astimezone(tz).date(),
        "windows": [av.window_out(w) for w in av.windows(conn, pr["id"])],
        "time_off": av.time_off(conn, pr["id"], now.astimezone(tz).date()),
        "upcoming": counts,
        "limits": {"slot_minutes": [av.MIN_SLOT_MINUTES, av.MAX_SLOT_MINUTES],
                   "horizon_days": [av.MIN_HORIZON_DAYS, av.MAX_HORIZON_DAYS],
                   "max_windows": av.MAX_WINDOWS, "preview_days": av.MAX_PREVIEW_DAYS},
    }


def _save(conn: Connection, actor: User, pr: dict, body: TemplateIn) -> dict:
    try:
        rows = av.validate_windows([w.model_dump() for w in body.windows])
        conf = av.settings(conn, pr["id"])
        tz_name = body.timezone or conf["timezone"]
        av.check_timezone(tz_name)
    except av.AvailabilityError as exc:
        raise HTTPException(422, {"code": "invalid_template", "message": str(exc)}) from None
    horizon = body.horizon_days or conf["horizon_days"]
    conn.execute(
        """
        INSERT INTO availability_settings (practitioner_id, timezone, horizon_days, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (practitioner_id) DO UPDATE
        SET timezone = EXCLUDED.timezone, horizon_days = EXCLUDED.horizon_days, updated_by = EXCLUDED.updated_by,
            updated_at = now()
        """,
        (pr["id"], tz_name, horizon, actor.id),
    )
    conn.execute("DELETE FROM availability_windows WHERE practitioner_id = %s", (pr["id"],))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO availability_windows (practitioner_id, weekday, start_time, end_time, mode, location,
                                              slot_minutes, effective_from, effective_until)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(pr["id"], w["weekday"], w["start"], w["end"], w["mode"], w["location"], w["slot_minutes"],
              w["effective_from"], w["effective_until"]) for w in rows],
        )
    result = av.sync(conn, pr["id"])
    audit.record(conn, action="availability.template_saved", entity_type="practitioner", entity_id=pr["id"],
                 actor=actor, detail={"windows": len(rows), "timezone": tz_name, "horizon_days": horizon,
                                      "sync": result})
    return _state(conn, pr) | {"sync": result}


def _booked_between(conn: Connection, pr: dict, starts_on: date, ends_on: date) -> list[dict]:
    tz = av.practitioner_tz(conn, pr["id"])
    lo = datetime.combine(starts_on, time(0), tzinfo=tz)
    hi = datetime.combine(ends_on + timedelta(days=1), time(0), tzinfo=tz)
    return conn.execute(
        """
        SELECT a.id::text AS appointment_id, s.starts_at, s.mode, pt.name AS patient_name
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN patients pt ON pt.id = a.patient_id
        WHERE a.practitioner_id = %s AND a.status = 'booked' AND s.starts_at >= %s AND s.starts_at < %s
          AND s.starts_at > now()
        ORDER BY s.starts_at
        """,
        (pr["id"], lo, hi),
    ).fetchall()


def _add_time_off(conn: Connection, actor: User, pr: dict, body: TimeOffIn) -> dict:
    today = _now().astimezone(av.practitioner_tz(conn, pr["id"])).date()
    if body.ends_on < body.starts_on:
        raise HTTPException(422, "The last day off is before the first")
    if body.ends_on < today:
        raise HTTPException(422, "That time off is already over")
    if (body.ends_on - body.starts_on).days + 1 > av.MAX_TIME_OFF_DAYS:
        raise HTTPException(422, f"Time off can be at most {av.MAX_TIME_OFF_DAYS} days")
    clash = conn.execute(
        """
        SELECT starts_on, ends_on FROM availability_time_off
        WHERE practitioner_id = %s AND starts_on <= %s AND ends_on >= %s LIMIT 1
        """,
        (pr["id"], body.ends_on, body.starts_on),
    ).fetchone()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Overlaps time off already set for {clash['starts_on']:%d %b} – {clash['ends_on']:%d %b %Y}")
    row = conn.execute(
        """
        INSERT INTO availability_time_off (practitioner_id, starts_on, ends_on, reason, created_by)
        VALUES (%s, %s, %s, %s, %s) RETURNING id::text, starts_on, ends_on, reason, created_at
        """,
        (pr["id"], body.starts_on, body.ends_on, (body.reason or "").strip() or None, actor.id),
    ).fetchone()
    result = av.sync(conn, pr["id"])
    booked = _booked_between(conn, pr, body.starts_on, body.ends_on)
    audit.record(conn, action="availability.time_off_added", entity_type="practitioner", entity_id=pr["id"],
                 actor=actor, detail={"time_off_id": row["id"], "starts_on": body.starts_on, "ends_on": body.ends_on,
                                      "sync": result, "booked_kept": len(booked)})
    return {"time_off": row, "sync": result, "booked_in_range": booked}


def _remove_time_off(conn: Connection, actor: User, pr: dict, time_off_id: str) -> dict:
    try:
        tid = str(UUID(time_off_id))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Time off not found") from None
    row = conn.execute(
        "DELETE FROM availability_time_off WHERE id = %s AND practitioner_id = %s RETURNING starts_on, ends_on",
        (tid, pr["id"]),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Time off not found")
    result = av.sync(conn, pr["id"])
    audit.record(conn, action="availability.time_off_removed", entity_type="practitioner", entity_id=pr["id"],
                 actor=actor, detail={"time_off_id": tid, "starts_on": row["starts_on"], "ends_on": row["ends_on"],
                                      "sync": result})
    return {"deleted": tid, "sync": result}


# ---------------------------------------------------------------------------------------------
# Online consult profile
# ---------------------------------------------------------------------------------------------


class ConsultProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fee_cents: int | None = Field(default=None, ge=0, le=200_000)
    modes: list[Literal["message", "video", "phone"]] | None = Field(default=None, min_length=1, max_length=3)
    bio: str | None = Field(default=None, max_length=2000)
    years_in_practice: int | None = Field(default=None, ge=0, le=70)
    languages: list[str] | None = Field(default=None, min_length=1, max_length=12)
    accepting: bool | None = None
    reply_hours: int | None = Field(default=None, ge=1, le=72)
    # Weekly hours for scheduled video/phone consults, replaced as a whole: {"mon": ["09:00", "17:00"], ...}.
    hours: dict[str, list[str] | None] | None = None
    slot_minutes: int | None = Field(default=None, ge=10, le=120)


def _check_hours(hours: dict[str, list[str] | None]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for day, span in hours.items():
        if day not in CONSULT_DAYS:
            raise HTTPException(422, f"Unknown day '{day}': use mon to sun")
        if span is None:
            continue
        try:
            if len(span) != 2:
                raise ValueError
            start, end = (time.fromisoformat(v) for v in span)
        except (ValueError, TypeError):
            raise HTTPException(422, f"{day}: hours are two HH:MM times") from None
        if end <= start:
            raise HTTPException(422, f"{day}: the end time must be after the start time")
        out[day] = [av.fmt_time(start), av.fmt_time(end)]
    return out


def _profile(conn: Connection, pr: dict) -> dict:
    row = conn.execute(
        """
        SELECT modes, fee_cents, years_in_practice, bio, hours, slot_minutes, reply_hours, accepting, updated_at
        FROM consult_profiles WHERE practitioner_id = %s
        """,
        (pr["id"],),
    ).fetchone()
    cred = credential_state(conn, pr["id"])
    languages = conn.execute("SELECT languages FROM practitioners WHERE id = %s", (pr["id"],)).fetchone()["languages"]
    checks = [
        {"key": "license", "label": "Verified, unexpired license on file", "ok": cred["credentialed"]},
        {"key": "accepting", "label": "Accepting new patients", "ok": bool(row and row["accepting"])},
        {"key": "profile", "label": "Online consult profile set up", "ok": row is not None},
        {"key": "login", "label": "Has a Bioverse sign-in", "ok": pr["has_login"]},
    ]
    return {
        "practitioner": {k: pr[k] for k in ("id", "name", "specialty", "location_name", "has_login")},
        "exists": row is not None,
        "profile": row or {"modes": ["message"], "fee_cents": 0, "years_in_practice": None, "bio": None, "hours": {},
                           "slot_minutes": 30, "reply_hours": 24, "accepting": False, "updated_at": None},
        "languages": languages,
        "mode_options": list(CONSULT_MODES),
        "credential": {
            "credentialed": cred["credentialed"],
            "message": cred["message"],
            "credentials": [{k: c[k] for k in ("id", "license_type", "jurisdiction", "license_number", "status",
                                               "status_label", "expires_on", "lapsed", "expiring_soon")}
                            for c in cred["credentials"]],
        },
        "listed_in_directory": all(c["ok"] for c in checks),
        "listing_checks": checks,
        "directory_note": DIRECTORY_NOTE,
        "in_person_note": IN_PERSON_NOTE,
    }


def _patch_profile(conn: Connection, actor: User, pr: dict, body: ConsultProfilePatch) -> dict:
    changes = body.model_dump(exclude_unset=True)
    for key in ("fee_cents", "modes", "accepting", "reply_hours", "slot_minutes", "languages"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} can't be empty")
    if "modes" in changes:
        changes["modes"] = [m for m in CONSULT_MODES if m in changes["modes"]]
    if "hours" in changes:
        changes["hours"] = Jsonb(_check_hours(changes["hours"] or {}))
    if "bio" in changes:
        changes["bio"] = (changes["bio"] or "").strip() or None
    languages = changes.pop("languages", None)
    if languages is not None:
        clean: list[str] = []
        for lang in languages:
            lang = lang.strip()
            if not 1 <= len(lang) <= 40:
                raise HTTPException(422, "Each language is 1 to 40 characters")
            if lang.lower() not in (c.lower() for c in clean):
                clean.append(lang)
        conn.execute("UPDATE practitioners SET languages = %s WHERE id = %s", (clean, pr["id"]))
    conn.execute(
        "INSERT INTO consult_profiles (practitioner_id, fee_cents) VALUES (%s, 0) ON CONFLICT (practitioner_id) DO NOTHING",
        (pr["id"],),
    )
    if changes:
        cols = list(changes)
        conn.execute(
            "UPDATE consult_profiles SET " + ", ".join(f"{c} = %s" for c in cols) + ", updated_at = now() "
            "WHERE practitioner_id = %s",
            [changes[c] for c in cols] + [pr["id"]],
        )
    fields = sorted(list(changes) + (["languages"] if languages is not None else []))
    audit.record(conn, action="consult_profile.updated", entity_type="practitioner", entity_id=pr["id"], actor=actor,
                 detail={"fields": fields} | ({"fee_cents": changes["fee_cents"]} if "fee_cents" in changes else {})
                 | ({"accepting": changes["accepting"]} if "accepting" in changes else {}))
    return _profile(conn, pr)


# ---------------------------------------------------------------------------------------------
# Routes: the signed-in clinician
# ---------------------------------------------------------------------------------------------


@router.get("/clinician/availability")
def my_availability(conn: Conn, user: Clinician) -> dict:
    return _state(conn, _mine(conn, user))


@router.put("/clinician/availability")
def save_my_availability(body: TemplateIn, conn: Conn, user: Clinician) -> dict:
    return _save(conn, user, _mine(conn, user), body)


@router.post("/clinician/availability/time-off", status_code=status.HTTP_201_CREATED)
def add_my_time_off(body: TimeOffIn, conn: Conn, user: Clinician) -> dict:
    return _add_time_off(conn, user, _mine(conn, user), body)


@router.delete("/clinician/availability/time-off/{time_off_id}")
def remove_my_time_off(time_off_id: str, conn: Conn, user: Clinician) -> dict:
    return _remove_time_off(conn, user, _mine(conn, user), time_off_id)


@router.get("/clinician/availability/preview")
def preview_my_slots(conn: Conn, user: Clinician, days: int = Query(14, ge=1, le=av.MAX_PREVIEW_DAYS)) -> dict:
    return av.preview(conn, _mine(conn, user)["id"], _now(), days)


@router.get("/clinician/consult-profile")
def my_consult_profile(conn: Conn, user: Clinician) -> dict:
    return _profile(conn, _mine(conn, user))


@router.patch("/clinician/consult-profile")
def update_my_consult_profile(body: ConsultProfilePatch, conn: Conn, user: Clinician) -> dict:
    return _patch_profile(conn, user, _mine(conn, user), body)


# ---------------------------------------------------------------------------------------------
# Routes: administrators and the front desk, for any clinician in their organization
# ---------------------------------------------------------------------------------------------


@router.get("/admin/availability/practitioners")
def practitioners(conn: Conn, user: Scheduler) -> list[dict]:
    """Clinicians to pick from, with how much of their schedule is open."""
    return conn.execute(
        """
        SELECT pr.id::text, pr.name, pr.specialty, pr.location_name, (pr.user_id IS NOT NULL) AS has_login,
               (SELECT count(*) FROM availability_windows w WHERE w.practitioner_id = pr.id) AS windows,
               (SELECT count(*) FROM slots s WHERE s.practitioner_id = pr.id AND s.status = 'free'
                  AND s.starts_at > now()) AS free_upcoming,
               (SELECT count(*) FROM slots s WHERE s.practitioner_id = pr.id AND s.status = 'booked'
                  AND s.starts_at > now()) AS booked_upcoming
        FROM practitioners pr WHERE pr.organization_id = %s
        ORDER BY pr.name
        """,
        (user.organization_id,),
    ).fetchall()


@router.get("/admin/practitioners/{practitioner_id}/availability")
def clinician_availability(practitioner_id: str, conn: Conn, user: Scheduler) -> dict:
    return _state(conn, _practitioner(conn, user.organization_id, practitioner_id))


@router.put("/admin/practitioners/{practitioner_id}/availability")
def save_clinician_availability(practitioner_id: str, body: TemplateIn, conn: Conn, user: Scheduler) -> dict:
    return _save(conn, user, _practitioner(conn, user.organization_id, practitioner_id), body)


@router.post("/admin/practitioners/{practitioner_id}/availability/time-off", status_code=status.HTTP_201_CREATED)
def add_clinician_time_off(practitioner_id: str, body: TimeOffIn, conn: Conn, user: Scheduler) -> dict:
    return _add_time_off(conn, user, _practitioner(conn, user.organization_id, practitioner_id), body)


@router.delete("/admin/practitioners/{practitioner_id}/availability/time-off/{time_off_id}")
def remove_clinician_time_off(practitioner_id: str, time_off_id: str, conn: Conn, user: Scheduler) -> dict:
    return _remove_time_off(conn, user, _practitioner(conn, user.organization_id, practitioner_id), time_off_id)


@router.get("/admin/practitioners/{practitioner_id}/availability/preview")
def preview_clinician_slots(practitioner_id: str, conn: Conn, user: Scheduler,
                            days: int = Query(14, ge=1, le=av.MAX_PREVIEW_DAYS)) -> dict:
    return av.preview(conn, _practitioner(conn, user.organization_id, practitioner_id)["id"], _now(), days)


@router.get("/admin/practitioners/{practitioner_id}/consult-profile")
def clinician_consult_profile(practitioner_id: str, conn: Conn, user: Scheduler) -> dict:
    return _profile(conn, _practitioner(conn, user.organization_id, practitioner_id))


@router.patch("/admin/practitioners/{practitioner_id}/consult-profile")
def update_clinician_consult_profile(practitioner_id: str, body: ConsultProfilePatch, conn: Conn,
                                     user: Scheduler) -> dict:
    return _patch_profile(conn, user, _practitioner(conn, user.organization_id, practitioner_id), body)
