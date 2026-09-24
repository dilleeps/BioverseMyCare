"""Vital signs: measures, validation, storage, thresholds, alerts, trends and monitoring plans.

Shared by the vitals router, the reminders job, the pre-visit brief and the timeline. Readings live in
`observations` (category vital-signs / activity), coded from `bioverse.vitals_codes`.

Alerts are rules, never a model:
- Critical (HH/LL against the patient's thresholds): urgent notification and fixed safety copy for the
  patient, an urgent review item and a notification for the care team.
- Sustained: 3 of the last 5 readings of a measure out of range in the same direction within 7 days,
  or a weight gain of 2 kg or more within 3 days. Normal notification plus a routine review item.
- One open alert per patient, measure and kind. Further readings attach to it (reading_count), so a bad
  day is one item. After a clinician acknowledges, only readings after the acknowledgement count again.

The patient-facing copy below is fixed and non-diagnostic. It never says what a reading means for the
person's health; it says what to do now and that the care team has been told.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from bioverse import audit
from bioverse.agents.doctor_agent import care_team_practitioner
from bioverse.config import clinic_tz
from bioverse.notify import notify, patient_user
from bioverse.vitals_codes import CODES

AGENT = "vitals-rules"


def _rows(conn: Connection, sql: str, params: Any = None) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(sql, params).fetchall()


def _row(conn: Connection, sql: str, params: Any = None) -> dict | None:
    return conn.cursor(row_factory=dict_row).execute(sql, params).fetchone()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Measures ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit_label: str
    codes: tuple[str, ...]
    decimals: int = 0
    ranged: bool = True          # has reference ranges (steps, sleep and weight don't)


MEASURES: dict[str, Measure] = {m.key: m for m in [
    Measure("bp", "Blood pressure", "mmHg", ("bp_systolic", "bp_diastolic")),
    Measure("heart_rate", "Heart rate", "beats a minute", ("heart_rate",)),
    Measure("spo2", "Oxygen saturation", "%", ("spo2",)),
    Measure("temperature", "Temperature", "°C", ("temperature",), 1),
    Measure("glucose", "Blood glucose", "mg/dL", ("glucose", "glucose_fasting")),
    Measure("weight", "Weight", "kg", ("weight",), 1, ranged=False),
    Measure("steps", "Steps", "steps a day", ("steps",), ranged=False),
    Measure("sleep", "Sleep", "hours", ("sleep_hours",), 1, ranged=False),
]}
CODE_MEASURE = {c: m.key for m in MEASURES.values() for c in m.codes}
PLAN_MEASURES = ("bp", "heart_rate", "spo2", "temperature", "glucose", "weight")
GLUCOSE_CONTEXTS = ("fasting", "before_meal", "after_meal", "bedtime", "random")
CONTEXT_LABEL = {"fasting": "fasting", "before_meal": "before a meal", "after_meal": "after a meal",
                 "bedtime": "at bedtime", "random": "any time"}

# Physiologically possible values (canonical units). Outside these, it's a typo or a misread display.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "bp_systolic": (50, 260), "bp_diastolic": (30, 160), "heart_rate": (25, 250), "spo2": (50, 100),
    "temperature": (30, 45), "glucose": (15, 700), "glucose_fasting": (15, 700), "weight": (2, 350),
    "steps": (0, 100_000), "sleep_hours": (0, 24),
}
DECIMALS = {"temperature": 1, "weight": 1, "sleep_hours": 1}

# Thresholds a clinician can set per patient, and the extra weight-gain rule.
THRESHOLD_CODES = ("bp_systolic", "bp_diastolic", "heart_rate", "spo2", "temperature", "glucose", "glucose_fasting")
WEIGHT_GAIN = "weight_gain_3d"
WEIGHT_GAIN_DEFAULT_KG = 2.0
SUSTAINED_WINDOW = timedelta(days=7)
SUSTAINED_OF, SUSTAINED_NEEDED = 5, 3
RECENT = timedelta(hours=24)       # a critical reading older than this gets no "act now" message


class ReadingError(ValueError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


def _unit_factor(measure: str, unit: str | None) -> tuple[float, float]:
    """(scale, offset) that turns a value in `unit` into the canonical unit."""
    u = (unit or "").strip().lower().replace("°", "").replace(" ", "")
    if not u:
        return 1.0, 0.0
    if measure == "temperature":
        if u in ("c", "cel", "celsius", "degc"):
            return 1.0, 0.0
        if u in ("f", "fahrenheit", "degf", "[degf]"):
            return 5 / 9, -32 * 5 / 9
    elif measure == "weight":
        if u in ("kg", "kgs", "kilogram", "kilograms"):
            return 1.0, 0.0
        if u in ("lb", "lbs", "[lb_av]", "pound", "pounds"):
            return 0.45359237, 0.0
        if u in ("g",):
            return 0.001, 0.0
    elif measure == "glucose":
        if u in ("mg/dl",):
            return 1.0, 0.0
        if u.startswith("mmol"):
            return 18.016, 0.0
    elif measure == "bp":
        if u in ("mmhg", "mm[hg]"):
            return 1.0, 0.0
    elif measure in ("heart_rate",):
        if u in ("bpm", "/min", "count/min", "beats/min"):
            return 1.0, 0.0
    elif measure == "spo2":
        if u in ("%",):
            return 1.0, 0.0
    elif measure == "steps":
        if u in ("count", "steps", "/d"):
            return 1.0, 0.0
    elif measure == "sleep":
        if u in ("h", "hr", "hrs", "hour", "hours"):
            return 1.0, 0.0
        if u in ("min", "minutes"):
            return 1 / 60, 0.0
    raise ReadingError(f"We don't recognise the unit '{unit}' for {MEASURES[measure].label.lower()}.", "unit")


def _check(code: str, value: float | None, field: str) -> float:
    if value is None:
        raise ReadingError(f"Enter the {CODES[code].display.lower()}.", field)
    lo, hi = PLAUSIBLE[code]
    v = round(float(value), DECIMALS.get(code, 0))
    if not lo <= v <= hi:
        unit = MEASURES[CODE_MEASURE[code]].unit_label
        raise ReadingError(
            f"{CODES[code].display} {fmt(v)} isn't possible. Check the reading (expected {fmt(lo)}–{fmt(hi)} {unit}).",
            field,
        )
    return v


def fmt(v: float | None) -> str:
    if v is None:
        return "—"
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def normalize(measure: str, *, systolic: float | None = None, diastolic: float | None = None,
              pulse: float | None = None, value: float | None = None, unit: str | None = None,
              context: str | None = None) -> list[tuple[str, float]]:
    """Validate a reading and return [(vitals code, canonical value)]. Raises ReadingError."""
    if measure not in MEASURES:
        raise ReadingError("Choose what you measured.", "measure")
    if context is not None and measure != "glucose":
        raise ReadingError("Meal timing only applies to glucose readings.", "context")
    if context is not None and context not in GLUCOSE_CONTEXTS:
        raise ReadingError("Choose when you measured your glucose.", "context")
    out: list[tuple[str, float]] = []
    if measure == "bp":
        _unit_factor("bp", unit)
        s = _check("bp_systolic", systolic, "systolic")
        d = _check("bp_diastolic", diastolic, "diastolic")
        if s <= d:
            raise ReadingError("The top number (systolic) should be higher than the bottom number (diastolic). "
                               "Check the order.", "diastolic")
        out = [("bp_systolic", s), ("bp_diastolic", d)]
    else:
        if value is None:
            raise ReadingError(f"Enter your {MEASURES[measure].label.lower()}.", "value")
        scale, offset = _unit_factor(measure, unit)
        raw = float(value)
        if measure == "spo2" and 0 < raw <= 1 and (unit or "").strip() in ("", "%"):
            raw *= 100          # exports give oxygen saturation as a fraction
        canonical = raw * scale + offset
        if measure == "temperature" and not unit and 86 <= raw <= 113:
            raise ReadingError("That looks like °F. Choose °F as the unit, or enter the reading in °C.", "unit")
        code = {"glucose": "glucose_fasting" if context == "fasting" else "glucose",
                "sleep": "sleep_hours"}.get(measure, measure)
        out = [(code, _check(code, canonical, "value"))]
    if pulse is not None:
        if measure not in ("bp", "spo2"):
            raise ReadingError("Pulse is recorded with blood pressure or oxygen readings.", "pulse")
        out.append(("heart_rate", _check("heart_rate", pulse, "pulse")))
    return out


def check_time(taken_at: datetime | None, now: datetime, *, max_age_days: int = 365) -> datetime:
    if taken_at is None:
        return now
    if taken_at.tzinfo is None:
        taken_at = taken_at.replace(tzinfo=clinic_tz())
    if taken_at > now + timedelta(minutes=10):
        raise ReadingError("That time is in the future.", "taken_at")
    if taken_at < now - timedelta(days=max_age_days):
        raise ReadingError(f"Readings can go back {max_age_days} days at most.", "taken_at")
    return taken_at


# --- Thresholds -------------------------------------------------------------------------------------


def thresholds(conn: Connection, patient_id: str) -> dict[str, dict]:
    """Effective thresholds per code: clinician overrides on top of the vitals_codes defaults."""
    rules = {r["code"]: r for r in _rows(
        conn,
        """
        SELECT r.code, r.low, r.high, r.critical_low, r.critical_high, r.note, r.updated_at, pr.name AS set_by_name
        FROM vital_alert_rules r LEFT JOIN practitioners pr ON pr.id = r.set_by WHERE r.patient_id = %s
        """,
        (patient_id,),
    )}
    out: dict[str, dict] = {}
    for key in THRESHOLD_CODES:
        c = CODES[key]
        base = {"code": key, "display": c.display, "unit": c.unit, "low": c.low, "high": c.high,
                "critical_low": c.critical_low, "critical_high": c.critical_high, "source": "default",
                "note": None, "set_by": None, "updated_at": None}
        out[key] = _overlay(base, rules.get(key))
    base = {"code": WEIGHT_GAIN, "display": "Weight gain within 3 days", "unit": "kg", "low": None,
            "high": WEIGHT_GAIN_DEFAULT_KG, "critical_low": None, "critical_high": None, "source": "default",
            "note": None, "set_by": None, "updated_at": None}
    out[WEIGHT_GAIN] = _overlay(base, rules.get(WEIGHT_GAIN))
    return out


def _overlay(base: dict, rule: dict | None) -> dict:
    if rule is None:
        return base
    out = dict(base)
    for f in ("low", "high", "critical_low", "critical_high"):
        if rule[f] is not None:
            out[f] = float(rule[f])
    out.update(source="clinician", note=rule["note"], set_by=rule["set_by_name"], updated_at=rule["updated_at"])
    return out


def interpret(th: dict | None, value: float) -> str:
    """H / L / N, or HH / LL at or beyond the critical limits (same rule as vitals_codes.interpret)."""
    if not th:
        return "N"
    if th.get("critical_high") is not None and value >= th["critical_high"]:
        return "HH"
    if th.get("critical_low") is not None and value <= th["critical_low"]:
        return "LL"
    if th.get("high") is not None and value > th["high"]:
        return "H"
    if th.get("low") is not None and value < th["low"]:
        return "L"
    return "N"


def direction(interp: str) -> str | None:
    return "high" if interp in ("H", "HH") else "low" if interp in ("L", "LL") else None


# --- Storage ----------------------------------------------------------------------------------------


def store_reading(conn: Connection, *, patient_id: str, values: list[tuple[str, float]], taken_at: datetime,
                  source: str, context: str | None = None, note: str | None = None,
                  device: dict | None = None, th: dict | None = None) -> dict:
    """Insert one reading (one observation per value, grouped by panel_id when there are several)."""
    th = th if th is not None else thresholds(conn, patient_id)
    panel_id = str(uuid.uuid4()) if len(values) > 1 else None
    stored = []
    for code_key, value in values:
        c = CODES[code_key]
        t = th.get(code_key)
        interp = interpret(t, value)
        row = _row(
            conn,
            """
            INSERT INTO observations (patient_id, loinc_code, display, value, unit, ref_low, ref_high, interpretation,
                                      effective_at, category, source, device, device_id, panel_id, note,
                                      measurement_context)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text
            """,
            (patient_id, c.loinc, c.display, value, c.unit, t["low"] if t else None, t["high"] if t else None,
             interp, taken_at, c.category, source, device["label"] if device else None,
             device["id"] if device else None, panel_id, note, context),
        )
        stored.append({"id": row["id"], "code": code_key, "value": value, "interpretation": interp})
    measure = CODE_MEASURE[values[0][0]]
    return {"id": panel_id or stored[0]["id"], "panel_id": panel_id, "measure": measure, "taken_at": taken_at,
            "source": source, "context": context, "observations": stored}


def exists(conn: Connection, patient_id: str, code_key: str, taken_at: datetime, value: float) -> bool:
    """Import dedupe: same patient, code, time and value."""
    return _row(
        conn,
        "SELECT 1 FROM observations WHERE patient_id = %s AND loinc_code = %s AND effective_at = %s AND value = %s",
        (patient_id, CODES[code_key].loinc, taken_at, value),
    ) is not None


# --- Alerts -----------------------------------------------------------------------------------------

# Fixed, non-diagnostic safety copy for critical readings: (measure, direction) -> message.
SAFETY: dict[tuple[str, str], str] = {
    ("bp", "high"): (
        "Your blood pressure reading is very high. Sit quietly for 5 minutes and measure again. "
        "If you have chest pain, shortness of breath, back pain, weakness or numbness, vision changes or "
        "difficulty speaking, call 911 now."),
    ("bp", "low"): (
        "Your blood pressure reading is very low. Sit or lie down and measure again in 5 minutes. "
        "If you feel faint, confused, or have chest pain or shortness of breath, call 911 now."),
    ("spo2", "low"): (
        "Your oxygen reading is low. Warm your hands, sit still for a minute and measure again. "
        "If you are short of breath, have chest pain, feel confused, or your lips look blue or grey, call 911 now."),
    ("glucose", "low"): (
        "Your blood sugar reading is very low. If you can swallow safely, have 15 grams of fast-acting sugar, "
        "such as half a cup of juice, then check again in 15 minutes. If you are confused, very drowsy, or "
        "can't eat or drink, someone should call 911 now."),
    ("glucose", "high"): (
        "Your blood sugar reading is very high. Wash and dry your hands and check again. If you are vomiting, "
        "very thirsty, breathing fast, confused or very drowsy, call 911 now. Otherwise contact your care team today."),
    ("heart_rate", "high"): (
        "Your heart rate reading is very high. Sit quietly for 5 minutes and measure again. If you have chest "
        "pain, shortness of breath, or feel faint, call 911 now."),
    ("heart_rate", "low"): (
        "Your heart rate reading is very low. Sit quietly and measure again. If you feel faint, confused, or "
        "have chest pain or shortness of breath, call 911 now."),
    ("temperature", "high"): (
        "Your temperature reading is very high. Measure again in a few minutes. If you have a stiff neck, "
        "confusion, trouble breathing, or a new rash, call 911 now. Otherwise contact your care team today."),
    ("temperature", "low"): (
        "Your temperature reading is very low. Get warm and measure again. If you are confused, very drowsy "
        "or shivering uncontrollably, call 911 now."),
}
SAFETY_TITLE = "Check this reading again now"
SUSTAINED_PATIENT = (
    "Several of your recent readings were outside your range. Your care team has been told and will contact "
    "you if anything needs to change. Keep measuring as planned.")
WEIGHT_GAIN_PATIENT = (
    "Your weight has gone up quickly over the last few days. Your care team has been told. If you are more "
    "short of breath than usual or your ankles are more swollen, contact your care team today. If you are "
    "struggling to breathe, call 911.")
OUT_OF_RANGE_NOTE = (
    "This reading is outside your usual range. A single reading on its own is common; keep measuring as "
    "planned and your care team will see the pattern.")


def responsible_practitioner(conn: Connection, patient_id: str) -> str | None:
    """Who reviews home readings: the clinician running an active monitoring plan, else the care team
    clinician (active care plan, then most recent clinician; the rule the Doctor Agent uses)."""
    row = _row(
        conn,
        """
        SELECT practitioner_id::text AS id FROM vital_monitoring_plans
        WHERE patient_id = %s AND status = 'active' ORDER BY created_at DESC LIMIT 1
        """,
        (patient_id,),
    )
    if row:
        return row["id"]
    org = _row(conn, "SELECT organization_id::text AS org FROM patients WHERE id = %s", (patient_id,))
    return care_team_practitioner(conn, patient_id, org["org"]) if org else None


def _raise_alert(conn: Connection, *, patient_id: str, measure: str, kind: str, severity: str, title: str,
                 detail: str, observation_id: str | None, reading_at: datetime, patient_message: str,
                 notify_patient: bool) -> dict:
    """Open an alert, or attach this reading to the open one of the same measure and kind."""
    existing = _row(
        conn,
        """
        UPDATE vital_alerts SET reading_count = reading_count + 1, last_reading_at = greatest(last_reading_at, %s),
               observation_id = coalesce(%s, observation_id)
        WHERE patient_id = %s AND measure = %s AND kind = %s AND status = 'open'
        RETURNING id::text, kind, severity, title, reading_count, status
        """,
        (reading_at, observation_id, patient_id, measure, kind),
    )
    if existing:
        return {**existing, "new": False}

    practitioner_id = responsible_practitioner(conn, patient_id)
    alert = _row(
        conn,
        """
        INSERT INTO vital_alerts (patient_id, measure, kind, severity, title, detail, observation_id, last_reading_at,
                                  practitioner_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (patient_id, measure, kind) WHERE status = 'open' DO NOTHING
        RETURNING id::text, kind, severity, title, reading_count, status
        """,
        (patient_id, measure, kind, severity, title, detail, observation_id, reading_at, practitioner_id),
    )
    if alert is None:   # another request opened it a moment ago
        return {**_row(conn, "SELECT id::text, kind, severity, title, reading_count, status FROM vital_alerts "
                             "WHERE patient_id = %s AND measure = %s AND kind = %s AND status = 'open'",
                       (patient_id, measure, kind)), "new": False}

    link = f"/clinician/vitals/{patient_id}"
    item_id = None
    if practitioner_id:
        item_id = _row(
            conn,
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
            VALUES ('vital_alert', %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
            """,
            (patient_id, practitioner_id, alert["id"], f"Home vitals · {title}", detail,
             "urgent" if severity == "critical" else "routine", link),
        )["id"]
        conn.execute("UPDATE vital_alerts SET review_item_id = %s WHERE id = %s", (item_id, alert["id"]))
        clinician = _row(conn, "SELECT user_id::text AS uid FROM practitioners WHERE id = %s", (practitioner_id,))
        name = _row(conn, "SELECT name FROM patients WHERE id = %s", (patient_id,))["name"]
        if clinician and clinician["uid"]:
            notify(conn, user_id=clinician["uid"], kind="vital_alert", title="Home vitals alert for a patient",
                   body=f"{name}: {title}", link=link, patient_id=patient_id,
                   priority="high" if severity == "critical" else "normal",
                   dedupe_key=f"vitals:alert:{alert['id']}", created_by=AGENT)
    if notify_patient:
        uid = patient_user(conn, patient_id)
        if uid:
            notify(conn, user_id=uid, kind="vital_alert",
                   title=SAFETY_TITLE if severity == "critical" else "Your care team is reviewing your readings",
                   body=patient_message, link="/vitals", patient_id=patient_id,
                   priority="urgent" if severity == "critical" else "normal",
                   dedupe_key=f"vitals:alert:{alert['id']}", created_by=AGENT)
    audit.record(conn, action="vital_alert_raised", entity_type="vital_alert", entity_id=alert["id"], agent=AGENT,
                 patient_id=patient_id, detail={"measure": measure, "kind": kind, "severity": severity,
                                                "review_item_id": item_id, "practitioner_id": practitioner_id})
    return {**alert, "new": True}


def _ack_cutoff(conn: Connection, patient_id: str, measure: str, kind: str) -> datetime | None:
    row = _row(
        conn,
        """
        SELECT max(acknowledged_at) AS at FROM vital_alerts
        WHERE patient_id = %s AND measure = %s AND kind = %s AND status = 'acknowledged'
        """,
        (patient_id, measure, kind),
    )
    return row["at"] if row else None


def recent_readings(conn: Connection, patient_id: str, measure: str, since: datetime,
                    until: datetime | None = None) -> list[dict]:
    """Readings of a measure, oldest first, grouped into one dict per reading (a BP panel is one reading).

    Each: {id, at, values: {code: value}, source, context, device, note, obs_ids}.
    """
    m = MEASURES[measure]
    codes = list(m.codes) + (["heart_rate"] if measure in ("bp", "spo2") else [])
    rows = _rows(
        conn,
        """
        SELECT id::text, loinc_code, value, effective_at, source, panel_id::text, measurement_context, device, note
        FROM observations
        WHERE patient_id = %s AND category IN ('vital-signs', 'activity') AND loinc_code = ANY(%s)
          AND effective_at >= %s AND (%s::timestamptz IS NULL OR effective_at <= %s::timestamptz)
        ORDER BY effective_at, id
        """,
        (patient_id, [CODES[c].loinc for c in codes], since, until, until),
    )
    by_loinc = {CODES[c].loinc: c for c in codes}
    grouped: dict[str, dict] = {}
    for r in rows:
        code = by_loinc[r["loinc_code"]]
        key = r["panel_id"] or r["id"]
        if code == "heart_rate" and measure != "heart_rate" and not r["panel_id"]:
            continue    # a standalone heart rate isn't part of a BP or oxygen reading
        g = grouped.setdefault(key, {"id": key, "at": r["effective_at"], "values": {}, "source": r["source"],
                                     "context": r["measurement_context"], "device": r["device"], "note": r["note"],
                                     "obs_ids": []})
        g["values"][code] = float(r["value"])
        g["obs_ids"].append(r["id"])
    out = [g for g in grouped.values() if any(c in g["values"] for c in m.codes)]
    out.sort(key=lambda g: g["at"])
    return out


def reading_direction(measure: str, values: dict[str, float], th: dict) -> tuple[str | None, bool]:
    """(high/low/None, critical?) for one grouped reading against the thresholds."""
    interps = [interpret(th.get(c), v) for c, v in values.items() if c in MEASURES[measure].codes]
    if not interps:
        return None, False
    crit = [i for i in interps if i in ("HH", "LL")]
    if crit:
        return direction(crit[0]), True
    for i in interps:
        if i in ("H", "L"):
            return direction(i), False
    return None, False


def label_values(measure: str, values: dict[str, float]) -> str:
    if measure == "bp":
        return f"{fmt(values.get('bp_systolic'))}/{fmt(values.get('bp_diastolic'))}"
    v = next((values[c] for c in MEASURES[measure].codes if c in values), None)
    return fmt(v)


def evaluate(conn: Connection, patient_id: str, reading: dict, *, now: datetime | None = None,
             notify_patient: bool = True, th: dict | None = None) -> dict:
    """Run the alert rules for a new reading. Returns {alerts: [...], safety: {...} | None, note: str | None}."""
    now = now or utcnow()
    th = th if th is not None else thresholds(conn, patient_id)
    measure = reading["measure"]
    m = MEASURES[measure]
    values = {o["code"]: o["value"] for o in reading["observations"]}
    alerts: list[dict] = []
    safety = None
    note = None
    recent = reading["taken_at"] >= now - RECENT

    dirn, critical = reading_direction(measure, values, th)
    if measure in ("bp", "spo2") and "heart_rate" in values:
        hr_interp = interpret(th.get("heart_rate"), values["heart_rate"])
        if hr_interp in ("HH", "LL"):
            alerts.append(_critical(conn, patient_id, "heart_rate", direction(hr_interp),
                                    {"heart_rate": values["heart_rate"]}, reading, recent, notify_patient))
            safety = safety or {"level": "critical", "title": SAFETY_TITLE,
                                "message": SAFETY[("heart_rate", direction(hr_interp))], "call": "911"}
    if critical and dirn and (measure, dirn) in SAFETY:
        alerts.insert(0, _critical(conn, patient_id, measure, dirn, values, reading, recent, notify_patient))
        if recent:
            safety = {"level": "critical", "title": SAFETY_TITLE, "message": SAFETY[(measure, dirn)], "call": "911"}
    elif dirn and m.ranged:
        note = OUT_OF_RANGE_NOTE
    if safety and not recent:
        safety = None

    if dirn and measure in ("bp", "glucose", "spo2", "heart_rate", "temperature"):
        a = _sustained(conn, patient_id, measure, dirn, th, now, notify_patient)
        if a:
            alerts.append(a)
    if measure == "weight":
        a = _weight_gain(conn, patient_id, reading, th, notify_patient)
        if a:
            alerts.append(a)
    return {"alerts": alerts, "safety": safety, "note": note}


def _critical(conn, patient_id, measure, dirn, values, reading, recent, notify_patient) -> dict:
    label = MEASURES[measure].label
    shown = label_values(measure, values) if measure != "heart_rate" else fmt(values["heart_rate"])
    at = reading["taken_at"].astimezone(clinic_tz())
    title = f"{label} critically {dirn} · {shown} {MEASURES[measure].unit_label}"
    detail = (f"Home reading {shown} {MEASURES[measure].unit_label} at {at:%d %b %H:%M} "
              f"({reading['source']}). Patient was shown fixed guidance to recheck and call 911 if symptomatic.")
    if not recent:
        detail = (f"Home reading {shown} {MEASURES[measure].unit_label} from {at:%d %b %H:%M}, entered later "
                  f"({reading['source']}). No real-time guidance was shown because the reading is over a day old.")
    return _raise_alert(conn, patient_id=patient_id, measure=measure, kind=f"critical_{dirn}", severity="critical",
                        title=title, detail=detail, observation_id=reading["observations"][0]["id"],
                        reading_at=reading["taken_at"], patient_message=SAFETY[(measure, dirn)],
                        notify_patient=notify_patient and recent)


def _sustained(conn, patient_id, measure, dirn, th, now, notify_patient) -> dict | None:
    kind = f"sustained_{dirn}"
    since = now - SUSTAINED_WINDOW
    cutoff = _ack_cutoff(conn, patient_id, measure, kind)
    if cutoff and cutoff > since:
        since = cutoff
    readings = recent_readings(conn, patient_id, measure, since, now)[-SUSTAINED_OF:]
    if len(readings) < SUSTAINED_NEEDED:
        return None
    hits = [r for r in readings if reading_direction(measure, r["values"], th)[0] == dirn]
    if len(hits) < SUSTAINED_NEEDED:
        return None
    label = MEASURES[measure].label
    unit = MEASURES[measure].unit_label
    shown = ", ".join(label_values(measure, r["values"]) for r in hits[-5:])
    avg = average(measure, readings)
    title = f"{label} {dirn} on {len(hits)} of the last {len(readings)} readings"
    detail = (f"{len(hits)} of the last {len(readings)} home {label.lower()} readings (7 days) were {dirn}: "
              f"{shown} {unit}. Average of those {len(readings)}: {avg} {unit}.")
    return _raise_alert(conn, patient_id=patient_id, measure=measure, kind=kind, severity="warning", title=title,
                        detail=detail, observation_id=hits[-1]["obs_ids"][0], reading_at=hits[-1]["at"],
                        patient_message=SUSTAINED_PATIENT, notify_patient=notify_patient)


def _weight_gain(conn, patient_id, reading, th, notify_patient) -> dict | None:
    limit = th[WEIGHT_GAIN]["high"] or WEIGHT_GAIN_DEFAULT_KG
    at = reading["taken_at"]
    since = at - timedelta(days=3)
    cutoff = _ack_cutoff(conn, patient_id, "weight", "weight_gain")
    if cutoff and cutoff > since:
        since = cutoff
    earlier = [r for r in recent_readings(conn, patient_id, "weight", since, at) if r["at"] < at]
    if not earlier:
        return None
    now_kg = reading["observations"][0]["value"]
    low = min(earlier, key=lambda r: r["values"]["weight"])
    gain = round(now_kg - low["values"]["weight"], 1)
    if gain < limit:
        return None
    title = f"Weight up {fmt(gain)} kg in 3 days"
    detail = (f"Home weight {fmt(low['values']['weight'])} kg on {low['at'].astimezone(clinic_tz()):%d %b} to "
              f"{fmt(now_kg)} kg on {at.astimezone(clinic_tz()):%d %b} (threshold {fmt(limit)} kg in 3 days).")
    return _raise_alert(conn, patient_id=patient_id, measure="weight", kind="weight_gain", severity="warning",
                        title=title, detail=detail, observation_id=reading["observations"][0]["id"], reading_at=at,
                        patient_message=WEIGHT_GAIN_PATIENT, notify_patient=notify_patient)


def acknowledge(conn: Connection, *, alert_id: str, user, note: str | None) -> dict:
    alert = _row(conn, "SELECT id::text, patient_id::text, status, review_item_id::text FROM vital_alerts "
                       "WHERE id::text = %s FOR UPDATE", (alert_id,))
    if alert is None:
        raise LookupError("alert")
    if alert["status"] != "open":
        raise ValueError("already acknowledged")
    conn.execute(
        """
        UPDATE vital_alerts SET status = 'acknowledged', acknowledged_by = %s, acknowledged_at = now(), ack_note = %s
        WHERE id = %s
        """,
        (user.id, note, alert_id),
    )
    if alert["review_item_id"]:
        conn.execute(
            """
            UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now()
            WHERE id = %s AND status = 'open'
            """,
            ("acknowledge" + (f": {note}" if note else ""), user.id, alert["review_item_id"]),
        )
    audit.record(conn, action="vital_alert_acknowledged", entity_type="vital_alert", entity_id=alert_id, actor=user,
                 patient_id=alert["patient_id"], detail={"review_item_id": alert["review_item_id"], "note": bool(note)})
    return alert


ALERT_COLS = """
    a.id::text, a.patient_id::text, a.measure, a.kind, a.severity, a.title, a.detail, a.reading_count,
    a.last_reading_at, a.status, a.created_at, a.acknowledged_at, a.ack_note, a.review_item_id::text,
    u.display_name AS acknowledged_by_name, pr.name AS practitioner_name
"""


def alerts_for(conn: Connection, patient_id: str, *, status: str | None = None, days: int = 90) -> list[dict]:
    return _rows(
        conn,
        f"""
        SELECT {ALERT_COLS}
        FROM vital_alerts a LEFT JOIN users u ON u.id = a.acknowledged_by
        LEFT JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.patient_id = %s AND (%s::text IS NULL OR a.status = %s)
          AND (a.status = 'open' OR a.created_at > now() - make_interval(days => %s))
        ORDER BY (a.status = 'open') DESC, (a.severity = 'critical') DESC, a.created_at DESC
        """,
        (patient_id, status, status, days),
    )


# --- Trends -----------------------------------------------------------------------------------------


def _round(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)      # half up, as people round


def average(measure: str, readings: list[dict]) -> str:
    if not readings:
        return "—"
    if measure == "bp":
        s = [r["values"]["bp_systolic"] for r in readings if "bp_systolic" in r["values"]]
        d = [r["values"]["bp_diastolic"] for r in readings if "bp_diastolic" in r["values"]]
        return f"{_round(sum(s) / len(s))}/{_round(sum(d) / len(d))}"
    vals = [primary(measure, r) for r in readings]
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    avg = sum(vals) / len(vals)
    return fmt(round(avg, MEASURES[measure].decimals))


def primary(measure: str, r: dict) -> float | None:
    return next((r["values"][c] for c in MEASURES[measure].codes if c in r["values"]), None)


def daily_steps(readings: list[dict]) -> list[dict]:
    """Steps are daily totals; several sources may report the same day. Keep the highest per day."""
    tz = clinic_tz()
    best: dict[date, dict] = {}
    for r in readings:
        d = r["at"].astimezone(tz).date()
        if d not in best or r["values"]["steps"] > best[d]["values"]["steps"]:
            best[d] = r
    return [best[d] for d in sorted(best)]


def reading_out(measure: str, r: dict, th: dict, own: bool) -> dict:
    dirn, crit = reading_direction(measure, r["values"], th)
    out = {"id": r["id"], "at": r["at"], "source": r["source"], "context": r["context"], "device": r["device"],
           "note": r["note"], "status": ("critical_" if crit else "") + dirn if dirn else "in_range",
           "deletable": own and r["source"] in ("manual", "photo")}
    if measure == "bp":
        out.update(systolic=r["values"].get("bp_systolic"), diastolic=r["values"].get("bp_diastolic"),
                   pulse=r["values"].get("heart_rate"))
    else:
        out["value"] = primary(measure, r)
        if measure == "spo2":
            out["pulse"] = r["values"].get("heart_rate")
        if measure == "glucose" and "glucose_fasting" in r["values"]:
            out["context"] = "fasting"
    if not MEASURES[measure].ranged:
        out["status"] = None
    return out


def stats(measure: str, readings: list[dict], th: dict) -> dict:
    tz = clinic_tz()
    n = len(readings)
    out: dict[str, Any] = {"count": n, "average": average(measure, readings) if n else None,
                           "in_range_pct": None, "high": 0, "low": 0, "critical": 0}
    if n and MEASURES[measure].ranged:
        for r in readings:
            dirn, crit = reading_direction(measure, r["values"], th)
            out["high"] += dirn == "high"
            out["low"] += dirn == "low"
            out["critical"] += crit
        out["in_range_pct"] = round(100 * (n - out["high"] - out["low"]) / n)
    vals = [primary(measure, r) for r in readings]
    vals = [v for v in vals if v is not None]
    if vals:
        out["min"], out["max"] = fmt(min(vals)), fmt(max(vals))
    if measure == "weight" and len(vals) >= 2:
        out["change"] = round(vals[-1] - vals[0], 1)
    if measure == "bp":
        am = [r for r in readings if 4 <= r["at"].astimezone(tz).hour < 12]
        pm = [r for r in readings if 16 <= r["at"].astimezone(tz).hour < 24]
        out["morning"] = {"average": average("bp", am) if am else None, "count": len(am)}
        out["evening"] = {"average": average("bp", pm) if pm else None, "count": len(pm)}
    return out


def range_text(measure: str, th: dict) -> dict:
    """Plain-language explanation of the ranges. Describes the numbers; never says what they mean for you."""
    def span(code):
        t = th[code]
        return f"{fmt(t['low'])}–{fmt(t['high'])}" if t["low"] is not None else f"up to {fmt(t['high'])}"

    by_clinician = any(th[c]["source"] == "clinician" for c in MEASURES[measure].codes if c in th)
    who = "set for you by your care team" if by_clinician else "general ranges for adults"
    common = ("One reading outside the range is common and is not a diagnosis. Your care team looks at the "
              "pattern over several days. If you are unsure what your numbers mean for you, ask your care team.")
    texts = {
        "bp": (f"Blood pressure has two numbers. The top number (systolic) is the pressure in your arteries when "
               f"your heart beats; the bottom number (diastolic) is the pressure between beats. The range shown is "
               f"{span('bp_systolic')} over {span('bp_diastolic')} mmHg ({who}). Caffeine, exercise, talking, stress "
               f"or a full bladder can raise a reading, so sit quietly for 5 minutes first, with your arm supported "
               f"at heart level. " + common),
        "heart_rate": (f"Heart rate is how many times your heart beats in a minute. The range shown for a resting "
                       f"reading is {span('heart_rate')} beats a minute ({who}). Activity, caffeine, fever and some "
                       f"medicines change it. " + common),
        "spo2": (f"Oxygen saturation is the share of your blood's oxygen-carrying capacity that is in use. The range "
                 f"shown is {span('spo2')}% ({who}). Cold fingers, nail polish and movement can give a falsely low "
                 f"reading, so warm your hands and keep still. " + common),
        "temperature": (f"The range shown is {span('temperature')} °C ({who}). Temperature is usually a little "
                        f"lower in the morning and higher in the evening, and depends on where you measure. " + common),
        "glucose": (f"Blood glucose is the sugar in your blood, which changes through the day with food, activity "
                    f"and medicines. The range shown is {span('glucose_fasting')} mg/dL when fasting and "
                    f"{span('glucose')} mg/dL at other times ({who}). Recording when you measured (fasting, before "
                    f"or after a meal, bedtime) helps your care team read the pattern. " + common),
        "weight": ("Weight changes a little from day to day with food, fluids and time of day. Weigh yourself at "
                   "the same time each day, after using the toilet and before breakfast, in similar clothes. "
                   "Your care team may ask you to report a quick gain over a few days."),
        "steps": "Steps come from your phone or wearable. Any movement counts, and small increases add up.",
        "sleep": "Sleep hours come from your wearable or what you log. Most adults need 7 or more hours a night.",
    }
    return {"text": texts[measure], "source": "clinician" if by_clinician else "default"}


def series(conn: Connection, patient_id: str, measure: str, days: int, *, own: bool, now: datetime | None = None) -> dict:
    now = now or utcnow()
    th = thresholds(conn, patient_id)
    readings = recent_readings(conn, patient_id, measure, now - timedelta(days=days), now)
    if measure == "steps":
        readings = daily_steps(readings)
    ranges = {c: {k: th[c][k] for k in ("low", "high", "critical_low", "critical_high")}
              for c in MEASURES[measure].codes if c in th}
    return {
        "measure": measure, "label": MEASURES[measure].label, "unit": MEASURES[measure].unit_label, "days": days,
        "ranges": ranges, "stats": stats(measure, readings, th),
        "readings": [reading_out(measure, r, th, own) for r in reversed(readings)],
        "explanation": range_text(measure, th),
    }


def tiles(conn: Connection, patient_id: str, *, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    th = thresholds(conn, patient_id)
    out = []
    for key, m in MEASURES.items():
        readings = recent_readings(conn, patient_id, key, now - timedelta(days=90), now)
        if key == "steps":
            readings = daily_steps(readings)
        week = [r for r in readings if r["at"] >= now - timedelta(days=7)]
        spark = [r for r in readings if r["at"] >= now - timedelta(days=14)]
        latest = reading_out(key, readings[-1], th, False) if readings else None
        out.append({
            "measure": key, "label": m.label, "unit": m.unit_label, "latest": latest,
            "week": {"count": len(week), "average": average(key, week) if week else None},
            "spark": [primary(key, r) for r in spark],
        })
    return out


# --- Monitoring plans -------------------------------------------------------------------------------

WINDOW_BEFORE = timedelta(hours=1)
WINDOW_AFTER = timedelta(hours=3)
MIN_GAP_HOURS = 2


def plan_label(plan: dict) -> str:
    n = len(plan["times"])
    freq = {1: "once daily", 2: "twice daily", 3: "three times daily", 4: "four times daily"}.get(n, f"{n} times daily")
    days = (plan["end_on"] - plan["start_on"]).days + 1
    return f"{MEASURES[plan['measure']].label} {freq} for {days} days"


def slots(plan: dict, day: date) -> list[tuple[datetime, datetime, datetime]]:
    """(window start, due time, window end) for each plan time on a clinic-local day. Windows never overlap."""
    tz = clinic_tz()
    due = [datetime.combine(day, t, tzinfo=tz) for t in sorted(plan["times"])]
    out = []
    for i, d in enumerate(due):
        end = d + WINDOW_AFTER
        if i + 1 < len(due):
            end = min(end, due[i + 1] - WINDOW_BEFORE)
        out.append((d - WINDOW_BEFORE, d, end))
    return out


def _plan_codes(measure: str) -> list[str]:
    codes = MEASURES[measure].codes
    return [CODES[codes[0]].loinc] if measure == "bp" else [CODES[c].loinc for c in codes]


def reading_times(conn: Connection, patient_id: str, measure: str, since: datetime, until: datetime) -> list[datetime]:
    return [r["effective_at"] for r in _rows(
        conn,
        """
        SELECT effective_at FROM observations
        WHERE patient_id = %s AND category = 'vital-signs' AND loinc_code = ANY(%s)
          AND effective_at >= %s AND effective_at < %s
        ORDER BY effective_at
        """,
        (patient_id, _plan_codes(measure), since, until),
    )]


def adherence(conn: Connection, plan: dict, now: datetime | None = None) -> dict:
    """Plan slots so far: done (a reading in the window), missed (window closed), due, upcoming."""
    now = now or utcnow()
    today = now.astimezone(clinic_tz()).date()
    last = min(plan["end_on"], today)
    first_start = datetime.combine(plan["start_on"], time(0), tzinfo=clinic_tz()) - WINDOW_BEFORE
    times = reading_times(conn, plan["patient_id"], plan["measure"], first_start,
                          datetime.combine(last + timedelta(days=1), time(0), tzinfo=clinic_tz()) + WINDOW_AFTER)
    days, done, expected = [], 0, 0
    d = plan["start_on"]
    while d <= last:
        row = []
        for start, due, end in slots(plan, d):
            hit = any(start <= t < end for t in times)
            if hit:
                st = "done"
            elif end <= now:
                st = "missed"
            elif due <= now:
                st = "due"
            else:
                st = "upcoming"
            if st in ("done", "missed"):
                expected += 1
                done += st == "done"
            row.append({"due": due, "status": st})
        days.append({"date": d, "slots": row})
        d += timedelta(days=1)
    return {"done": done, "expected": expected, "pct": round(100 * done / expected) if expected else None,
            "days": days[-14:], "today": days[-1]["slots"] if days and days[-1]["date"] == today else []}


PLAN_COLS = """
    v.id::text, v.patient_id::text, v.practitioner_id::text, v.measure, v.times, v.start_on, v.end_on,
    v.instructions, v.status, v.created_at, v.stopped_at, pr.name AS practitioner_name
"""


def plans_for(conn: Connection, patient_id: str, now: datetime | None = None, include_ended: bool = True) -> list[dict]:
    rows = _rows(
        conn,
        f"""
        SELECT {PLAN_COLS} FROM vital_monitoring_plans v JOIN practitioners pr ON pr.id = v.practitioner_id
        WHERE v.patient_id = %s AND (%s OR v.status = 'active')
        ORDER BY (v.status = 'active') DESC, v.created_at DESC LIMIT 10
        """,
        (patient_id, include_ended),
    )
    for p in rows:
        p["label"] = plan_label(p)
        p["times"] = [t.strftime("%H:%M") for t in sorted(p["times"])]
        p["adherence"] = adherence(conn, {**p, "times": [time.fromisoformat(t) for t in p["times"]]}, now)
    return rows


# --- Devices ----------------------------------------------------------------------------------------

DEVICE_KINDS = {"bp_cuff": "Blood pressure cuff", "glucometer": "Glucose meter", "scale": "Scale",
                "pulse_oximeter": "Pulse oximeter", "thermometer": "Thermometer", "wearable": "Wearable"}
INTEGRATIONS = {"bluetooth": "Bluetooth", "apple_health": "Apple Health", "health_connect": "Health Connect",
                "fitbit": "Fitbit", "manual_import": "File import"}


def device_label(d: dict) -> str:
    name = " ".join(x for x in (d.get("vendor"), d.get("model")) if x)
    return name or DEVICE_KINDS[d["kind"]]


def devices_for(conn: Connection, patient_id: str) -> list[dict]:
    rows = _rows(
        conn,
        """
        SELECT d.id::text, d.kind, d.vendor, d.model, d.integration, d.serial, d.status, d.simulated, d.last_sync,
               d.created_at, d.disconnected_at,
               (SELECT count(*) FROM observations o WHERE o.device_id = d.id) AS readings
        FROM devices d WHERE d.patient_id = %s
        ORDER BY (d.status = 'connected') DESC, d.created_at DESC
        """,
        (patient_id,),
    )
    for d in rows:
        d["label"] = device_label(d)
        d["kind_label"] = DEVICE_KINDS[d["kind"]]
        d["integration_label"] = INTEGRATIONS[d["integration"]]
    return rows


# --- Brief ------------------------------------------------------------------------------------------


def brief_bullets(conn: Connection, patient_id: str, practitioner_id: str, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    th = thresholds(conn, patient_id)
    out: list[dict] = []
    since = now - timedelta(days=14)
    bp = recent_readings(conn, patient_id, "bp", since, now)
    critical = _row(
        conn,
        """
        SELECT count(*) AS n FROM vital_alerts
        WHERE patient_id = %s AND measure = 'bp' AND severity = 'critical' AND created_at >= %s
        """,
        (patient_id, since),
    )["n"]
    if bp:
        s = stats("bp", bp, th)
        text = (f"Home BP averaged {s['average']} over 14 days; {s['high']} of {s['count']} readings high"
                + (f"; {s['low']} low" if s["low"] else "")
                + (f"; {critical} critical alert{'s' if critical != 1 else ''}" if critical else "") + ".")
        out.append({"text": text, "source": {"type": "observation", "id": bp[-1]["obs_ids"][0]},
                    "flag": "Home BP above range" if s["high"] * 2 > s["count"] else None})
    weight = recent_readings(conn, patient_id, "weight", since, now)
    if len(weight) >= 2:
        change = weight[-1]["values"]["weight"] - weight[0]["values"]["weight"]
        out.append({"text": f"Home weight {fmt(weight[-1]['values']['weight'])} kg; {change:+.1f} kg over 14 days.",
                    "source": {"type": "observation", "id": weight[-1]["obs_ids"][0]}, "flag": None})
    for a in alerts_for(conn, patient_id, status="open"):
        out.append({"text": f"Open home vitals alert: {a['title']} (since {a['created_at'].astimezone(clinic_tz()):%d %b}"
                            + (f", {a['reading_count']} readings" if a["reading_count"] > 1 else "") + ").",
                    "source": {"type": "vital_alert", "id": a["id"]},
                    "flag": "Critical home reading" if a["severity"] == "critical" else "Open home vitals alert"})
    for p in plans_for(conn, patient_id, now, include_ended=False):
        a = p["adherence"]
        if a["expected"]:
            who = "your" if p["practitioner_id"] == practitioner_id else f"{p['practitioner_name']}'s"
            out.append({"text": f"Home monitoring ({who} plan): {p['label'].lower()}, ends {p['end_on']:%d %b}; "
                                f"{a['done']} of {a['expected']} readings logged ({a['pct']}%).",
                        "source": {"type": "vital_monitoring_plan", "id": p["id"]},
                        "flag": "Low home monitoring adherence" if a["pct"] is not None and a["pct"] < 60 else None})
    return out
