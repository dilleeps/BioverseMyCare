"""Health companion: jobs (idempotent, with fixed `now`), doses, check-ins and escalation, access and audit."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import companion
from bioverse.agents import llm
from bioverse.agents.triage import rules_triage
from bioverse.db.seed import DR_OKAFOR, P_HADDAD, U_PARK, seed
from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.s050_billing_pharmacy import DISP_ATORVA_1, RX_HADDAD_AMLO, RX_MAYA_ATORVA
from bioverse.db.seeds.s140_companion import CHECKIN_AMLO, CHECKIN_VISIT, RX_MAYA_AMLO
from bioverse.jobs import run_job
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK, P_PARK
from bioverse.db.seed import U_MAYA

CTX = SeedContext()
at, days = CTX.at, CTX.days
UTC = timezone.utc


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def count(sql: str, *params) -> int:
    with db() as conn:
        return conn.execute(sql, params).fetchone()["n"]


def notes(user_id: str, prefix: str) -> list[dict]:
    with db() as conn:
        return conn.execute(
            "SELECT kind, title, body, link, status, due_at, dedupe_key, priority FROM notifications "
            "WHERE user_id = %s AND dedupe_key LIKE %s ORDER BY due_at", (user_id, prefix + "%")).fetchall()


def run_twice(name: str, now: datetime) -> tuple[dict, dict]:
    with db() as conn:
        first = run_job(conn, name, now)
        second = run_job(conn, name, now)
    assert first["status"] == second["status"] == "succeeded", (first, second)
    return first["detail"], second["detail"]


def audit_actions(patient_id: str) -> list[dict]:
    with db() as conn:
        return conn.execute("SELECT action, agent, model, actor_user_id::text FROM audit_events WHERE patient_id = %s",
                            (patient_id,)).fetchall()


def open_checkin(patient_id=P_MAYA, kind="new_medication", ref=RX_MAYA_ATORVA, subject="Atorvastatin 20 mg",
                 practitioner=DR_OKAFOR) -> str:
    with db() as conn:
        return conn.execute(
            """
            INSERT INTO companion_checkins (patient_id, kind, ref_id, subject, practitioner_id, prompt, produced_by, due_at)
            VALUES (%s, %s, %s, %s, %s, 'How are you?', 'companion/rules', now() - interval '1 hour') RETURNING id::text
            """,
            (patient_id, kind, ref, subject, practitioner),
        ).fetchone()["id"]


def pick_up_atorvastatin(when: datetime) -> None:
    with db() as conn:
        conn.execute("UPDATE medication_dispenses SET status = 'picked_up', picked_up_at = %s WHERE id = %s",
                     (when, DISP_ATORVA_1))


# --- Seed ------------------------------------------------------------------------------------------


def test_seed_story_and_idempotent(client):
    def snapshot():
        return (count("SELECT count(*) AS n FROM medication_doses WHERE patient_id = %s", P_MAYA),
                count("SELECT count(*) AS n FROM companion_checkins WHERE patient_id = %s", P_MAYA),
                count("SELECT count(*) AS n FROM notifications WHERE user_id = %s", U_MAYA),
                count("SELECT count(*) AS n FROM medication_adherence_logs WHERE patient_id = %s", P_MAYA))
    before = snapshot()
    seed(DB)
    assert snapshot() == before
    assert before[0] == 14 and before[1] == 2 and before[3] == 13
    checkins = client.get("/api/companion/checkins", headers=MAYA).json()
    assert [c["id"] for c in checkins["open"]] == [CHECKIN_VISIT]
    assert [(c["id"], c["response"]) for c in checkins["history"]] == [(CHECKIN_AMLO, "better")]
    s = client.get("/api/companion/settings", headers=MAYA).json()
    assert s["daily_brief"] and s["dose_times"]["evening"] == "21:00"
    meds = {m["rx_id"]: m for m in s["medications"]}
    assert meds[RX_MAYA_AMLO]["times"] == ["08:00"] and meds[RX_MAYA_ATORVA]["times"] == ["21:00"]
    assert meds[RX_MAYA_ATORVA]["started"] is False     # waiting for pickup


def test_adherence_summary(client):
    a = client.get("/api/companion/adherence", headers=MAYA).json()
    amlo = next(m for m in a["medications"] if m["rx_id"] == RX_MAYA_AMLO)
    assert amlo["last_7"] == {"taken": 6, "skipped": 0, "missed": 1, "expected": 7, "pct": 86}
    assert amlo["last_30"] == {"taken": 13, "skipped": 1, "missed": 1, "expected": 15, "pct": 87}
    assert a["last_30"]["pct"] == 87 and len(amlo["days"]) == 14
    atorva = next(m for m in a["medications"] if m["rx_id"] == RX_MAYA_ATORVA)
    assert atorva["tracking"] is False and atorva["waiting_for_pickup"]
    # The pharmacy page agrees, and nothing flags low adherence for Maya.
    rx = client.get(f"/api/pharmacy/prescriptions/{RX_MAYA_AMLO}", headers=MAYA).json()
    assert rx["adherence"]["pct_7"] == 86


# --- Medication reminders -------------------------------------------------------------------------


def test_medication_reminders_are_idempotent_and_generic(client):
    now = at(days(0), 7, 30).astimezone(UTC)
    first, second = run_twice("medication_reminders", now)
    assert first["created"] == 2 and second["created"] == 0            # Maya's amlodipine and Rana's
    [n] = notes(U_MAYA, "med:")
    assert n["dedupe_key"] == f"med:{RX_MAYA_AMLO}:{days(0).isoformat()}T08:00"
    assert n["due_at"] == at(days(0), 8, 0)
    assert n["title"] == "Time for your morning medicine" and n["kind"] == "medication_reminder"
    assert "Amlodipine" not in n["title"] + n["body"]
    assert n["link"] == f"/companion?rx={RX_MAYA_AMLO}&at={days(0).isoformat()}T08:00"
    # Nothing is created more than an hour ahead.
    run_twice("medication_reminders", at(days(0), 5, 0).astimezone(UTC))
    assert len(notes(U_MAYA, "med:")) == 1


def test_reminders_start_at_pickup_and_stop_when_prescription_stops(client):
    evening = at(days(0), 20, 15).astimezone(UTC)
    run_twice("medication_reminders", evening)
    assert notes(U_MAYA, f"med:{RX_MAYA_ATORVA}:") == []          # not picked up yet
    pick_up_atorvastatin(at(days(-1), 16, 0))
    first, second = run_twice("medication_reminders", evening)
    assert first["created"] == 1 and second["created"] == 0
    [n] = notes(U_MAYA, f"med:{RX_MAYA_ATORVA}:")
    assert n["status"] == "pending" and n["due_at"] == at(days(0), 21, 0)   # Maya prefers 21:00 in the evening

    with db() as conn:
        conn.execute("UPDATE medication_requests SET status = 'stopped' WHERE id = %s", (RX_MAYA_ATORVA,))
    first, second = run_twice("medication_reminders", evening)
    assert first["cancelled"] == 1 and second["cancelled"] == 0
    assert [x["status"] for x in notes(U_MAYA, f"med:{RX_MAYA_ATORVA}:")] == ["cancelled"]
    assert any(a["action"] == "medication_reminders_cancelled" for a in audit_actions(P_MAYA))


def test_marked_dose_gets_no_reminder(client):
    today = days(0).isoformat()
    r = client.post("/api/companion/doses", headers=MAYA,
                    json={"medication_request_id": RX_MAYA_AMLO, "local_time": f"{today}T08:00", "status": "taken"})
    assert r.status_code == 201
    run_twice("medication_reminders", at(days(0), 7, 30).astimezone(UTC))
    assert notes(U_MAYA, "med:") == []


# --- Doses: take and skip -------------------------------------------------------------------------


def test_take_skip_undo_and_audit(client):
    t = client.get("/api/companion/today", headers=MAYA).json()
    dose = next(d for d in t["doses"] if d["rx_id"] == RX_MAYA_AMLO)
    assert dose["time"] == "08:00" and dose["status"] in ("due", "upcoming")
    assert [w["rx_id"] for w in t["waiting_for_pickup"]] == [RX_MAYA_ATORVA]
    assert t["tip"]["source"] and t["checkins"][0]["id"] == CHECKIN_VISIT

    url = "/api/companion/doses"
    body = {"medication_request_id": RX_MAYA_AMLO, "local_time": dose["local"], "status": "taken"}
    r = client.post(url, headers=MAYA, json=body)
    assert r.status_code == 201 and r.json()["status"] == "taken"
    t = client.get("/api/companion/today", headers=MAYA).json()
    assert next(d for d in t["doses"] if d["rx_id"] == RX_MAYA_AMLO)["status"] == "taken"
    assert count("SELECT count(*) AS n FROM medication_adherence_logs WHERE medication_request_id = %s AND taken_on = %s",
                 RX_MAYA_AMLO, days(0)) == 1

    skip = client.post(url, headers=MAYA, json={**body, "status": "skipped", "reason": "side_effects"})
    assert skip.status_code == 201 and skip.json()["reason"] == "side_effects" and "care team" in skip.json()["note"]
    assert count("SELECT count(*) AS n FROM medication_adherence_logs WHERE medication_request_id = %s AND taken_on = %s",
                 RX_MAYA_AMLO, days(0)) == 0
    assert client.post(url, headers=MAYA, json={**body, "reason": "forgot"}).status_code == 422
    assert client.post(url, headers=MAYA, json={**body, "local_time": f"{days(0)}T09:13"}).status_code == 404
    assert client.post(url, headers=MAYA, json={**body, "local_time": f"{days(1)}T08:00"}).status_code == 422
    assert client.post(url, headers=MAYA, json={**body, "local_time": f"{days(-8)}T08:00"}).status_code == 422
    assert client.post(url, headers=MAYA, json={**body, "status": "lost"}).status_code == 422
    assert client.post(url, headers=OKAFOR, json=body).status_code == 403
    assert client.post(url, headers=MAYA, json={**body, "medication_request_id": RX_HADDAD_AMLO}).status_code == 404
    assert client.post(url, headers=MAYA, json={**body, "medication_request_id": "nope"}).status_code == 404

    # A dose from last week can still be marked; then undone.
    late = client.post(url, headers=MAYA, json={**body, "local_time": f"{days(-4)}T08:00"})
    assert late.status_code == 201
    a = client.get("/api/companion/adherence", headers=MAYA).json()
    amlo = next(m for m in a["medications"] if m["rx_id"] == RX_MAYA_AMLO)
    assert amlo["last_7"]["taken"] == 7 and amlo["last_7"]["skipped"] == 1
    assert client.delete(f"/api/companion/doses/{late.json()['id']}", headers=PARK).status_code == 404
    assert client.delete(f"/api/companion/doses/{late.json()['id']}", headers=MAYA).status_code == 200

    actions = {a["action"] for a in audit_actions(P_MAYA)}
    assert {"medication_dose_taken", "medication_dose_skipped", "medication_dose_undone"} <= actions


# --- Appointment reminders -------------------------------------------------------------------------


def book(reason: str, starts: datetime, mode="in_person") -> str:
    with db() as conn:
        slot = conn.execute("INSERT INTO slots (practitioner_id, starts_at, mode, status) VALUES (%s, %s, %s, 'booked') "
                            "RETURNING id", (DR_OKAFOR, starts, mode)).fetchone()["id"]
        return conn.execute("INSERT INTO appointments (patient_id, practitioner_id, slot_id, reason) VALUES (%s, %s, %s, %s) "
                            "RETURNING id::text", (P_MAYA, DR_OKAFOR, slot, reason)).fetchone()["id"]


def test_appointment_reminders_24h_and_2h(client):
    starts = at(days(3), 10, 5)
    appt = book("Fasting lipid blood test and review", starts)
    first, second = run_twice("appointment_reminders", (starts - timedelta(hours=24, minutes=30)).astimezone(UTC))
    assert first["created"] == 1 and second["created"] == 0
    [day_before] = notes(U_MAYA, f"appt:{appt}:")
    assert day_before["title"] == "Appointment tomorrow at 10:05 AM" and day_before["link"] == "/visits"
    assert "fasting" in day_before["body"] and "Northside Heart Centre" in day_before["body"]
    assert "medication list" in day_before["body"]

    first, second = run_twice("appointment_reminders", (starts - timedelta(hours=2, minutes=10)).astimezone(UTC))
    assert first["created"] == 1 and second["created"] == 0
    reminders = notes(U_MAYA, f"appt:{appt}:")
    assert [r["dedupe_key"].rsplit(":", 1)[1] for r in reminders] == ["24h", "2h"]
    assert reminders[1]["title"] == "Appointment today at 10:05 AM"

    with db() as conn:
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (appt,))
    first, _ = run_twice("appointment_reminders", (starts - timedelta(hours=3)).astimezone(UTC))
    assert first["cancelled"] == 2
    assert {r["status"] for r in notes(U_MAYA, f"appt:{appt}:")} == {"cancelled"}


def test_late_booking_gets_only_the_2h_reminder(client):
    starts = at(days(3), 15, 5)
    appt = book("Video follow-up", starts, mode="video")
    run_twice("appointment_reminders", (starts - timedelta(hours=2, minutes=30)).astimezone(UTC))
    [r] = notes(U_MAYA, f"appt:{appt}:")
    assert r["dedupe_key"].endswith(":2h") and "camera" in r["body"]


# --- Check-ins -------------------------------------------------------------------------------------


def test_checkin_job_after_visit_and_new_medicine(client):
    pick_up_atorvastatin(at(days(-3), 17, 0))
    with db() as conn:
        conn.execute("INSERT INTO encounters (patient_id, practitioner_id, occurred_at, kind, summary) "
                     "VALUES (%s, %s, %s, 'Cardiology visit', 'Review')", (P_PARK, DR_OKAFOR, at(days(-1), 9, 0)))
    now = at(days(0), 10, 30).astimezone(UTC)
    first, second = run_twice("companion_checkins", now)
    assert first["new_medication"] == 1 and first["post_visit"] == 1       # Maya's visit check-in was seeded
    assert second == {"post_visit": 0, "new_medication": 0, "expired": 0}
    with db() as conn:
        c = conn.execute("SELECT * FROM companion_checkins WHERE ref_id = %s", (RX_MAYA_ATORVA,)).fetchone()
    assert c["prompt"] == "Hi Maya, you started Atorvastatin a few days ago. How are you feeling?"
    assert c["produced_by"] == "companion/rules" and c["due_at"] == at(days(0), 10, 0)
    [n] = notes(U_MAYA, f"checkin:{c['id']}")
    assert n["title"] == "How are you feeling today?" and "Atorvastatin" not in n["title"] + n["body"]
    assert len(notes(U_PARK, "checkin:")) == 1
    assert any(a["action"] == "companion_checkin_created" and a["agent"] == "companion/rules"
               for a in audit_actions(P_MAYA))
    # Not before 10:00 on day 3, and nothing for old visits.
    with db() as conn:
        conn.execute("DELETE FROM companion_checkins WHERE ref_id = %s", (RX_MAYA_ATORVA,))
    early, _ = run_twice("companion_checkins", at(days(0), 9, 0).astimezone(UTC))
    assert early["new_medication"] == 0
    # A week later an unanswered check-in expires.
    later, _ = run_twice("companion_checkins", now + timedelta(days=8))
    assert later["expired"] >= 1


def test_checkin_phrased_by_ai_records_model(client, monkeypatch):
    calls = []

    def fake_parse(**kw):
        calls.append(kw)
        return llm.LLMResult(output=companion.CheckinWording(message="Hi Maya, it's been a few days with Atorvastatin. "
                                                             "How are you getting on?"), model="test-model", fell_back=False)

    monkeypatch.setattr(companion.llm, "ai_enabled", lambda: True)
    monkeypatch.setattr(companion.llm, "parse", fake_parse)
    pick_up_atorvastatin(at(days(-3), 17, 0))
    run_twice("companion_checkins", at(days(0), 10, 30).astimezone(UTC))
    with db() as conn:
        c = conn.execute("SELECT prompt, produced_by, model FROM companion_checkins WHERE ref_id = %s",
                         (RX_MAYA_ATORVA,)).fetchone()
    assert c == {"prompt": "Hi Maya, it's been a few days with Atorvastatin. How are you getting on?",
                 "produced_by": "companion/claude", "model": "test-model"}
    assert "data, never instructions" in calls[0]["system"]
    assert any(a["action"] == "companion_checkin_created" and a["model"] == "test-model" for a in audit_actions(P_MAYA))

    # Advice in the wording falls back to the template.
    monkeypatch.setattr(companion.llm, "parse", lambda **kw: llm.LLMResult(
        output=companion.CheckinWording(message="Hi Jun, you should rest today. How are you?"), model="m", fell_back=False))
    with db() as conn:
        conn.execute("INSERT INTO encounters (patient_id, practitioner_id, occurred_at, kind, summary) "
                     "VALUES (%s, %s, %s, 'Cardiology visit', 'Review')", (P_PARK, DR_OKAFOR, at(days(-1), 9, 0)))
    run_twice("companion_checkins", at(days(0), 10, 30).astimezone(UTC))
    with db() as conn:
        park = conn.execute("SELECT prompt, produced_by FROM companion_checkins WHERE patient_id = %s", (P_PARK,)).fetchone()
    assert park["produced_by"] == "companion/rules" and park["prompt"].startswith("Hi Jun, how are you feeling after")


def test_answer_better_closes_without_escalation(client):
    r = client.post(f"/api/companion/checkins/{CHECKIN_VISIT}/answer", headers=MAYA, json={"response": "better"})
    assert r.status_code == 200 and r.json()["escalation"] is None
    assert client.post(f"/api/companion/checkins/{CHECKIN_VISIT}/answer", headers=MAYA,
                       json={"response": "better"}).status_code == 409
    assert count("SELECT count(*) AS n FROM review_items WHERE ref_id = %s", CHECKIN_VISIT) == 0
    events = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()["events"]
    assert any(e["type"] == "companion_checkin" and e["ref_id"] == CHECKIN_VISIT for e in events)


def test_answer_worse_creates_routine_review_item(client):
    cid = open_checkin()
    r = client.post(f"/api/companion/checkins/{cid}/answer", headers=MAYA, json={"response": "worse", "note": "Tired all day"})
    assert r.status_code == 200 and r.json()["escalation"] == "routine"
    with db() as conn:
        item = conn.execute("SELECT * FROM review_items WHERE ref_id = %s", (cid,)).fetchone()
    assert item["kind"] == "companion_checkin" and item["priority"] == "routine" and item["practitioner_id"] is not None
    assert item["link"] == f"/clinician/companion?patient={P_MAYA}" and "Tired all day" in item["body"]

    esc = client.get("/api/companion/clinician/escalations", headers=OKAFOR).json()["items"]
    assert [e["checkin_id"] for e in esc] == [cid]
    # The core queue sends the clinician to this module's screen to decide it.
    assert client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR,
                       json={"action": "acknowledge"}).status_code == 409
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert any("Reported feeling worse on day" in b["text"] and "Atorvastatin 20 mg" in b["text"] for b in brief["bullets"])
    assert "Check-in needs review" in brief["attention_flags"]
    ok = client.post(f"/api/companion/clinician/escalations/{item['id']}/resolve", headers=OKAFOR, json={"note": "Called"})
    assert ok.status_code == 200
    assert client.post(f"/api/companion/clinician/escalations/{item['id']}/resolve", headers=OKAFOR,
                       json={}).status_code == 409
    assert client.get("/api/companion/clinician/escalations", headers=OKAFOR).json()["items"] == []
    assert {"companion_checkin_answered", "companion_escalation_resolved"} <= {a["action"] for a in audit_actions(P_MAYA)}


def test_side_effect_mention_for_new_medicine_escalates(client):
    cid = open_checkin()
    r = client.post(f"/api/companion/checkins/{cid}/answer", headers=MAYA,
                    json={"response": "same", "note": "Some muscle aches in my legs"})
    assert r.json()["escalation"] == "routine"
    with db() as conn:
        c = conn.execute("SELECT escalation_reason FROM companion_checkins WHERE id = %s", (cid,)).fetchone()
    assert "possible side effect" in c["escalation_reason"] and "muscle aches" in c["escalation_reason"]


@pytest.mark.parametrize("note,level,crisis", [
    ("Crushing chest pain and my left arm hurts", "emergency", False),
    ("I just want to die", "crisis", True),
])
def test_emergency_in_checkin_is_urgent(client, note, level, crisis):
    cid = open_checkin()
    r = client.post(f"/api/companion/checkins/{cid}/answer", headers=MAYA, json={"response": "same", "note": note})
    body = r.json()
    assert r.status_code == 200 and body["escalation"] == "urgent"
    assert body["emergency"]["emergency_number"] and body["emergency"]["care_team_notified"]
    assert (body["emergency"]["crisis_line"] is not None) is crisis
    with db() as conn:
        item = conn.execute("SELECT kind, priority FROM review_items WHERE ref_id = %s", (cid,)).fetchone()
        c = conn.execute("SELECT screen_level, status FROM companion_checkins WHERE id = %s", (cid,)).fetchone()
        alert = conn.execute("SELECT priority FROM notifications WHERE dedupe_key = %s", (f"checkin-escalation:{cid}",)).fetchone()
    assert item == {"kind": "red_flag", "priority": "urgent"}
    assert c == {"screen_level": level, "status": "answered"} and alert["priority"] == "urgent"
    assert any(a["action"] == "red_flag_escalation" and a["agent"] == "safety/red-flags" for a in audit_actions(P_MAYA))
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert queue[0]["priority"] == "urgent" and queue[0]["patient_id"] == P_MAYA
    events = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()["events"]
    assert any(e["type"] == "companion_escalation" and e["tone"] == "alert" for e in events)


# --- Results, care gaps, daily brief ---------------------------------------------------------------


def test_results_ready_after_release(client):
    item = next(i for i in client.get("/api/clinician/review-queue", headers=OKAFOR).json()
                if i["kind"] == "result_explanation")
    now = datetime.now(UTC) + timedelta(minutes=1)
    before, _ = run_twice("companion_results", now)
    assert notes(U_PARK, "result:") == []                              # not released yet
    client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "approve"})
    first, second = run_twice("companion_results", now)
    assert first["created"] == 1 and second["created"] == 0
    [n] = notes(U_PARK, "result:")
    assert n["title"] == "New results are ready" and n["kind"] == "results_ready" and n["link"].startswith("/results/")
    assert "HbA1c" not in n["title"] + n["body"]


def test_care_gap_nudges_weekly_and_once_per_gap(client):
    now = at(days(0), 11, 0).astimezone(UTC)
    first, second = run_twice("companion_care_gaps", now)
    assert second["created"] == 0
    maya = notes(U_MAYA, "gap:")
    assert len(maya) == 1 and maya[0]["link"] == "/wellness" and maya[0]["title"].endswith("may be due")
    week2, _ = run_twice("companion_care_gaps", now + timedelta(days=7))
    maya2 = notes(U_MAYA, "gap:")
    assert len(maya2) == 2
    rules = [n["dedupe_key"].split(":")[1] for n in maya2]
    assert rules[0] != rules[1]                                        # the same gap waits 30 days
    with db() as conn:
        conn.execute("INSERT INTO companion_settings (patient_id, care_gap_nudges) VALUES (%s, false)", (P_PARK,))
    run_twice("companion_care_gaps", now + timedelta(days=14))
    assert len(notes(U_PARK, "gap:")) == 2


def test_daily_brief_opt_in(client):
    first, second = run_twice("companion_daily_brief", at(days(0), 7, 40).astimezone(UTC))
    assert first == {"created": 1, "opted_in": 1} and second["created"] == 0
    [n] = notes(U_MAYA, "brief:")
    assert n["due_at"] == at(days(0), 7, 30) and "Tip:" in n["body"] and "1 medicine dose" in n["body"]
    assert "Amlodipine" not in n["body"]
    late, _ = run_twice("companion_daily_brief", at(days(1), 11, 0).astimezone(UTC))
    assert late["created"] == 0                                        # more than two hours late: skipped


# --- Settings --------------------------------------------------------------------------------------


def test_settings_change_times_and_turn_off(client):
    now = at(days(0), 7, 30).astimezone(UTC)
    run_twice("medication_reminders", now)
    s = client.get("/api/companion/settings", headers=MAYA).json()
    payload = {k: s[k] for k in ("medication_reminders", "appointment_reminders", "checkins", "results_ready",
                                  "care_gap_nudges", "daily_brief", "daily_brief_time", "dose_times")}
    assert client.put("/api/companion/settings", headers=MAYA, json={**payload, "daily_brief_time": "7am"}).status_code == 422
    assert client.put("/api/companion/settings", headers=MAYA,
                      json={**payload, "dose_times": {"lunch": "12:00"}}).status_code == 422
    assert client.put("/api/companion/settings", headers=MAYA,
                      json={**payload, "medication_times": {RX_HADDAD_AMLO: ["07:00"]}}).status_code == 422
    r = client.put("/api/companion/settings", headers=MAYA,
                   json={**payload, "medication_times": {RX_MAYA_AMLO: ["07:45"]}})
    assert r.status_code == 200
    assert next(m for m in r.json()["medications"] if m["rx_id"] == RX_MAYA_AMLO)["times"] == ["07:45"]
    statuses = {n["dedupe_key"][-5:]: n["status"] for n in notes(U_MAYA, "med:")}
    assert statuses == {"08:00": "cancelled"}
    run_twice("medication_reminders", now)
    assert {n["dedupe_key"][-5:]: n["status"] for n in notes(U_MAYA, "med:")}["07:45"] == "pending"

    client.put("/api/companion/settings", headers=MAYA, json={**payload, "medication_reminders": False})
    assert {n["status"] for n in notes(U_MAYA, "med:")} == {"cancelled"}
    run_twice("medication_reminders", now + timedelta(days=1))
    assert {n["status"] for n in notes(U_MAYA, "med:")} == {"cancelled"}
    assert any(a["action"] == "companion_settings_updated" for a in audit_actions(P_MAYA))


# --- Access control, clinician views, intents ------------------------------------------------------


def test_access_control(client):
    assert client.get("/api/companion/today", headers=OKAFOR).status_code == 403
    assert client.get("/api/companion/today", headers=ADMIN).status_code == 403
    assert client.get("/api/companion/today").status_code == 401
    assert client.get(f"/api/companion/adherence?patient_id={P_HADDAD}", headers=MAYA).status_code == 403
    assert client.get("/api/companion/adherence", headers=OKAFOR).status_code == 400
    assert client.get("/api/companion/adherence?patient_id=nope", headers=OKAFOR).status_code == 404
    assert client.post(f"/api/companion/checkins/{CHECKIN_VISIT}/answer", headers=PARK,
                       json={"response": "better"}).status_code == 404
    assert client.get("/api/companion/clinician/escalations", headers=MAYA).status_code == 403
    assert client.get(f"/api/companion/patients/{P_MAYA}/between-visits", headers=MAYA).status_code == 403
    assert client.put("/api/companion/settings", headers=OKAFOR, json={}).status_code == 403

    bv = client.get(f"/api/companion/patients/{P_MAYA}/between-visits", headers=OKAFOR)
    assert bv.status_code == 200
    data = bv.json()
    assert data["adherence"]["last_7"]["pct"] == 86 and data["counts"]["answered"] >= 1
    viewed = [a for a in audit_actions(P_MAYA) if a["action"] == "companion_summary_viewed"]
    assert viewed and viewed[0]["actor_user_id"] is not None


def test_brief_bullets_from_companion(client):
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    texts = [b["text"] for b in brief["bullets"]]
    assert any(t.startswith("Amlodipine 5 mg: took 6 of 7 scheduled doses in the last 7 days (1 not recorded)")
               for t in texts)
    assert "Reported feeling better on day 3 of Amlodipine 5 mg." in texts
    assert "Missed doses" not in brief["attention_flags"]
    assert "Low medication adherence" not in brief["attention_flags"]


@pytest.mark.parametrize("text,intent", [
    ("remind me to take my medicine", "companion"),
    ("Did I take my pill today?", "companion"),
    ("have I already taken my meds", "companion"),
    ("turn on medication reminders", "companion"),
    ("I need a refill", "pharmacy"),
    ("did I take my pill, I feel dizzy", "symptom"),
    ("I took two pills by mistake and my chest hurts", "symptom"),
])
def test_companion_intent(text, intent):
    assert rules_triage([{"role": "user", "content": text}], {}).intent == intent, text
