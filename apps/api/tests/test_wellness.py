"""Wellness and prevention: preventive rules on known ages and dates, care-gap sync, goals math, assessment."""

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from bioverse import prevention
from bioverse.agents.triage import rules_triage
from bioverse.db.seed import DR_OKAFOR
from bioverse.routers.wellness import AssessmentIn, assess, milestones, progress
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, PARK

TODAY = date(2026, 9, 24)


def born(age_years: int, today: date = TODAY) -> date:
    return date(today.year - age_years, 1, 1)


def record(age: int, sex: str | None = "female", **kw) -> prevention.Record:
    return prevention.Record(birth_date=born(age), sex=sex, **kw)


def at(days_ago: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time(), tzinfo=timezone.utc)


def items(rec: prevention.Record) -> dict[str, dict]:
    return {i["rule_id"]: i for i in prevention.evaluate(rec, TODAY)["items"]}


def enc(days_ago: int, summary: str, kind: str = "Visit") -> dict:
    return {"id": f"e{days_ago}", "kind": kind, "summary": summary, "occurred_at": at(days_ago)}


def imm(days_ago: int, vaccine: str) -> dict:
    return {"id": f"i{days_ago}{vaccine[:3]}", "vaccine": vaccine, "occurred_at": at(days_ago)}


def obs(days_ago: int, loinc: str, value: float, interp: str) -> dict:
    return {"id": f"o{days_ago}{loinc}", "report_id": f"r{days_ago}", "loinc_code": loinc, "display": loinc,
            "value": value, "interpretation": interp, "effective_at": at(days_ago)}


# --- Rules on known ages and dates --------------------------------------------------------------------


def test_blood_pressure_rule_matches_mayas_overdue_gap():
    # Maya: 54, last reading 194 days ago was 138/88, which is elevated -> 6-month recheck -> overdue.
    bp = items(record(54, encounters=[enc(194, "BP 138/88. Lipid panel ordered.")]))["bp_check"]
    assert bp["status"] == "overdue"
    assert bp["interval"] == "6 months"
    assert bp["last_date"] == TODAY - timedelta(days=194)
    assert "USPSTF" in bp["source"] and bp["source"].startswith("Illustrative")

    normal = items(record(54, encounters=[enc(194, "BP 118/76.")]))["bp_check"]
    assert normal["status"] == "up_to_date"
    assert normal["next_due"] == prevention.add_months(TODAY - timedelta(days=194), 12)

    assert "bp_check" not in items(record(39))
    assert items(record(40))["bp_check"]["status"] == "due"


def test_lipid_interval_depends_on_ldl():
    high = items(record(54, observations=[obs(2, "13457-7", 148, "H")]))["lipid_panel"]
    assert high["status"] == "up_to_date" and high["interval"] == "year"
    assert items(record(54, observations=[obs(4 * 365, "13457-7", 90, "N")]))["lipid_panel"]["status"] == "up_to_date"
    assert items(record(54, observations=[obs(6 * 365, "13457-7", 90, "N")]))["lipid_panel"]["status"] == "overdue"
    # An encounter note that a panel was ordered is not evidence it was done.
    assert items(record(54, encounters=[enc(30, "Lipid panel ordered.")]))["lipid_panel"]["status"] == "due"
    assert "lipid_panel" not in items(record(76))


def test_colorectal_band_and_test_type_intervals():
    assert "colorectal" not in items(record(44))
    assert items(record(45))["colorectal"]["status"] == "due"
    assert "colorectal" not in items(record(76))
    colonoscopy = items(record(60, encounters=[enc(5 * 365, "Normal.", kind="Colonoscopy")]))["colorectal"]
    assert colonoscopy["status"] == "up_to_date" and colonoscopy["interval"] == "10 years"
    fit = prevention.Record(birth_date=born(60), sex="male",
                            reports=[{"id": "r1", "name": "FIT stool test", "collected_at": at(400)}])
    assert items(fit)["colorectal"]["status"] == "overdue"


def test_sex_specific_screenings():
    female = items(record(54))
    assert female["cervical"]["status"] == "due" and female["breast"]["status"] == "due"
    male = items(record(54, sex="male"))
    assert "cervical" not in male and "breast" not in male
    unknown = prevention.evaluate(record(54, sex=None), TODAY)
    ids = {i["rule_id"] for i in unknown["items"]}
    assert "cervical" not in ids and "breast" not in ids
    assert any("sex assigned at birth" in n for n in unknown["notes"])
    assert "cervical" not in items(record(66))
    assert "breast" not in items(record(39))


def test_vaccine_rules():
    assert items(record(30, immunizations=[imm(90, "Influenza vaccine")]))["influenza"]["status"] == "up_to_date"
    assert items(record(30, immunizations=[imm(340, "Influenza vaccine")]))["influenza"]["status"] == "due"
    assert items(record(30, immunizations=[imm(400, "Flu shot")]))["influenza"]["status"] == "overdue"

    assert items(record(30, immunizations=[imm(9 * 365, "Tdap")]))["td_tdap"]["status"] == "up_to_date"
    assert items(record(30, immunizations=[imm(11 * 365, "Td booster")]))["td_tdap"]["status"] == "overdue"

    assert "shingles" not in items(record(49))
    one = items(record(55, immunizations=[imm(60, "Shingrix (zoster) dose 1")]))["shingles"]
    assert one["status"] == "due" and "1 of 2" in one["detail"]
    two = items(record(55, immunizations=[imm(60, "Shingrix dose 2"), imm(200, "Shingrix dose 1")]))["shingles"]
    assert two["status"] == "up_to_date"

    assert items(record(66))["pneumococcal"]["status"] == "due"
    assert "pneumococcal" not in items(record(50))
    diabetic = record(50, observations=[obs(30, "4548-4", 7.1, "H")])
    assert items(diabetic)["pneumococcal"]["status"] == "due"
    assert items(record(70, immunizations=[imm(700, "Pneumococcal conjugate vaccine (PCV20)")]))["pneumococcal"]["status"] == "up_to_date"


def test_add_months_clamps_to_month_end():
    assert prevention.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert prevention.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert prevention.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


# --- API: checklist and care-gap sync ----------------------------------------------------------------


def test_mayas_checklist_from_the_record(client):
    body = client.get(f"/api/wellness/patients/{P_MAYA}/prevention", headers=MAYA).json()
    by_id = {i["rule_id"]: i for i in body["items"]}
    assert body["ruleset"] == prevention.RULESET_VERSION
    assert "not medical advice" in body["disclaimer"]
    assert by_id["bp_check"]["status"] == "overdue"
    assert by_id["lipid_panel"]["status"] == "up_to_date"
    assert by_id["influenza"]["status"] == "up_to_date"
    assert by_id["colorectal"]["status"] == "due"
    assert body["items"][0]["rule_id"] == "bp_check", "overdue items come first"


def test_prevention_access_control(client):
    assert client.get(f"/api/wellness/patients/{P_MAYA}/prevention", headers=PARK).status_code == 403
    assert client.post(f"/api/wellness/patients/{P_MAYA}/prevention/sync", headers=PARK).status_code == 403
    assert client.get(f"/api/wellness/patients/{P_MAYA}/prevention", headers=OKAFOR).status_code == 200


def _gaps(status: str | None = None) -> list[tuple]:
    with psycopg.connect(DB) as conn:
        q = "SELECT title, status FROM care_gaps WHERE patient_id = %s"
        rows = conn.execute(q + (" AND status = %s" if status else ""), (P_MAYA, status) if status else (P_MAYA,)).fetchall()
    return rows


def test_gap_sync_is_idempotent_and_adopts_the_existing_bp_gap(client):
    first = client.post(f"/api/wellness/patients/{P_MAYA}/prevention/sync", headers=MAYA).json()
    assert "bp_check" in [u["rule_id"] for u in first["unchanged"]], "the seeded BP gap is adopted, not duplicated"
    assert "bp_check" not in [o["rule_id"] for o in first["opened"]]
    assert {o["rule_id"] for o in first["opened"]} >= {"colorectal", "td_tdap"}
    after_first = _gaps()
    assert sum(1 for t, _ in after_first if "blood pressure" in t.lower()) == 1

    second = client.post(f"/api/wellness/patients/{P_MAYA}/prevention/sync", headers=MAYA).json()
    assert second["opened"] == [] and second["closed"] == []
    assert sorted(_gaps()) == sorted(after_first)

    # A normal reading today closes the BP gap; a tetanus shot closes that one.
    with psycopg.connect(DB) as conn:
        conn.execute("INSERT INTO encounters (patient_id, occurred_at, kind, summary) VALUES (%s, now(), 'Nurse visit', 'BP 118/76.')", (P_MAYA,))
        conn.execute("INSERT INTO immunizations (patient_id, vaccine, occurred_at) VALUES (%s, 'Tdap', now())", (P_MAYA,))
    third = client.post(f"/api/wellness/patients/{P_MAYA}/prevention/sync", headers=MAYA).json()
    assert {c["rule_id"] for c in third["closed"]} == {"bp_check", "td_tdap"}
    assert not any("blood pressure" in t.lower() for t, _ in _gaps("open"))

    # Remove the shot again: the same gap reopens instead of a new one being created.
    with psycopg.connect(DB) as conn:
        conn.execute("DELETE FROM immunizations WHERE patient_id = %s AND vaccine = 'Tdap'", (P_MAYA,))
    fourth = client.post(f"/api/wellness/patients/{P_MAYA}/prevention/sync", headers=MAYA).json()
    assert [o["rule_id"] for o in fourth["opened"]] == ["td_tdap"]
    assert sum(1 for t, _ in _gaps() if "tetanus" in t.lower()) == 1

    with psycopg.connect(DB) as conn:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_events WHERE patient_id = %s AND action LIKE 'care_gap_%%'", (P_MAYA,))]
    assert "care_gap_opened" in actions and "care_gap_closed" in actions and "care_gap_reopened" in actions


# --- Goals ------------------------------------------------------------------------------------------


def test_progress_math_on_known_entries():
    today = date(2026, 9, 24)
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    entries = {d(1): 8000, d(2): 7000, d(3): 7500, d(4): 3000, d(5): 9000, d(6): 7000, d(10): 7000, d(11): 7200}
    p = progress(7000, entries, today)
    assert p["last_7"] == {"days": 7, "logged": 6, "met": 5, "average": 6916.7, "percent_met": 71}
    assert p["last_30"]["logged"] == 8 and p["last_30"]["met"] == 7
    assert p["current_streak"] == 3, "today not logged yet: count back from yesterday"
    assert p["best_streak"] == 3
    assert [s["met"] for s in p["series"]] == [True, True, False, True, True, True, False]

    entries[today] = 7100
    assert progress(7000, entries, today)["current_streak"] == 4
    entries[today] = 100  # logged but not met yet: the day isn't over, streak stays at yesterday's
    assert progress(7000, entries, today)["current_streak"] == 3
    assert progress(7000, {}, today)["last_7"]["average"] is None


def test_streak_milestones():
    start = date(2026, 8, 1)
    entries = {start + timedelta(days=i): 8 for i in range(8)}
    entries[start + timedelta(days=8)] = 5  # broken
    entries.update({start + timedelta(days=9 + i): 8 for i in range(7)})
    assert milestones(7.5, entries) == [{"day": start + timedelta(days=6), "streak": 7},
                                        {"day": start + timedelta(days=15), "streak": 7}]


def test_goal_lifecycle_and_access(client):
    created = client.post(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA, json={"kind": "sleep_hours"})
    assert created.status_code == 201
    goal = created.json()
    assert goal["target"] == 7.5 and goal["unit"] == "hours" and goal["reported_by"] == "patient"

    today = date.today().isoformat()
    r = client.put(f"/api/wellness/goals/{goal['id']}/entries/{today}", headers=MAYA, json={"value": 6})
    assert r.status_code == 200 and r.json()["logged_today"] == 6
    r = client.put(f"/api/wellness/goals/{goal['id']}/entries/{today}", headers=MAYA, json={"value": 8})
    assert r.json()["logged_today"] == 8 and r.json()["progress"]["last_7"]["logged"] == 1, "re-logging replaces the day"

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.put(f"/api/wellness/goals/{goal['id']}/entries/{tomorrow}", headers=MAYA, json={"value": 8}).status_code == 422
    old = (date.today() - timedelta(days=61)).isoformat()
    assert client.put(f"/api/wellness/goals/{goal['id']}/entries/{old}", headers=MAYA, json={"value": 8}).status_code == 422
    assert client.put(f"/api/wellness/goals/{goal['id']}/entries/{today}", headers=MAYA, json={"value": 30}).status_code == 422

    # Only the patient writes; others can't read, clinicians can read but not write.
    assert client.put(f"/api/wellness/goals/{goal['id']}/entries/{today}", headers=PARK, json={"value": 8}).status_code == 403
    assert client.put(f"/api/wellness/goals/{goal['id']}/entries/{today}", headers=OKAFOR, json={"value": 8}).status_code == 403
    assert client.post(f"/api/wellness/patients/{P_MAYA}/goals", headers=OKAFOR, json={"kind": "steps"}).status_code == 403
    assert client.get(f"/api/wellness/patients/{P_MAYA}/goals", headers=PARK).status_code == 403
    assert client.get(f"/api/wellness/patients/{P_MAYA}/goals", headers=OKAFOR).status_code == 200

    assert client.post(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA, json={"kind": "custom"}).status_code == 422
    custom = client.post(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA,
                         json={"kind": "custom", "title": "Glasses of water", "unit": "glasses", "target": 6})
    assert custom.status_code == 201

    archived = client.patch(f"/api/wellness/goals/{goal['id']}", headers=MAYA, json={"status": "archived"})
    assert archived.json()["status"] == "archived"
    titles = [g["title"] for g in client.get(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA).json()["goals"]]
    assert titles == ["Daily steps", "Glasses of water"]


def test_seeded_goal_progress_and_timeline_milestone(client):
    goals = client.get(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA).json()["goals"]
    steps = goals[0]
    assert steps["progress"]["best_streak"] == 7
    assert steps["reported_by"] == "patient"
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    types = {e["type"] for e in story["events"]}
    assert {"goal", "goal_milestone"} <= types


# --- Assessment ----------------------------------------------------------------------------------------

BASE = {"active_days": 2, "sleep_hours": 6, "smoking": "current", "alcohol_drinks_per_week": 16, "stress": "often"}


def test_assessment_rules():
    out = assess(AssessmentIn(**BASE))
    ids = [s["id"] for s in out["suggestions"]]
    assert ids == ["activity", "sleep", "smoking", "alcohol", "stress"]
    assert out["suggested_goal"]["kind"] == "active_minutes"
    healthy = assess(AssessmentIn(active_days=6, sleep_hours=8, smoking="never", alcohol_drinks_per_week=2, stress="rarely"))
    assert [s["id"] for s in healthy["suggestions"]] == ["keep_going"]


def test_assessment_submission_goal_and_timeline(client):
    r = client.post(f"/api/wellness/patients/{P_MAYA}/assessments", headers=MAYA, json={**BASE, "notes": "Busy at work"})
    assert r.status_code == 201
    body = r.json()
    assert body["emergency"] is None and body["suggestions"]
    goal = client.post(f"/api/wellness/patients/{P_MAYA}/goals", headers=MAYA,
                       json={**body["suggested_goal"], "assessment_id": body["id"]})
    assert goal.status_code == 201 and goal.json()["source"] == "assessment"
    assert client.post(f"/api/wellness/patients/{P_MAYA}/assessments", headers=PARK, json=BASE).status_code == 403
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    assert any(e["type"] == "assessment" for e in story["events"])
    latest = client.get(f"/api/wellness/patients/{P_MAYA}/assessments/latest", headers=MAYA).json()
    assert latest["id"] == body["id"]


def test_assessment_free_text_red_flag_stops_routine_flow(client):
    r = client.post(f"/api/wellness/patients/{P_MAYA}/assessments", headers=MAYA,
                    json={**BASE, "notes": "Honestly some days I want to die"})
    body = r.json()
    assert body["emergency"]["level"] == "crisis"
    assert body["emergency"]["crisis_line"] == "988"
    assert body["suggestions"] == [] and body["suggested_goal"] is None
    assert body["emergency"]["care_team_notified"] is True
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert queue[0]["kind"] == "red_flag" and queue[0]["priority"] == "urgent"
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    assert not any(e["type"] == "assessment" for e in story["events"])
    with psycopg.connect(DB) as conn:
        assert conn.execute(
            "SELECT practitioner_id::text FROM review_items WHERE kind = 'red_flag' AND patient_id = %s "
            "ORDER BY created_at DESC LIMIT 1", (P_MAYA,)
        ).fetchone()[0] == DR_OKAFOR


def test_assessment_symptom_mention_points_to_front_door(client):
    body = client.post(f"/api/wellness/patients/{P_MAYA}/assessments", headers=MAYA,
                       json={**BASE, "notes": "I get headaches in the afternoon"}).json()
    assert body["emergency"] is None
    assert body["symptom_notice"]["to"] == "/app"


# --- Front door ---------------------------------------------------------------------------------------

PATIENT = {"age": 54, "allergies": []}


@pytest.mark.parametrize("text", [
    "Am I due for any screenings?", "Which vaccines do I need?", "I want to track my steps",
    "help me sleep better", "set a wellness goal",
])
def test_wellness_intent(text):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent == "wellness"


@pytest.mark.parametrize("text", ["I can't sleep because my back hurts", "I feel dizzy when I exercise"])
def test_wellness_intent_does_not_steal_symptoms(text):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent != "wellness"
