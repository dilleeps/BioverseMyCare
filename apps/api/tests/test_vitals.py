"""Vitals and devices: logging, validation, trends, imports, meter photos, alerts, plans, reminders, access, brief."""

import base64
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.agents import llm
from bioverse.agents.triage import rules_triage
from bioverse.config import clinic_tz
from bioverse.db.seed import DR_OKAFOR, P_HADDAD, U_FRONTDESK, U_MAYA, U_PARK, seed
from bioverse.db.seeds.s110_vitals import ALERT_MAYA_BP, DEV_CUFF, PLAN_MAYA_BP, REVIEW_MAYA_BP
from bioverse.jobs import run_job
from bioverse.routers import vitals_core as core
from bioverse.routers import vitals_import as imp
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK, as_user

FRONTDESK = as_user(U_FRONTDESK)
TZ = clinic_tz()


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def log(client, headers=PARK, expect=201, **body):
    r = client.post("/api/vitals/readings", headers=headers, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def open_alerts(patient_id):
    with db() as conn:
        return conn.execute(
            "SELECT id::text, measure, kind, severity, reading_count, review_item_id::text, practitioner_id::text "
            "FROM vital_alerts WHERE patient_id = %s AND status = 'open' ORDER BY created_at",
            (patient_id,),
        ).fetchall()


# --- Seed ---------------------------------------------------------------------------------------------


def test_seeded_story_and_idempotent_reseed(client):
    s = client.get("/api/vitals/summary", headers=MAYA).json()
    tiles = {t["measure"]: t for t in s["tiles"]}
    assert tiles["bp"]["latest"]["systolic"] and tiles["bp"]["week"]["count"] >= 10
    assert tiles["weight"]["latest"] and tiles["steps"]["latest"] and tiles["spo2"]["latest"] is None
    assert {d["kind"] for d in s["devices"]} == {"bp_cuff", "scale"} and all(d["simulated"] for d in s["devices"])
    plan = next(p for p in s["plans"] if p["id"] == PLAN_MAYA_BP)
    assert plan["label"] == "Blood pressure twice daily for 14 days" and plan["times"] == ["08:00", "20:00"]
    assert plan["adherence"]["expected"] >= 3 and plan["adherence"]["done"] < plan["adherence"]["expected"]
    alert = next(a for a in s["alerts"] if a["id"] == ALERT_MAYA_BP)
    assert alert["kind"] == "sustained_high" and alert["status"] == "open"
    assert "detail" not in alert, "clinician detail stays off the patient's screen"

    with db() as conn:
        before = conn.execute("SELECT count(*) AS n FROM observations WHERE patient_id = %s", (P_MAYA,)).fetchone()["n"]
    seed(DB)
    with db() as conn:
        after = conn.execute("SELECT count(*) AS n FROM observations WHERE patient_id = %s", (P_MAYA,)).fetchone()["n"]
        item = conn.execute("SELECT kind, practitioner_id::text, link FROM review_items WHERE id = %s",
                            (REVIEW_MAYA_BP,)).fetchone()
    assert before == after
    assert item == {"kind": "vital_alert", "practitioner_id": DR_OKAFOR, "link": f"/clinician/vitals/{P_MAYA}"}


# --- Logging and validation -----------------------------------------------------------------------------


def test_log_bp_with_pulse_is_one_panel(client):
    r = log(client, measure="bp", systolic=118, diastolic=76, pulse=64, note="after coffee")
    assert r["reading"]["status"] == "in_range" and r["safety"] is None and r["alerts"] == []
    with db() as conn:
        rows = conn.execute(
            "SELECT loinc_code, value, category, source, panel_id::text, note FROM observations WHERE patient_id = %s "
            "ORDER BY loinc_code", (P_PARK,)).fetchall()
        audited = conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'vital_logged' AND patient_id = %s",
                               (P_PARK,)).fetchone()["n"]
    vitals = [r for r in rows if r["category"] == "vital-signs"]
    assert {r["loinc_code"] for r in vitals} == {"8480-6", "8462-4", "8867-4"}
    assert len({r["panel_id"] for r in vitals}) == 1 and vitals[0]["panel_id"] is not None
    assert all(r["source"] == "manual" for r in vitals) and audited == 1
    hr = client.get("/api/vitals/measures/heart_rate?days=7", headers=PARK).json()
    assert hr["readings"][0]["value"] == 64


@pytest.mark.parametrize("body, field", [
    ({"measure": "bp", "systolic": 1200, "diastolic": 80}, "systolic"),
    ({"measure": "bp", "systolic": 80, "diastolic": 120}, "diastolic"),
    ({"measure": "bp", "systolic": 120}, "diastolic"),
    ({"measure": "spo2", "value": 150}, "value"),
    ({"measure": "heart_rate", "value": 400}, "value"),
    ({"measure": "temperature", "value": 98.6}, "unit"),
    ({"measure": "weight", "value": 700}, "value"),
    ({"measure": "weight", "value": 70, "unit": "stone"}, "unit"),
    ({"measure": "heart_rate", "value": 70, "context": "fasting"}, "context"),
    ({"measure": "glucose", "value": 5000}, "value"),
    ({"measure": "heart_rate", "value": 70, "taken_at": "2099-01-01T00:00:00Z"}, "taken_at"),
])
def test_implausible_readings_are_rejected(client, body, field):
    r = client.post("/api/vitals/readings", headers=PARK, json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["field"] == field
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations WHERE patient_id = %s AND category <> 'laboratory'",
                            (P_PARK,)).fetchone()["n"] == 0


def test_units_and_glucose_context(client):
    log(client, measure="temperature", value=98.6, unit="F")
    log(client, measure="weight", value=176, unit="lb")
    log(client, measure="glucose", value=5.5, unit="mmol/L", context="fasting")
    log(client, measure="glucose", value=150, context="after_meal")
    with db() as conn:
        rows = {(r["loinc_code"], r["measurement_context"]): float(r["value"]) for r in conn.execute(
            "SELECT loinc_code, value, measurement_context FROM observations WHERE patient_id = %s", (P_PARK,))}
    assert rows[("8310-5", None)] == 37.0
    assert rows[("29463-7", None)] == 79.8
    assert rows[("1558-6", "fasting")] == 99          # fasting glucose uses its own LOINC code
    assert rows[("2339-0", "after_meal")] == 150
    g = client.get("/api/vitals/measures/glucose?days=7", headers=PARK).json()
    assert {r["context"] for r in g["readings"]} == {"fasting", "after_meal"}


def test_delete_own_manual_reading_only(client):
    r = log(client, headers=MAYA, measure="bp", systolic=120, diastolic=78, pulse=66)
    rid = r["reading"]["id"]
    assert client.delete(f"/api/vitals/readings/{rid}", headers=PARK).status_code == 404
    assert client.delete(f"/api/vitals/readings/{rid}", headers=OKAFOR).status_code == 403
    ok = client.delete(f"/api/vitals/readings/{rid}", headers=MAYA)
    assert ok.status_code == 200 and ok.json()["deleted"] == 3
    assert client.delete(f"/api/vitals/readings/{rid}", headers=MAYA).status_code == 404
    with db() as conn:
        device_obs = conn.execute("SELECT id::text FROM observations WHERE device_id = %s LIMIT 1", (DEV_CUFF,)).fetchone()["id"]
    assert client.delete(f"/api/vitals/readings/{device_obs}", headers=MAYA).status_code == 409


# --- Trends ------------------------------------------------------------------------------------------------


def test_trend_stats_morning_evening_and_ranges(client):
    today = datetime.now(TZ).date()
    for d, (hh, s, dia) in enumerate([(7, 150, 95), (20, 120, 75), (7, 146, 92), (20, 118, 74)]):
        when = datetime.combine(today - timedelta(days=2 + d // 2), time(hh, 0), tzinfo=TZ)
        log(client, measure="bp", systolic=s, diastolic=dia, taken_at=when.isoformat())
    m = client.get("/api/vitals/measures/bp?days=7", headers=PARK).json()
    s = m["stats"]
    assert s["count"] == 4 and s["high"] == 2 and s["in_range_pct"] == 50
    assert s["morning"] == {"average": "148/94", "count": 2} and s["evening"] == {"average": "119/75", "count": 2}
    assert m["ranges"]["bp_systolic"]["high"] == 129 and "not a diagnosis" in m["explanation"]["text"]
    assert all(r["deletable"] for r in m["readings"])
    assert client.get("/api/vitals/measures/bp?days=45", headers=PARK).status_code == 422
    assert client.get("/api/vitals/measures/nope", headers=PARK).status_code == 404
    tiles = {t["measure"]: t for t in client.get("/api/vitals/summary", headers=PARK).json()["tiles"]}
    assert tiles["bp"]["week"]["count"] == 4 and len(tiles["bp"]["spark"]) == 4


# --- Devices and imports ------------------------------------------------------------------------------------


def test_connect_and_disconnect_device(client):
    r = client.post("/api/vitals/devices", headers=PARK, json={"kind": "glucometer", "integration": "bluetooth",
                                                               "vendor": "Demo", "model": "G1"})
    assert r.status_code == 201 and r.json()["simulated"] and "Demo pairing" in r.json()["notice"]
    did = r.json()["id"]
    assert client.post(f"/api/vitals/devices/{did}/disconnect", headers=MAYA).status_code == 404
    assert client.post(f"/api/vitals/devices/{did}/disconnect", headers=PARK).json()["status"] == "disconnected"
    assert client.post(f"/api/vitals/devices/{did}/disconnect", headers=PARK).status_code == 409
    assert client.post("/api/vitals/import", headers=PARK, json={"format": "json", "content": "[]",
                                                                 "device_id": did}).status_code == 409
    assert client.post(f"/api/vitals/devices/{did}/connect", headers=PARK).json()["status"] == "connected"
    assert client.post("/api/vitals/devices", headers=OKAFOR, json={"kind": "scale", "integration": "fitbit"}).status_code == 403
    devices = client.get(f"/api/vitals/devices?patient_id={P_PARK}", headers=OKAFOR).json()["devices"]
    assert devices[0]["label"] == "Demo G1"


def test_json_import_with_dedupe_and_rejections(client):
    t1, t2 = ago(days=2), ago(days=1)
    content = """{"readings": [
        {"measure": "bp", "systolic": 124, "diastolic": 80, "pulse": 70, "taken_at": "%s"},
        {"measure": "weight", "value": 81.2, "unit": "kg", "taken_at": "%s"},
        {"measure": "bp", "systolic": 1240, "diastolic": 80, "taken_at": "%s"},
        {"measure": "blood_type", "value": 1, "taken_at": "%s"},
        {"measure": "weight", "value": 81.2, "unit": "kg", "taken_at": "%s"}
    ]}""" % (t1, t2, t2, t2, t2)
    r = client.post("/api/vitals/import", headers=PARK, json={"format": "json", "content": content})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["imported"], body["skipped"], body["rejected_count"]) == (2, 1, 2)
    assert body["by_measure"] == {"bp": 1, "weight": 1}
    assert {x["row"] for x in body["rejected"]} == {3, 4}
    again = client.post("/api/vitals/import", headers=PARK, json={"format": "json", "content": content}).json()
    assert (again["imported"], again["skipped"]) == (0, 3)
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM observations WHERE patient_id = %s AND source = 'import'",
                            (P_PARK,)).fetchone()["n"] == 4   # BP panel (3) + weight
    bad = client.post("/api/vitals/import", headers=PARK, json={"format": "json", "content": "{nope"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "unreadable_file"


def test_csv_import(client):
    t1, t2 = ago(hours=30), ago(hours=6)
    csv_text = (f"measure,taken_at,value,systolic,diastolic,unit,context\n"
                f"bp,{t1},,122,79,,\nglucose,{t2},6.1,,,mmol/L,fasting\nsteps,{t2},8200,,,,\n")
    body = client.post("/api/vitals/import", headers=PARK, json={"format": "csv", "content": csv_text}).json()
    assert body["imported"] == 3 and body["rejected_count"] == 0
    missing = client.post("/api/vitals/import", headers=PARK, json={"format": "csv", "content": "a,b\n1,2\n"})
    assert missing.status_code == 422


APPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (Record)*>
<!ATTLIST Record type CDATA #REQUIRED>
]>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" unit="mmHg" value="131" startDate="{d1} 08:01:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" unit="mmHg" value="84" startDate="{d1} 08:01:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="72" startDate="{d1} 08:03:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="3000" startDate="{d1} 09:00:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="2500" startDate="{d1} 17:00:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" unit="lb" value="180" startDate="{d1} 07:00:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierBloodGlucose" unit="mg/dL" value="104" startDate="{d1} 07:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierOxygenSaturation" unit="%" value="0.97" startDate="{d1} 07:31:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierDietaryWater" unit="mL" value="250" startDate="{d1} 07:31:00 -0400"/>
</HealthData>"""


def test_apple_health_import_subset(client):
    d1 = (datetime.now(TZ).date() - timedelta(days=2)).isoformat()
    xml = APPLE.replace("{d1}", d1)
    body = client.post("/api/vitals/import", headers=PARK, json={"format": "apple_health", "content": xml}).json()
    assert body["by_measure"] == {"bp": 1, "heart_rate": 1, "steps": 1, "weight": 1, "glucose": 1, "spo2": 1}, body
    again = client.post("/api/vitals/import", headers=PARK, json={"format": "apple_health", "content": xml}).json()
    assert again["imported"] == 0 and again["skipped"] == 6
    steps = client.get("/api/vitals/measures/steps?days=7", headers=PARK).json()
    assert steps["readings"][0]["value"] == 5500      # summed into a daily total
    spo2 = client.get("/api/vitals/measures/spo2?days=7", headers=PARK).json()
    assert spo2["readings"][0]["value"] == 97          # a fraction in the export
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><HealthData>&a;</HealthData>'
    assert client.post("/api/vitals/import", headers=PARK,
                       json={"format": "apple_health", "content": bomb}).status_code == 422


def test_parsers_directly():
    rows = imp.parse_json('[{"measure": "pulse", "value": 60, "taken_at": "2026-09-01T08:00:00"}]')
    assert rows[0]["measure"] == "heart_rate" and rows[0]["taken_at"].tzinfo is not None
    assert isinstance(imp.parse_json('[{"measure": "bp", "taken_at": "yesterday"}]')[0], ValueError)
    with pytest.raises(imp.ImportError_):
        imp.parse_json('{"readings": 3}')


# --- Meter photo ----------------------------------------------------------------------------------------------

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


class FakeMessages:
    def __init__(self):
        self.calls = []
        self.output = None

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="test-model",
                               usage=SimpleNamespace(iterations=None), parsed_output=self.output)


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    messages = FakeMessages()
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    yield messages
    llm.set_client(None)


def observation_count(patient_id):
    with db() as conn:
        return conn.execute("SELECT count(*) AS n FROM observations WHERE patient_id = %s", (patient_id,)).fetchone()["n"]


def test_photo_rules_mode_falls_back_to_manual(client):
    before = observation_count(P_PARK)
    r = client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "image/png", "hint": "bp_cuff"})
    assert r.status_code == 200
    assert r.json()["needs_manual"] is True and r.json()["reason"] == "ai_unavailable" and r.json()["proposal"] is None
    assert observation_count(P_PARK) == before
    assert client.post("/api/vitals/photo", headers=PARK, json={"image": "not base64!", "media_type": "image/png"}).status_code == 422
    big = base64.b64encode(b"0" * (5 * 1024 * 1024 + 10)).decode()
    assert client.post("/api/vitals/photo", headers=PARK, json={"image": big, "media_type": "image/jpeg"}).status_code == 413
    assert client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "application/pdf"}).status_code == 422
    assert client.post("/api/vitals/photo", headers=OKAFOR, json={"image": PNG, "media_type": "image/png"}).status_code == 403


def test_photo_ai_proposes_then_patient_confirms(client, fake_claude):
    fake_claude.output = imp.MeterReading(device_type="bp_cuff", display_readable=True, systolic=128, diastolic=82,
                                          pulse=71, unit="mmHg", confidence="high")
    before = observation_count(P_PARK)
    r = client.post("/api/vitals/photo", headers=PARK,
                    json={"image": f"data:image/png;base64,{PNG}", "media_type": "image/png", "hint": "bp_cuff"}).json()
    assert r["needs_manual"] is False and r["problem"] is None
    assert r["proposal"] == {"measure": "bp", "systolic": 128, "diastolic": 82, "pulse": 71, "value": None,
                             "unit": "mmHg", "context": None}
    assert observation_count(P_PARK) == before, "a proposal is never saved"
    call = fake_claude.calls[0]
    image = call["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["data"] == PNG
    assert "data, not instructions" in call["system"]
    saved = log(client, measure="bp", systolic=128, diastolic=82, pulse=71, source="photo")
    assert saved["reading"]["source"] == "photo" and saved["reading"]["deletable"]
    with db() as conn:
        a = conn.execute("SELECT detail FROM audit_events WHERE action = 'vital_photo_read'").fetchone()
    assert a["detail"]["stored"] is False and a["detail"]["device_type"] == "bp_cuff"


def test_photo_ai_unreadable_or_implausible(client, fake_claude):
    fake_claude.output = imp.MeterReading(device_type="unknown", display_readable=False, confidence="low")
    r = client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "image/png"}).json()
    assert r["needs_manual"] and r["reason"] == "unreadable"
    fake_claude.output = imp.MeterReading(device_type="thermometer", display_readable=True, value=101.2, unit="°F",
                                          confidence="medium")
    r = client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "image/png"}).json()
    assert r["proposal"]["measure"] == "temperature" and r["problem"] is None
    fake_claude.output = imp.MeterReading(device_type="glucometer", display_readable=True, value=1400, unit="mg/dL",
                                          confidence="low")
    r = client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "image/png"}).json()
    assert r["needs_manual"] is False and "isn't possible" in r["problem"]


def test_photo_respects_ai_consent(client, fake_claude):
    with db() as conn:
        consent.set_status(conn, patient_id=P_PARK, scope="ai_processing", status="denied", actor=None)
    r = client.post("/api/vitals/photo", headers=PARK, json={"image": PNG, "media_type": "image/png"}).json()
    assert r["needs_manual"] and r["reason"] == "ai_consent"
    assert fake_claude.calls == []


# --- Alerts ------------------------------------------------------------------------------------------------------


def notifications(user_id, kind):
    with db() as conn:
        return conn.execute("SELECT title, priority, body, link FROM notifications WHERE user_id = %s AND kind = %s "
                            "ORDER BY created_at", (user_id, kind)).fetchall()


def test_critical_bp_alerts_patient_and_care_team_once(client):
    r = log(client, headers=MAYA, measure="bp", systolic=186, diastolic=110, pulse=90)
    assert r["safety"]["call"] == "911" and "5 minutes" in r["safety"]["message"] and "chest pain" in r["safety"]["message"]
    assert r["reading"]["status"] == "critical_high"
    crit = [a for a in r["alerts"] if a["kind"] == "critical_high"][0]
    assert crit["new"] is True
    alerts = {a["kind"]: a for a in open_alerts(P_MAYA)}
    assert alerts["critical_high"]["practitioner_id"] == DR_OKAFOR    # the monitoring plan's clinician
    with db() as conn:
        item = conn.execute("SELECT priority, link, status FROM review_items WHERE id = %s",
                            (alerts["critical_high"]["review_item_id"],)).fetchone()
    assert item == {"priority": "urgent", "link": f"/clinician/vitals/{P_MAYA}", "status": "open"}
    maya = notifications(U_MAYA, "vital_alert")
    assert any(n["priority"] == "urgent" and "call 911" in n["body"] for n in maya)
    assert all("186" not in n["title"] for n in maya), "no clinical detail in titles"
    okafor = client.get("/api/notifications", headers=OKAFOR).json()["items"]
    assert any(n["kind"] == "vital_alert" and n["priority"] == "high" for n in okafor)

    # A second critical reading the same day attaches to the open alert: no new item, no new notification.
    again = log(client, headers=MAYA, measure="bp", systolic=182, diastolic=100)
    assert again["safety"] is not None
    assert [a["new"] for a in again["alerts"] if a["kind"] == "critical_high"] == [False]
    alerts = {a["kind"]: a for a in open_alerts(P_MAYA)}
    assert alerts["critical_high"]["reading_count"] == 2
    with db() as conn:
        n_items = conn.execute("SELECT count(*) AS n FROM review_items WHERE kind = 'vital_alert' AND priority = 'urgent'"
                               ).fetchone()["n"]
    assert n_items == 1 and len(notifications(U_MAYA, "vital_alert")) == len(maya)


@pytest.mark.parametrize("body, kind, phrase", [
    ({"measure": "spo2", "value": 88}, "critical_low", "oxygen"),
    ({"measure": "glucose", "value": 45}, "critical_low", "15 grams"),
    ({"measure": "glucose", "value": 350, "context": "after_meal"}, "critical_high", "very high"),
])
def test_other_critical_readings_get_fixed_guidance(client, body, kind, phrase):
    r = log(client, **body)
    assert phrase in r["safety"]["message"] and "911" in r["safety"]["message"]
    assert [a["kind"] for a in open_alerts(P_PARK)] == [kind]


def test_old_critical_reading_alerts_clinician_without_act_now_message(client):
    r = log(client, measure="spo2", value=87, taken_at=ago(days=3))
    assert r["safety"] is None and r["alerts"][0]["kind"] == "critical_low"
    assert notifications(U_PARK, "vital_alert") == []


def test_mildly_high_single_reading_is_not_an_alert(client):
    r = log(client, measure="bp", systolic=138, diastolic=86)
    assert r["alerts"] == [] and r["safety"] is None and "common" in r["note"]


def test_sustained_high_bp_then_acknowledge(client):
    for i, (s, d) in enumerate([(142, 90), (118, 76), (139, 88)]):
        r = log(client, measure="bp", systolic=s, diastolic=d, taken_at=ago(hours=10 - i))
        assert r["alerts"] == []
    r = log(client, measure="bp", systolic=145, diastolic=91, taken_at=ago(hours=6))
    assert [(a["kind"], a["new"]) for a in r["alerts"]] == [("sustained_high", True)]
    r = log(client, measure="bp", systolic=144, diastolic=92, taken_at=ago(hours=5))
    assert [(a["kind"], a["new"]) for a in r["alerts"]] == [("sustained_high", False)]
    [alert] = open_alerts(P_PARK)
    assert alert["severity"] == "warning" and alert["practitioner_id"]
    park = notifications(U_PARK, "vital_alert")
    assert len(park) == 1 and park[0]["priority"] == "normal"

    # The core queue sends the clinician to this module's screen; acknowledging here resolves the item.
    core_resolve = client.post(f"/api/clinician/review-items/{alert['review_item_id']}/resolve", headers=OKAFOR,
                               json={"action": "acknowledge"})
    assert core_resolve.status_code in (404, 409)
    assert client.post(f"/api/vitals/alerts/{alert['id']}/acknowledge", headers=PARK, json={}).status_code == 403
    ok = client.post(f"/api/vitals/alerts/{alert['id']}/acknowledge", headers=OKAFOR, json={"note": "Reviewed, call booked"})
    assert ok.status_code == 200
    assert client.post(f"/api/vitals/alerts/{alert['id']}/acknowledge", headers=OKAFOR, json={}).status_code == 409
    with db() as conn:
        item = conn.execute("SELECT status, resolution FROM review_items WHERE id = %s", (alert["review_item_id"],)).fetchone()
    assert item["status"] == "resolved" and "Reviewed" in item["resolution"]

    # After acknowledgement only new readings count: one more high reading doesn't reopen it.
    r = log(client, measure="bp", systolic=146, diastolic=92)
    assert r["alerts"] == [] and open_alerts(P_PARK) == []
    patient_view = client.get("/api/vitals/alerts", headers=PARK).json()
    assert patient_view[0]["status"] == "acknowledged" and "ack_note" not in patient_view[0]


def test_weight_gain_over_three_days(client):
    log(client, measure="weight", value=80.0, taken_at=ago(days=2, hours=12))
    assert log(client, measure="weight", value=81.0, taken_at=ago(days=1))["alerts"] == []
    r = log(client, measure="weight", value=82.3)
    assert r["alerts"][0]["kind"] == "weight_gain" and r["alerts"][0]["title"] == "Weight up 2.3 kg in 3 days"
    assert "short of breath" in notifications(U_PARK, "vital_alert")[0]["body"]


def test_clinician_thresholds_change_interpretation_and_alerts(client):
    url = f"/api/vitals/patients/{P_PARK}/thresholds/bp_systolic"
    assert client.put(url, headers=PARK, json={"high": 140}).status_code == 403
    assert client.put(url, headers=OKAFOR, json={"high": 190, "critical_high": 170}).status_code == 422
    assert client.put(url, headers=OKAFOR, json={"high": 900}).status_code == 422
    assert client.put(f"/api/vitals/patients/{P_PARK}/thresholds/nope", headers=OKAFOR, json={"high": 1}).status_code == 404
    t = client.put(url, headers=OKAFOR, json={"high": 139, "critical_high": 160, "note": "Older adult target"}).json()
    assert t["source"] == "clinician" and t["high"] == 139 and t["low"] == 90
    assert log(client, measure="bp", systolic=135, diastolic=78)["reading"]["status"] == "in_range"
    r = log(client, measure="bp", systolic=165, diastolic=78)
    assert r["reading"]["status"] == "critical_high" and r["safety"]
    wg = client.put(f"/api/vitals/patients/{P_PARK}/thresholds/weight_gain_3d", headers=OKAFOR, json={"high": 1.0})
    assert wg.status_code == 200 and wg.json()["high"] == 1.0
    reset = client.delete(url, headers=OKAFOR).json()
    assert reset["source"] == "default" and reset["high"] == 129
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'vital_threshold_set'").fetchone()["n"] == 2


# --- Monitoring plans and reminders --------------------------------------------------------------------------------


def make_plan(client, **kw):
    body = {"measure": "bp", "times": ["08:00", "20:00"], "days": 14, "instructions": "Rest 5 minutes first."} | kw
    r = client.post(f"/api/vitals/patients/{P_PARK}/plans", headers=OKAFOR, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_plan_validation_and_patient_notice(client):
    assert client.post(f"/api/vitals/patients/{P_PARK}/plans", headers=PARK,
                       json={"measure": "bp", "times": ["08:00"], "days": 3}).status_code == 403
    close = client.post(f"/api/vitals/patients/{P_PARK}/plans", headers=OKAFOR,
                        json={"measure": "bp", "times": ["08:00", "09:00"], "days": 3})
    assert close.status_code == 422
    plan = make_plan(client)
    assert plan["label"] == "Blood pressure twice daily for 14 days" and plan["practitioner_name"] == "Dr. Adaeze Okafor"
    assert client.post(f"/api/vitals/patients/{P_PARK}/plans", headers=OKAFOR,
                       json={"measure": "bp", "times": ["09:00"], "days": 3}).status_code == 409
    assert notifications(U_PARK, "vital_reminder")[0]["title"] == "New home monitoring plan from your care team"
    # Adherence is visible to both sides.
    mine = client.get("/api/vitals/summary", headers=PARK).json()["plans"][0]["adherence"]
    theirs = client.get(f"/api/vitals/summary?patient_id={P_PARK}", headers=OKAFOR).json()["plans"][0]["adherence"]
    assert mine == theirs
    assert client.post(f"/api/vitals/plans/{plan['id']}/stop", headers=OKAFOR).json()["status"] == "stopped"
    assert client.post(f"/api/vitals/plans/{plan['id']}/stop", headers=OKAFOR).status_code == 409


def test_reminders_job_is_idempotent_and_skips_logged_slots(client):
    plan = make_plan(client)
    today = datetime.now(TZ).date()
    at = lambda hh, mm: datetime.combine(today, time(hh, mm), tzinfo=TZ).astimezone(timezone.utc)  # noqa: E731

    def reminders():
        with db() as conn:
            return conn.execute("SELECT title, link FROM notifications WHERE dedupe_key LIKE %s",
                                (f"vitals:plan:{plan['id']}:slot:%",)).fetchall()

    with db() as conn:
        early = run_job(conn, "vitals_reminders", at(7, 50))
        assert early["status"] == "succeeded" and reminders() == []
        run_job(conn, "vitals_reminders", at(8, 10))
        assert len(reminders()) == 1
        run_job(conn, "vitals_reminders", at(8, 25))      # same slot again: nothing new
    assert reminders() == [{"title": "Time to measure your blood pressure", "link": "/vitals"}]

    # A reading in the evening window before 20:00 means no evening reminder.
    with db() as conn:
        conn.execute(
            """
            INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                      category, source)
            VALUES (%s, '8480-6', 'Systolic blood pressure', 121, 'mm[Hg]', 'N', %s, 'vital-signs', 'manual')
            """,
            (P_PARK, at(19, 30)),
        )
        evening = run_job(conn, "vitals_reminders", at(20, 5))
    assert evening["detail"]["already_logged"] >= 1 and len(reminders()) == 1

    with db() as conn:
        conn.execute("UPDATE vital_monitoring_plans SET start_on = %s, end_on = %s WHERE id = %s",
                     (today - timedelta(days=5), today - timedelta(days=1), plan["id"]))
        done = run_job(conn, "vitals_reminders", at(21, 0))
        status = conn.execute("SELECT status FROM vital_monitoring_plans WHERE id = %s", (plan["id"],)).fetchone()["status"]
    assert done["detail"]["completed_plans"] == 1 and status == "completed"


def test_adherence_counts_slots():
    today = datetime.now(TZ).date()
    plan = {"measure": "bp", "times": [time(8), time(20)], "start_on": today - timedelta(days=1), "end_on": today,
            "patient_id": P_PARK}
    windows = core.slots(plan, today)
    assert windows[0][1].hour == 8 and windows[0][2].hour == 11 and windows[1][0].hour == 19


# --- Access, brief, timeline, intents --------------------------------------------------------------------------------


def test_access_control(client):
    assert client.get(f"/api/vitals/summary?patient_id={P_MAYA}", headers=PARK).status_code == 403
    assert client.get("/api/vitals/summary", headers=ADMIN).status_code == 403
    assert client.get(f"/api/vitals/summary?patient_id={P_MAYA}", headers=FRONTDESK).status_code == 403
    assert client.get("/api/vitals/summary", headers=OKAFOR).status_code == 400
    assert client.get("/api/vitals/summary?patient_id=nope", headers=OKAFOR).status_code == 404
    assert client.post("/api/vitals/readings", headers=OKAFOR, json={"measure": "heart_rate", "value": 60}).status_code == 403
    assert client.get(f"/api/vitals/measures/bp?patient_id={P_HADDAD}", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/vitals/summary?patient_id={P_MAYA}", headers=OKAFOR).status_code == 200
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'vitals_viewed' AND patient_id = %s",
                            (P_MAYA,)).fetchone()["n"] == 1
    listing = client.get("/api/vitals/clinician/patients", headers=OKAFOR).json()
    assert any(p["id"] == P_MAYA and p["open_alerts"] >= 1 for p in listing)
    assert client.get("/api/vitals/clinician/patients", headers=MAYA).status_code == 403


def test_brief_bullets_and_timeline(client):
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    texts = [b["text"] for b in brief["bullets"]]
    bp = next(t for t in texts if t.startswith("Home BP averaged"))
    assert "over 14 days" in bp and "readings high" in bp and "critical" not in bp
    assert any(t.startswith("Home monitoring (your plan): blood pressure twice daily") for t in texts)
    assert any(t.startswith("Open home vitals alert: Blood pressure high on") for t in texts)
    assert "Open home vitals alert" in brief["attention_flags"]
    assert any(e["type"] == "vital_plan" for e in brief["timeline"])

    log(client, headers=MAYA, measure="bp", systolic=190, diastolic=100)
    with db() as conn:
        bullets = core.brief_bullets(conn, P_MAYA, DR_OKAFOR)
        assert core.brief_bullets(conn, P_PARK, DR_OKAFOR) == []
    assert "; 1 critical alert." in bullets[0]["text"]
    assert any(b["flag"] == "Critical home reading" for b in bullets)


@pytest.mark.parametrize("text", [
    "log my blood pressure", "I want to record my glucose", "add a new weight reading", "my bp readings",
    "record my blood sugar this morning", "connect my blood pressure cuff", "track my oxygen",
])
def test_vitals_intent(text):
    assert rules_triage([{"role": "user", "content": text}], {}).intent == "vitals"


@pytest.mark.parametrize("text", [
    "my blood pressure is high and I have a headache", "I checked my pulse and feel faint",
    "chest pain when I measure my blood pressure", "what does my cholesterol result mean",
])
def test_vitals_intent_does_not_steal_symptoms(text):
    assert rules_triage([{"role": "user", "content": text}], {}).intent != "vitals"
