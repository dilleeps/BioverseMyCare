"""Vital signs and connected devices: home readings, trends, meter photos, devices and imports, abnormal-reading
alerts, clinician thresholds and home monitoring plans.

Domain rules live in `vitals_core` (validation, thresholds, alerts, trends, adherence) and file/photo reading in
`vitals_import`. Alerts are rules only; the one AI feature is reading a meter photo, which proposes numbers the
patient confirms before anything is saved, and falls back to the typed form in rules mode.

Access: patients reach their own readings, devices and plans. Clinicians reach patients in their organization
and own thresholds, plans and alert acknowledgement. Staff and administrators have no access to vitals.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field

from bioverse import audit, consent
from bioverse.agents import llm
from bioverse.auth import Clinician, CurrentUser, Patient, User, assert_patient_access
from bioverse.config import clinic_tz
from bioverse.db import DbConn
from bioverse.notify import cancel, notify, patient_user
from bioverse.routers import vitals_core as core
from bioverse.routers import vitals_import as imp

router = APIRouter(prefix="/api/vitals", tags=["vitals"])

Conn = DbConn

DEMO_PAIRING = ("Demo pairing. No real device is connected: readings arrive when you log them, snap a photo "
                "or import a file.")
PHOTO_NOTICE = "Check these numbers against your meter before saving. The photo itself is not kept."
MAX_PHOTO_BYTES = 5 * 1024 * 1024
UNITS = {"temperature": ["°C", "°F"], "weight": ["kg", "lb"], "glucose": ["mg/dL", "mmol/L"]}


def _uuid(value: str, what: str = "Record") -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found") from None


def _scope(conn: Connection, user: User, patient_id: str | None) -> str:
    """Patients: themselves. Clinicians: patients in their organization (patient_id required)."""
    if patient_id:
        patient_id = _uuid(patient_id, "Patient")
    if user.role == "patient" and user.patient_id:
        if patient_id and patient_id != user.patient_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record")
        return user.patient_id
    if user.role == "clinician" and user.practitioner_id:
        if not patient_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
        assert_patient_access(conn, user, patient_id)
        return patient_id
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Home vitals are available to the patient and their clinicians")


def _reading_error(exc: core.ReadingError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "invalid_reading", "field": exc.field,
                                                                  "message": str(exc)})


def _alerts_view(alerts: list[dict], user: User) -> list[dict]:
    """Patients see what happened and that their care team knows; not the clinician's detail or notes."""
    if user.role != "patient":
        return alerts
    hidden = ("detail", "ack_note", "review_item_id", "practitioner_name")
    return [{k: v for k, v in a.items() if k not in hidden} for a in alerts]


def _measures_meta() -> list[dict]:
    return [{"key": m.key, "label": m.label, "unit": m.unit_label, "units": UNITS.get(m.key),
             "plan": m.key in core.PLAN_MEASURES} for m in core.MEASURES.values()]


# --- Overview and trends -----------------------------------------------------------------------------


@router.get("/summary")
def summary(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _scope(conn, user, patient_id)
    patient = conn.execute("SELECT id::text, name FROM patients WHERE id = %s", (pid,)).fetchone()
    th = core.thresholds(conn, pid)
    out = {
        "patient": patient,
        "measures": _measures_meta(),
        "glucose_contexts": [{"key": k, "label": core.CONTEXT_LABEL[k]} for k in core.GLUCOSE_CONTEXTS],
        "tiles": core.tiles(conn, pid),
        "plans": core.plans_for(conn, pid),
        "alerts": _alerts_view(core.alerts_for(conn, pid, days=30), user),
        "devices": core.devices_for(conn, pid),
        "thresholds": list(th.values()),
        "device_kinds": [{"key": k, "label": v} for k, v in core.DEVICE_KINDS.items()],
        "integrations": [{"key": k, "label": v} for k, v in core.INTEGRATIONS.items()],
        "demo_pairing_notice": DEMO_PAIRING,
    }
    if user.role != "patient":
        audit.record(conn, action="vitals_viewed", entity_type="patient", entity_id=pid, actor=user, patient_id=pid)
    return out


@router.get("/measures/{measure}")
def measure_detail(measure: str, conn: Conn, user: CurrentUser, patient_id: str | None = None,
                   days: int = 30) -> dict:
    if measure not in core.MEASURES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown measure")
    if days not in (7, 30, 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "days must be 7, 30 or 90")
    pid = _scope(conn, user, patient_id)
    out = core.series(conn, pid, measure, days, own=user.role == "patient")
    if user.role != "patient":
        audit.record(conn, action="vitals_trend_viewed", entity_type="patient", entity_id=pid, actor=user,
                     patient_id=pid, detail={"measure": measure, "days": days})
    return out


# --- Logging readings --------------------------------------------------------------------------------


Measure = Literal["bp", "heart_rate", "spo2", "temperature", "glucose", "weight", "steps", "sleep"]
Context = Literal["fasting", "before_meal", "after_meal", "bedtime", "random"]


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: Measure
    systolic: float | None = None
    diastolic: float | None = None
    pulse: float | None = None
    value: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    context: Context | None = None
    taken_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)
    source: Literal["manual", "photo"] = "manual"


def log_reading(conn: Connection, user: User, body: ReadingIn) -> dict:
    now = core.utcnow()
    try:
        values = core.normalize(body.measure, systolic=body.systolic, diastolic=body.diastolic, pulse=body.pulse,
                                value=body.value, unit=body.unit, context=body.context)
        taken_at = core.check_time(body.taken_at, now)
    except core.ReadingError as exc:
        raise _reading_error(exc) from None
    th = core.thresholds(conn, user.patient_id)
    reading = core.store_reading(conn, patient_id=user.patient_id, values=values, taken_at=taken_at,
                                 source=body.source, context=body.context if body.measure == "glucose" else None,
                                 note=(body.note or "").strip() or None, th=th)
    audit.record(conn, action="vital_logged", entity_type="observation", entity_id=reading["id"], actor=user,
                 patient_id=user.patient_id, detail={"measure": body.measure, "source": body.source})
    result = core.evaluate(conn, user.patient_id, reading, now=now, th=th)
    reading_view = core.reading_out(body.measure, {
        "id": reading["id"], "at": taken_at, "values": {o["code"]: o["value"] for o in reading["observations"]},
        "source": body.source, "context": reading["context"], "device": None, "note": body.note}, th, True)
    reading_view["measure"] = body.measure
    return {"reading": reading_view, "alerts": result["alerts"], "safety": result["safety"], "note": result["note"]}


@router.post("/readings", status_code=status.HTTP_201_CREATED)
def create_reading(body: ReadingIn, conn: Conn, user: Patient) -> dict:
    return log_reading(conn, user, body)


@router.delete("/readings/{reading_id}")
def delete_reading(reading_id: str, conn: Conn, user: Patient) -> dict:
    rid = _uuid(reading_id, "Reading")
    rows = conn.execute(
        """
        SELECT id::text, source, loinc_code FROM observations
        WHERE patient_id = %s AND category IN ('vital-signs', 'activity') AND (id = %s OR panel_id = %s)
        FOR UPDATE
        """,
        (user.patient_id, rid, rid),
    ).fetchall()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading not found")
    if any(r["source"] not in ("manual", "photo") for r in rows):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only readings you entered yourself can be deleted. Device and imported readings stay "
                            "as they arrived.")
    conn.execute("DELETE FROM observations WHERE id = ANY(%s)", ([r["id"] for r in rows],))
    audit.record(conn, action="vital_deleted", entity_type="observation", entity_id=rid, actor=user,
                 patient_id=user.patient_id, detail={"observations": len(rows)})
    return {"id": rid, "deleted": len(rows)}


# --- Meter photo ------------------------------------------------------------------------------------


class PhotoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(min_length=1, max_length=7_200_000)
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    hint: Literal["bp_cuff", "glucometer", "thermometer", "scale", "pulse_oximeter"] | None = None


def _manual(reason: str, message: str) -> dict:
    return {"needs_manual": True, "reason": reason, "message": message, "proposal": None,
            "notice": "Type the numbers from your meter's display into the form. The photo is not kept."}


@router.post("/photo")
def read_meter_photo(body: PhotoIn, conn: Conn, user: Patient) -> dict:
    """Propose a reading from a meter photo. Nothing is saved: the patient confirms it through POST /readings."""
    data = body.image.split(",", 1)[1] if body.image.startswith("data:") else body.image
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The photo couldn't be read. Try again.") from None
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Photos can be 5 MB at most.")
    detail = {"media_type": body.media_type, "bytes": len(raw), "hint": body.hint, "stored": False}

    if not consent.ai_allowed(conn, user.patient_id):
        audit.record(conn, action="vital_photo_manual", entity_type="observation", actor=user, agent="vitals-photo",
                     patient_id=user.patient_id, detail={**detail, "reason": "ai_consent"})
        return _manual("ai_consent", "You've chosen not to have AI process your information, so Bioverse won't "
                                     "read the photo. Type the numbers you see instead.")
    try:
        result = imp.read_photo(data, body.media_type, body.hint)
    except llm.LLMUnavailable:
        audit.record(conn, action="vital_photo_manual", entity_type="observation", actor=user, agent="vitals-photo",
                     patient_id=user.patient_id, detail={**detail, "reason": "ai_unavailable"})
        return _manual("ai_unavailable", "Bioverse can't read photos right now. Type the numbers from the display.")

    r = result.output
    measure = imp.DEVICE_MEASURE.get(r.device_type) or imp.DEVICE_MEASURE.get(body.hint or "")
    audit.record(conn, action="vital_photo_read", entity_type="observation", actor=user,
                 agent="vitals-photo/claude", model=result.model, patient_id=user.patient_id,
                 detail={**detail, "device_type": r.device_type, "confidence": r.confidence,
                         "readable": r.display_readable})
    if not r.display_readable or measure is None:
        return _manual("unreadable", "We couldn't read the display clearly. Type the numbers you see, or try "
                                     "another photo with the display in focus and no glare.")
    proposal = {"measure": measure, "systolic": r.systolic, "diastolic": r.diastolic, "pulse": r.pulse,
                "value": r.value, "unit": r.unit, "context": None}
    if measure not in ("bp", "spo2"):
        proposal["pulse"] = None
    problem = None
    try:
        core.normalize(measure, systolic=r.systolic, diastolic=r.diastolic, pulse=proposal["pulse"], value=r.value,
                       unit=r.unit)
    except core.ReadingError as exc:
        problem = str(exc)
    return {"needs_manual": False, "reason": None, "proposal": proposal, "device_type": r.device_type,
            "confidence": r.confidence, "problem": problem, "notice": PHOTO_NOTICE,
            "produced_by": "vitals-photo/claude"}


# --- Devices and imports ----------------------------------------------------------------------------


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bp_cuff", "glucometer", "scale", "pulse_oximeter", "thermometer", "wearable"]
    integration: Literal["bluetooth", "apple_health", "health_connect", "fitbit", "manual_import"]
    vendor: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    serial: str | None = Field(default=None, max_length=80)


@router.get("/devices")
def list_devices(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _scope(conn, user, patient_id)
    return {"devices": core.devices_for(conn, pid), "notice": DEMO_PAIRING}


@router.post("/devices", status_code=status.HTTP_201_CREATED)
def connect_device(body: DeviceIn, conn: Conn, user: Patient) -> dict:
    clean = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in body.model_dump().items()}
    row = conn.execute(
        """
        INSERT INTO devices (patient_id, kind, vendor, model, integration, serial, simulated)
        VALUES (%s, %s, %s, %s, %s, %s, true) RETURNING id::text
        """,
        (user.patient_id, clean["kind"], clean["vendor"], clean["model"], clean["integration"], clean["serial"]),
    ).fetchone()
    audit.record(conn, action="device_connected", entity_type="device", entity_id=row["id"], actor=user,
                 patient_id=user.patient_id, detail={"kind": clean["kind"], "integration": clean["integration"],
                                                     "simulated": True})
    device = next(d for d in core.devices_for(conn, user.patient_id) if d["id"] == row["id"])
    return {**device, "notice": DEMO_PAIRING}


def _own_device(conn: Connection, user: User, device_id: str) -> dict:
    row = conn.execute(
        "SELECT id::text, kind, vendor, model, integration, status FROM devices WHERE id = %s AND patient_id = %s "
        "FOR UPDATE",
        (_uuid(device_id, "Device"), user.patient_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    return row


@router.post("/devices/{device_id}/disconnect")
def disconnect_device(device_id: str, conn: Conn, user: Patient) -> dict:
    d = _own_device(conn, user, device_id)
    if d["status"] == "disconnected":
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is already disconnected")
    conn.execute("UPDATE devices SET status = 'disconnected', disconnected_at = now() WHERE id = %s", (d["id"],))
    audit.record(conn, action="device_disconnected", entity_type="device", entity_id=d["id"], actor=user,
                 patient_id=user.patient_id)
    return {"id": d["id"], "status": "disconnected"}


@router.post("/devices/{device_id}/connect")
def reconnect_device(device_id: str, conn: Conn, user: Patient) -> dict:
    d = _own_device(conn, user, device_id)
    if d["status"] == "connected":
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is already connected")
    conn.execute("UPDATE devices SET status = 'connected', disconnected_at = NULL WHERE id = %s", (d["id"],))
    audit.record(conn, action="device_connected", entity_type="device", entity_id=d["id"], actor=user,
                 patient_id=user.patient_id, detail={"reconnected": True, "simulated": True})
    return {"id": d["id"], "status": "connected"}


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["json", "csv", "apple_health"]
    content: str = Field(min_length=1, max_length=5_000_000)
    device_id: str | None = None


@router.post("/import")
def import_readings(body: ImportIn, conn: Conn, user: Patient) -> dict:
    """Import a batch. Rows that repeat a stored reading (same code, time and value) are skipped."""
    device = None
    if body.device_id:
        device = _own_device(conn, user, body.device_id)
        if device["status"] != "connected":
            raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect this device before importing its readings")
        device = {"id": device["id"], "label": core.device_label(device)}
    try:
        rows = imp.PARSERS[body.format](body.content)
    except imp.ImportError_ as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "unreadable_file", "message": str(exc)}) from None
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Import up to {imp.MAX_ROWS} readings at a time.")

    now = core.utcnow()
    th = core.thresholds(conn, user.patient_id)
    imported, skipped, rejected = 0, 0, []
    by_measure: dict[str, int] = {}
    seen: set[tuple] = set()
    alerts: dict[str, dict] = {}
    safety = None
    order = sorted(range(len(rows)), key=lambda i: (isinstance(rows[i], Exception),
                                                    rows[i]["taken_at"] if isinstance(rows[i], dict) else now))
    for i in order:
        row = rows[i]
        if isinstance(row, Exception):
            rejected.append({"row": i + 1, "reason": str(row)})
            continue
        try:
            values = core.normalize(row["measure"], systolic=row["systolic"], diastolic=row["diastolic"],
                                    pulse=row["pulse"], value=row["value"], unit=row["unit"], context=row["context"])
            taken_at = core.check_time(row["taken_at"], now, max_age_days=730)
        except core.ReadingError as exc:
            rejected.append({"row": i + 1, "reason": str(exc)})
            continue
        key = (values[0][0], taken_at, values[0][1])
        if key in seen or core.exists(conn, user.patient_id, values[0][0], taken_at, values[0][1]):
            skipped += 1
            continue
        seen.add(key)
        reading = core.store_reading(conn, patient_id=user.patient_id, values=values, taken_at=taken_at,
                                     source="import", context=row["context"] if row["measure"] == "glucose" else None,
                                     device=device, th=th)
        imported += 1
        by_measure[row["measure"]] = by_measure.get(row["measure"], 0) + 1
        result = core.evaluate(conn, user.patient_id, reading, now=now, th=th)
        for a in result["alerts"]:
            alerts[a["id"]] = a
        safety = safety or result["safety"]
    if device:
        conn.execute("UPDATE devices SET last_sync = now() WHERE id = %s", (device["id"],))
    audit.record(conn, action="vitals_imported", entity_type="observation", actor=user, patient_id=user.patient_id,
                 detail={"format": body.format, "imported": imported, "skipped": skipped, "rejected": len(rejected),
                         "device_id": device["id"] if device else None})
    return {"imported": imported, "skipped": skipped, "rejected": rejected[:50], "rejected_count": len(rejected),
            "by_measure": by_measure, "alerts": list(alerts.values()), "safety": safety}


# --- Alerts -----------------------------------------------------------------------------------------


@router.get("/alerts")
def list_alerts(conn: Conn, user: CurrentUser, patient_id: str | None = None,
                status_filter: Literal["open", "acknowledged", "all"] = "all") -> list[dict]:
    pid = _scope(conn, user, patient_id)
    return _alerts_view(core.alerts_for(conn, pid, status=None if status_filter == "all" else status_filter), user)


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, body: AckIn, conn: Conn, user: Clinician) -> dict:
    row = conn.execute("SELECT patient_id::text FROM vital_alerts WHERE id = %s",
                       (_uuid(alert_id, "Alert"),)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    assert_patient_access(conn, user, row["patient_id"])
    try:
        core.acknowledge(conn, alert_id=alert_id, user=user, note=(body.note or "").strip() or None)
    except ValueError:
        raise HTTPException(status.HTTP_409_CONFLICT, "This alert has already been acknowledged") from None
    return {"id": alert_id, "status": "acknowledged"}


# --- Clinician: thresholds, plans, monitored patients ----------------------------------------------


class ThresholdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: float | None = None
    high: float | None = None
    critical_low: float | None = None
    critical_high: float | None = None
    note: str | None = Field(default=None, max_length=300)


def _check_threshold(code: str, body: ThresholdIn) -> None:
    def bad(msg):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)

    if code == core.WEIGHT_GAIN:
        if body.low is not None or body.critical_low is not None or body.critical_high is not None:
            bad("Weight gain takes only a 'high' limit: kilograms gained within 3 days")
        if body.high is None or not 0.5 <= body.high <= 10:
            bad("Set the weight gain limit between 0.5 and 10 kg")
        return
    lo, hi = core.PLAUSIBLE[code]
    vals = {k: getattr(body, k) for k in ("critical_low", "low", "high", "critical_high")}
    if all(v is None for v in vals.values()):
        bad("Set at least one limit")
    for k, v in vals.items():
        if v is not None and not lo <= v <= hi:
            bad(f"{k.replace('_', ' ').capitalize()} must be between {core.fmt(lo)} and {core.fmt(hi)}")
    d = core.CODES[code]
    merged = {"critical_low": d.critical_low, "low": d.low, "high": d.high, "critical_high": d.critical_high}
    merged.update({k: v for k, v in vals.items() if v is not None})
    chain = [merged[k] for k in ("critical_low", "low", "high", "critical_high") if merged[k] is not None]
    if chain != sorted(chain):
        bad("Limits must go in order: critical low ≤ low ≤ high ≤ critical high")


@router.put("/patients/{patient_id}/thresholds/{code}")
def set_threshold(patient_id: str, code: str, body: ThresholdIn, conn: Conn, user: Clinician) -> dict:
    pid = _scope(conn, user, patient_id)
    if code not in (*core.THRESHOLD_CODES, core.WEIGHT_GAIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown threshold")
    _check_threshold(code, body)
    rule = conn.execute(
        """
        INSERT INTO vital_alert_rules (patient_id, code, low, high, critical_low, critical_high, note, set_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (patient_id, code) DO UPDATE SET low = EXCLUDED.low, high = EXCLUDED.high,
            critical_low = EXCLUDED.critical_low, critical_high = EXCLUDED.critical_high, note = EXCLUDED.note,
            set_by = EXCLUDED.set_by, updated_at = now()
        RETURNING id::text
        """,
        (pid, code, body.low, body.high, body.critical_low, body.critical_high, (body.note or "").strip() or None,
         user.practitioner_id),
    ).fetchone()
    audit.record(conn, action="vital_threshold_set", entity_type="vital_alert_rule", entity_id=rule["id"], actor=user,
                 patient_id=pid, detail={"code": code, **body.model_dump()})
    return core.thresholds(conn, pid)[code]


@router.delete("/patients/{patient_id}/thresholds/{code}")
def reset_threshold(patient_id: str, code: str, conn: Conn, user: Clinician) -> dict:
    pid = _scope(conn, user, patient_id)
    if code not in (*core.THRESHOLD_CODES, core.WEIGHT_GAIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown threshold")
    gone = conn.execute("DELETE FROM vital_alert_rules WHERE patient_id = %s AND code = %s RETURNING id::text",
                        (pid, code)).fetchone()
    if gone:
        audit.record(conn, action="vital_threshold_reset", entity_type="vital_alert_rule", entity_id=gone["id"],
                     actor=user, patient_id=pid, detail={"code": code})
    return core.thresholds(conn, pid)[code]


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: Literal["bp", "heart_rate", "spo2", "temperature", "glucose", "weight"]
    times: list[time] = Field(min_length=1, max_length=4)
    days: int = Field(ge=1, le=90)
    start_on: date | None = None
    instructions: str | None = Field(default=None, max_length=500)


@router.post("/patients/{patient_id}/plans", status_code=status.HTTP_201_CREATED)
def create_plan(patient_id: str, body: PlanIn, conn: Conn, user: Clinician) -> dict:
    pid = _scope(conn, user, patient_id)
    today = datetime.now(clinic_tz()).date()
    start = body.start_on or today
    if start < today or start > today + timedelta(days=60):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Start today or within the next 60 days")
    times = sorted({t.replace(second=0, microsecond=0, tzinfo=None) for t in body.times})
    for a, b in zip(times, times[1:]):
        if (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute) < core.MIN_GAP_HOURS * 60:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"Space measurement times at least {core.MIN_GAP_HOURS} hours apart")
    active = conn.execute(
        "SELECT 1 FROM vital_monitoring_plans WHERE patient_id = %s AND measure = %s AND status = 'active'",
        (pid, body.measure),
    ).fetchone()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's already an active plan for this measure. Stop it first.")
    row = conn.execute(
        """
        INSERT INTO vital_monitoring_plans (patient_id, practitioner_id, measure, times, start_on, end_on, instructions)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (pid, user.practitioner_id, body.measure, times, start, start + timedelta(days=body.days - 1),
         (body.instructions or "").strip() or None),
    ).fetchone()
    plan = next(p for p in core.plans_for(conn, pid) if p["id"] == row["id"])
    uid = patient_user(conn, pid)
    if uid:
        notify(conn, user_id=uid, kind="vital_reminder", title="New home monitoring plan from your care team",
                    body=f"{plan['label']}, at {', '.join(plan['times'])}. " + (plan["instructions"] or ""),
                    link="/vitals", patient_id=pid, dedupe_key=f"vitals:plan:{row['id']}:created",
                    created_by=user.id)
    audit.record(conn, action="vital_plan_created", entity_type="vital_monitoring_plan", entity_id=row["id"],
                 actor=user, patient_id=pid, detail={"measure": body.measure, "times": plan["times"], "days": body.days})
    return plan


@router.post("/plans/{plan_id}/stop")
def stop_plan(plan_id: str, conn: Conn, user: Clinician) -> dict:
    row = conn.execute("SELECT id::text, patient_id::text, status FROM vital_monitoring_plans WHERE id = %s FOR UPDATE",
                       (_uuid(plan_id, "Plan"),)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    assert_patient_access(conn, user, row["patient_id"])
    if row["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This plan has already ended")
    conn.execute("UPDATE vital_monitoring_plans SET status = 'stopped', stopped_at = now(), stopped_by = %s WHERE id = %s",
                 (user.id, row["id"]))
    uid = patient_user(conn, row["patient_id"])
    if uid:
        notify(conn, user_id=uid, kind="vital_reminder", title="Home monitoring plan ended",
                    body="Your care team has stopped this home monitoring plan. You can keep logging readings.",
                    link="/vitals", patient_id=row["patient_id"], dedupe_key=f"vitals:plan:{row['id']}:stopped",
                    created_by=user.id)
        cancel(conn, user_id=uid, dedupe_prefix=f"vitals:plan:{row['id']}:slot:")
    audit.record(conn, action="vital_plan_stopped", entity_type="vital_monitoring_plan", entity_id=row["id"],
                 actor=user, patient_id=row["patient_id"])
    return {"id": row["id"], "status": "stopped"}


@router.get("/clinician/patients")
def monitored_patients(conn: Conn, user: Clinician) -> list[dict]:
    """Patients in my organization with home vitals needing me: open alerts or plans I prescribed."""
    rows = conn.execute(
        """
        SELECT p.id::text, p.name,
               (SELECT count(*) FROM vital_alerts a WHERE a.patient_id = p.id AND a.status = 'open') AS open_alerts,
               (SELECT count(*) FROM vital_alerts a WHERE a.patient_id = p.id AND a.status = 'open'
                  AND a.severity = 'critical') AS critical_alerts,
               (SELECT max(o.effective_at) FROM observations o WHERE o.patient_id = p.id
                  AND o.category IN ('vital-signs', 'activity')) AS last_reading_at
        FROM patients p
        WHERE p.organization_id = %(org)s AND (
            EXISTS (SELECT 1 FROM vital_alerts a WHERE a.patient_id = p.id AND a.status = 'open'
                    AND (a.practitioner_id = %(pr)s OR a.practitioner_id IS NULL))
            OR EXISTS (SELECT 1 FROM vital_monitoring_plans v WHERE v.patient_id = p.id AND v.status = 'active'
                       AND v.practitioner_id = %(pr)s))
        ORDER BY critical_alerts DESC, open_alerts DESC, p.name
        """,
        {"org": user.organization_id, "pr": user.practitioner_id},
    ).fetchall()
    for r in rows:
        r["plans"] = [{"id": p["id"], "label": p["label"], "adherence": {k: p["adherence"][k] for k in ("done", "expected", "pct")}}
                      for p in core.plans_for(conn, r["id"], include_ended=False)]
        bp = core.recent_readings(conn, r["id"], "bp", core.utcnow() - timedelta(days=14))
        r["bp_14d"] = core.average("bp", bp) if bp else None
    return rows

