"""Clinician availability: weekly hours and time off, turned into bookable `slots`.

A practitioner's template is a set of weekly windows (weekday, start, end, in person or video, place, slot
length, optional effective dates) written in their own time zone, plus whole days off. `sync` materializes
free slots from it for a rolling horizon (28 days by default); the `availability_slots` job rolls the
horizon forward, and saving the template syncs straight away.

Rules the generator keeps:

- It owns only the slots it created (`slots.source = 'template'`). Seeded, imported and hand-made slots
  ('manual') are never changed or removed, and a generated slot is never placed on top of one.
- It never touches a booked slot, a slot in the past, or a slot an appointment row still points at.
- Future free generated slots that no longer fit the template (hours changed, time off added) are removed.
- Idempotent: running it twice changes nothing the second time (UNIQUE (practitioner_id, starts_at)).
- Wall-clock times are resolved with zoneinfo, so 09:00 stays 09:00 across a DST change. A time that does
  not exist (the spring-forward gap) gets no slot; an ambiguous one (fall back) uses its first occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from psycopg import Connection

from bioverse.config import clinic_tz

DEFAULT_HORIZON_DAYS = 28
MIN_HORIZON_DAYS, MAX_HORIZON_DAYS = 7, 90
MIN_SLOT_MINUTES, MAX_SLOT_MINUTES = 5, 120
MAX_WINDOWS = 60
MAX_TIME_OFF_DAYS = 366
MAX_PREVIEW_DAYS = 42
MODES = ("in_person", "video")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class AvailabilityError(ValueError):
    """A template that can't be saved. The message is shown to the person editing it."""


# ---------------------------------------------------------------------------------------------
# Time zones
# ---------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def check_timezone(name: str) -> ZoneInfo:
    if name not in _zones():
        raise AvailabilityError(f"Unknown time zone: {name}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AvailabilityError(f"Unknown time zone: {name}") from None


def settings(conn: Connection, practitioner_id: str) -> dict:
    row = conn.execute(
        "SELECT timezone, horizon_days, updated_at FROM availability_settings WHERE practitioner_id = %s",
        (practitioner_id,),
    ).fetchone()
    if row is None:
        return {"timezone": clinic_tz().key, "horizon_days": DEFAULT_HORIZON_DAYS, "timezone_is_default": True,
                "updated_at": None}
    return {**row, "timezone_is_default": False}


def practitioner_tz(conn: Connection, practitioner_id: str) -> ZoneInfo:
    name = settings(conn, practitioner_id)["timezone"]
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return clinic_tz()


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def fmt_time(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _ranges_overlap(a_from: date | None, a_until: date | None, b_from: date | None, b_until: date | None) -> bool:
    lo = max(a_from or date.min, b_from or date.min)
    hi = min(a_until or date.max, b_until or date.max)
    return lo <= hi


def validate_windows(windows: list[dict]) -> list[dict]:
    """Normalize and check a whole template. Raises AvailabilityError with a message a person can act on."""
    if len(windows) > MAX_WINDOWS:
        raise AvailabilityError(f"At most {MAX_WINDOWS} windows per week")
    out = []
    for w in windows:
        day = WEEKDAY_NAMES[w["weekday"]] if 0 <= w["weekday"] <= 6 else None
        if day is None:
            raise AvailabilityError("Weekday must be 0 (Monday) to 6 (Sunday)")
        start = w["start"].replace(second=0, microsecond=0, tzinfo=None)
        end = w["end"].replace(second=0, microsecond=0, tzinfo=None)
        label = f"{day} {fmt_time(start)}–{fmt_time(end)}"
        if _minutes(end) <= _minutes(start):
            raise AvailabilityError(f"{label}: the end time must be after the start time")
        if not MIN_SLOT_MINUTES <= w["slot_minutes"] <= MAX_SLOT_MINUTES:
            raise AvailabilityError(f"{label}: slot length must be {MIN_SLOT_MINUTES} to {MAX_SLOT_MINUTES} minutes")
        if _minutes(end) - _minutes(start) < w["slot_minutes"]:
            raise AvailabilityError(f"{label}: the window is shorter than one {w['slot_minutes']}-minute slot")
        if w["mode"] not in MODES:
            raise AvailabilityError(f"{label}: mode must be in person or video")
        ef, eu = w.get("effective_from"), w.get("effective_until")
        if ef and eu and eu < ef:
            raise AvailabilityError(f"{label}: 'effective until' is before 'effective from'")
        location = (w.get("location") or "").strip() or None
        out.append({**w, "start": start, "end": end, "location": location, "effective_from": ef,
                    "effective_until": eu, "_label": label})
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if (a["weekday"] == b["weekday"]
                    and _minutes(a["start"]) < _minutes(b["end"]) and _minutes(b["start"]) < _minutes(a["end"])
                    and _ranges_overlap(a["effective_from"], a["effective_until"], b["effective_from"], b["effective_until"])):
                raise AvailabilityError(f"{a['_label']} overlaps {fmt_time(b['start'])}–{fmt_time(b['end'])}")
    for w in out:
        w.pop("_label")
    return sorted(out, key=lambda w: (w["weekday"], w["start"]))


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


def windows(conn: Connection, practitioner_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT id::text, weekday, start_time, end_time, mode, location, slot_minutes, effective_from, effective_until
        FROM availability_windows WHERE practitioner_id = %s ORDER BY weekday, start_time
        """,
        (practitioner_id,),
    ).fetchall()


def time_off(conn: Connection, practitioner_id: str, since: date | None = None) -> list[dict]:
    return conn.execute(
        """
        SELECT id::text, starts_on, ends_on, reason, created_at FROM availability_time_off
        WHERE practitioner_id = %s AND (%s::date IS NULL OR ends_on >= %s::date)
        ORDER BY starts_on, ends_on
        """,
        (practitioner_id, since, since),
    ).fetchall()


def window_out(w: dict) -> dict:
    return {"id": w["id"], "weekday": w["weekday"], "weekday_name": WEEKDAY_NAMES[w["weekday"]],
            "start": fmt_time(w["start_time"]), "end": fmt_time(w["end_time"]), "mode": w["mode"],
            "location": w["location"], "slot_minutes": w["slot_minutes"],
            "effective_from": w["effective_from"], "effective_until": w["effective_until"]}


# ---------------------------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    starts_at: datetime        # UTC
    duration_min: int
    mode: str
    location: str | None

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_min)


def local_instant(day: date, wall: time, tz: ZoneInfo) -> datetime | None:
    """The instant a wall-clock time happens on `day`, or None when it doesn't exist (spring forward).
    An ambiguous time (fall back) resolves to its first occurrence."""
    local = datetime.combine(day, wall, tzinfo=tz)            # fold=0: the earlier of two, if ambiguous
    utc = local.astimezone(timezone.utc)
    if utc.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return utc


def candidates(template: list[dict], days_off: list[dict], tz: ZoneInfo, first_day: date, days: int,
               after: datetime) -> list[Candidate]:
    """Every slot the template calls for on `days` local days from `first_day`, starting after `after`."""
    out: list[Candidate] = []
    for i in range(days):
        day = first_day + timedelta(days=i)
        if any(t["starts_on"] <= day <= t["ends_on"] for t in days_off):
            continue
        for w in template:
            if w["weekday"] != day.weekday():
                continue
            if (w["effective_from"] and day < w["effective_from"]) or (w["effective_until"] and day > w["effective_until"]):
                continue
            step, end = w["slot_minutes"], _minutes(w["end_time"])
            m = _minutes(w["start_time"])
            while m + step <= end:
                at = local_instant(day, time(m // 60, m % 60), tz)
                if at is not None and at > after:
                    out.append(Candidate(at, step, w["mode"], w["location"]))
                m += step
    out.sort(key=lambda c: c.starts_at)
    return out


def _overlaps(start: datetime, end: datetime, spans: list[tuple[datetime, datetime]]) -> bool:
    return any(start < e and s < end for s, e in spans)


@dataclass
class Plan:
    existing: list[dict]             # every slot from `now` on (plus a little before, for overlap checks)
    delete: list[dict]
    update: list[tuple[dict, Candidate]]
    insert: list[Candidate]
    tz: ZoneInfo
    first_day: date
    days: int


def _existing(conn: Connection, practitioner_id: str, now: datetime) -> list[dict]:
    return conn.execute(
        """
        SELECT s.id::text, s.starts_at, s.duration_min, s.mode, s.status, s.source, s.location,
               EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id = s.id) AS referenced
        FROM slots s
        WHERE s.practitioner_id = %s AND s.starts_at > %s
        ORDER BY s.starts_at
        """,
        (practitioner_id, now - timedelta(minutes=MAX_SLOT_MINUTES)),
    ).fetchall()


def plan(conn: Connection, practitioner_id: str, now: datetime, days: int | None = None) -> Plan:
    """What `sync` would do. Nothing is written."""
    conf = settings(conn, practitioner_id)
    tz = practitioner_tz(conn, practitioner_id)
    days = days or conf["horizon_days"]
    first_day = now.astimezone(tz).date()
    wanted = candidates(windows(conn, practitioner_id), time_off(conn, practitioner_id, first_day), tz,
                        first_day, days, now)
    by_start = {c.starts_at: c for c in wanted}
    existing = _existing(conn, practitioner_id, now)

    def managed(s: dict) -> bool:
        return s["source"] == "template" and s["status"] == "free" and s["starts_at"] > now and not s["referenced"]

    # Slots nobody may move: everything the generator doesn't own, and anything booked or in the past.
    fixed = [(s["starts_at"], s["starts_at"] + timedelta(minutes=s["duration_min"])) for s in existing if not managed(s)]
    delete: list[dict] = []
    update: list[tuple[dict, Candidate]] = []
    taken: list[tuple[datetime, datetime]] = list(fixed)
    kept_starts: set[datetime] = {s["starts_at"] for s in existing if not managed(s)}
    for s in existing:
        if not managed(s):
            continue
        c = by_start.get(s["starts_at"])
        if c is None or _overlaps(c.starts_at, c.ends_at, fixed):
            delete.append(s)
            continue
        if (c.duration_min, c.mode, c.location) != (s["duration_min"], s["mode"], s["location"]):
            update.append((s, c))
        taken.append((c.starts_at, c.ends_at))
        kept_starts.add(s["starts_at"])
    insert: list[Candidate] = []
    for c in wanted:
        if c.starts_at in kept_starts:
            continue
        if _overlaps(c.starts_at, c.ends_at, taken):
            continue
        insert.append(c)
        taken.append((c.starts_at, c.ends_at))
    return Plan(existing, delete, update, insert, tz, first_day, days)


def sync(conn: Connection, practitioner_id: str, now: datetime | None = None) -> dict:
    """Bring the practitioner's generated free slots in line with their template. Safe to repeat."""
    now = now or datetime.now(timezone.utc)
    # One sync per practitioner at a time (a save and the job can overlap).
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('availability:' || %s))", (practitioner_id,))
    p = plan(conn, practitioner_id, now)
    removed = 0
    if p.delete:
        # Rechecked under the row lock: a slot booked a moment ago is left alone.
        removed = conn.execute(
            """
            DELETE FROM slots s WHERE s.id = ANY(%s::uuid[]) AND s.source = 'template' AND s.status = 'free'
              AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id = s.id)
            """,
            ([s["id"] for s in p.delete],),
        ).rowcount
    updated = 0
    for s, c in p.update:
        updated += conn.execute(
            """
            UPDATE slots SET duration_min = %s, mode = %s, location = %s
            WHERE id = %s AND source = 'template' AND status = 'free'
            """,
            (c.duration_min, c.mode, c.location, s["id"]),
        ).rowcount
    created = 0
    if p.insert:
        with conn.cursor() as cur:
            for c in p.insert:
                cur.execute(
                    """
                    INSERT INTO slots (practitioner_id, starts_at, duration_min, mode, status, source, location)
                    VALUES (%s, %s, %s, %s, 'free', 'template', %s)
                    ON CONFLICT (practitioner_id, starts_at) DO NOTHING
                    """,
                    (practitioner_id, c.starts_at, c.duration_min, c.mode, c.location),
                )
                created += cur.rowcount
    return {"created": created, "removed": removed, "updated": updated,
            "horizon_until": p.first_day + timedelta(days=p.days - 1)}


def preview(conn: Connection, practitioner_id: str, now: datetime, days: int) -> dict:
    """The slots that will exist over the next `days` local days once the template is applied."""
    days = max(1, min(days, MAX_PREVIEW_DAYS))
    horizon = settings(conn, practitioner_id)["horizon_days"]
    p = plan(conn, practitioner_id, now, max(days, horizon))
    last_day = p.first_day + timedelta(days=days - 1)
    gone = {s["id"] for s in p.delete}
    changed = {s["id"]: c for s, c in p.update}
    patients = {r["slot_id"]: r["patient_name"] for r in conn.execute(
        """
        SELECT a.slot_id::text, pt.name AS patient_name FROM appointments a JOIN patients pt ON pt.id = a.patient_id
        JOIN slots s ON s.id = a.slot_id
        WHERE a.practitioner_id = %s AND a.status = 'booked' AND s.starts_at > %s
        """,
        (practitioner_id, now),
    ).fetchall()}

    items = []
    for s in p.existing:
        if s["id"] in gone or s["starts_at"] <= now:
            continue
        c = changed.get(s["id"])
        items.append({"id": s["id"], "starts_at": s["starts_at"], "duration_min": c.duration_min if c else s["duration_min"],
                      "mode": c.mode if c else s["mode"], "location": c.location if c else s["location"],
                      "status": s["status"], "source": s["source"], "pending": False,
                      "patient_name": patients.get(s["id"]) if s["status"] == "booked" else None})
    for c in p.insert:
        items.append({"id": None, "starts_at": c.starts_at, "duration_min": c.duration_min, "mode": c.mode,
                      "location": c.location, "status": "free", "source": "template", "pending": True,
                      "patient_name": None})
    out = []
    for it in sorted(items, key=lambda i: i["starts_at"]):
        local = it["starts_at"].astimezone(p.tz)
        if local.date() > last_day:
            continue
        it["local_date"] = local.date()
        it["local_time"] = f"{local:%H:%M}"
        it["ends_at"] = it["starts_at"] + timedelta(minutes=it["duration_min"])
        out.append(it)
    return {
        "timezone": p.tz.key,
        "from": p.first_day,
        "until": last_day,
        "slots": out,
        "summary": {
            "free": sum(1 for i in out if i["status"] == "free"),
            "booked": sum(1 for i in out if i["status"] == "booked"),
            "pending": sum(1 for i in out if i["pending"]),
            "to_remove": sum(1 for s in p.delete if s["starts_at"].astimezone(p.tz).date() <= last_day),
        },
        "days_off": [t for t in time_off(conn, practitioner_id, p.first_day) if t["starts_on"] <= last_day],
    }
