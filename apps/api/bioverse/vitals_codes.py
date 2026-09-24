"""The shared vocabulary for vital signs and patient-generated data.

Every module that writes or reads vitals, activity or weight in `observations` uses these codes, so a
reading from a Bluetooth cuff, a meter photo, an Apple Health import or a typed entry all mean the same
thing. Ranges are general adult reference ranges for display and alerting in this demo; clinical alert
thresholds are clinician-owned in production.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VitalCode:
    key: str            # short id used in APIs
    loinc: str
    display: str
    unit: str           # UCUM
    category: str       # observations.category
    low: float | None = None
    high: float | None = None
    critical_low: float | None = None
    critical_high: float | None = None


CODES: dict[str, VitalCode] = {c.key: c for c in [
    VitalCode("bp_systolic", "8480-6", "Systolic blood pressure", "mm[Hg]", "vital-signs", 90, 129, 70, 180),
    VitalCode("bp_diastolic", "8462-4", "Diastolic blood pressure", "mm[Hg]", "vital-signs", 60, 79, 40, 120),
    VitalCode("heart_rate", "8867-4", "Heart rate", "/min", "vital-signs", 50, 100, 40, 130),
    VitalCode("spo2", "59408-5", "Oxygen saturation", "%", "vital-signs", 95, 100, 90, None),
    VitalCode("temperature", "8310-5", "Body temperature", "Cel", "vital-signs", 36.1, 37.5, 35.0, 39.5),
    VitalCode("resp_rate", "9279-1", "Respiratory rate", "/min", "vital-signs", 12, 20, 8, 30),
    VitalCode("glucose", "2339-0", "Blood glucose", "mg/dL", "vital-signs", 70, 140, 54, 300),
    VitalCode("glucose_fasting", "1558-6", "Fasting blood glucose", "mg/dL", "vital-signs", 70, 99, 54, 250),
    VitalCode("weight", "29463-7", "Body weight", "kg", "vital-signs"),
    VitalCode("height", "8302-2", "Body height", "cm", "vital-signs"),
    VitalCode("bmi", "39156-5", "Body mass index", "kg/m2", "vital-signs", 18.5, 24.9),
    VitalCode("steps", "41950-7", "Steps in 24 hours", "/d", "activity"),
    VitalCode("active_minutes", "55411-3", "Exercise duration", "min", "activity"),
    VitalCode("sleep_hours", "93832-4", "Sleep duration", "h", "activity"),
    VitalCode("calories_in", "9052-2", "Calorie intake", "kcal", "activity"),
]}

BY_LOINC: dict[str, VitalCode] = {c.loinc: c for c in CODES.values()}


def interpret(code: VitalCode, value: float) -> str:
    """H / L / N, or HH / LL beyond the critical limits."""
    if code.critical_high is not None and value >= code.critical_high:
        return "HH"
    if code.critical_low is not None and value <= code.critical_low:
        return "LL"
    if code.high is not None and value > code.high:
        return "H"
    if code.low is not None and value < code.low:
        return "L"
    return "N"
