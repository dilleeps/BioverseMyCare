"""Weight coach: guardrails, the eating screen that routes to the care team, weigh-ins in observations,
BMI from the latest height, the weekly check-in job and access control."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

from bioverse.jobs import run_job
from bioverse.routers.weight import check_goal, min_target_kg, score_scoff
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

NO = {"sick": False, "control": False, "one_stone": False, "fat": False, "food": False}


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def rejected(*args) -> str:
    with pytest.raises(HTTPException) as exc:
        check_goal(*args)
    assert exc.value.status_code == 422
    return exc.value.detail


# --- Guardrails ---------------------------------------------------------------------------------------------------


def test_bmi_floor_and_pace_limit():
    floor = min_target_kg(165)                 # 18.5 * 1.65^2 = 50.37 -> 50.4
    assert floor == 50.4
    check_goal(78, 165, floor, 1.0)            # exactly at the floor and the fastest pace: allowed
    assert "50.4 kg" in rejected(78, 165, floor - 0.1, 0.5)
    assert "1 kg a week" in rejected(78, 165, 70, 1.01)
    assert "below the healthy range" in rejected(49, 165, 45, 0.5)   # BMI 18.0 already: no loss goal
    assert "below your current weight" in rejected(70, 165, 70, 0.5)


def test_scoff_scoring():
    assert score_scoff(NO) == (0, False)
    assert score_scoff({**NO, "control": True}) == (1, False)
    assert score_scoff({**NO, "control": True, "food": True}) == (2, True)
    with pytest.raises(ValueError):
        score_scoff({"sick": False})


def test_api_enforces_guardrails(client):
    sid = client.post(f"/api/weight/patients/{P_PARK}/screening", headers=PARK, json={"answers": NO}).json()["id"]
    goal = lambda **b: client.post(f"/api/weight/patients/{P_PARK}/goal", headers=PARK, json={"screening_id": sid, **b})  # noqa: E731
    assert goal(target_weight_kg=70, pace_kg_week=0.5).status_code == 422          # no weigh-in yet
    client.post(f"/api/weight/patients/{P_PARK}/weigh-ins", headers=PARK, json={"weight_kg": 82})
    assert "height" in goal(target_weight_kg=70, pace_kg_week=0.5).json()["detail"]
    client.post(f"/api/weight/patients/{P_PARK}/height", headers=PARK, json={"height_cm": 175})
    assert goal(target_weight_kg=70, pace_kg_week=1.5).status_code == 422
    assert goal(target_weight_kg=55, pace_kg_week=0.5).status_code == 422          # BMI 18.0
    ok = goal(target_weight_kg=75, pace_kg_week=0.5)
    assert ok.status_code == 201, ok.text
    g = ok.json()["goal"]
    assert (g["start_weight_kg"], g["target_weight_kg"], g["remaining_kg"], g["weeks_left"]) == (82, 75, 7, 14)
    assert goal(target_weight_kg=74, pace_kg_week=0.5).status_code == 409          # one active goal


# --- Eating screen ----------------------------------------------------------------------------------------------------


def test_positive_screen_routes_to_care_team_instead_of_coaching(client):
    r = client.post(f"/api/weight/patients/{P_MAYA}/screening", headers=MAYA,
                    json={"answers": {**NO, "control": True, "food": True}})
    body = r.json()
    assert body["positive"] and body["routed_to_care_team"] and body["support"]["crisis_line"] == "988"
    client.post(f"/api/weight/patients/{P_MAYA}/goal/stop", headers=MAYA)
    refused = client.post(f"/api/weight/patients/{P_MAYA}/goal", headers=MAYA,
                          json={"screening_id": body["id"], "target_weight_kg": 70, "pace_kg_week": 0.5})
    assert refused.status_code == 409 and refused.json()["detail"]["state"] == "paused_for_review"
    view = client.get(f"/api/weight/patients/{P_MAYA}", headers=MAYA).json()
    assert view["screening"]["state"] == "paused_for_review" and view["can_set_goal"] is False and view["routed_message"]

    with db() as conn:
        item = conn.execute("SELECT id::text, priority, link FROM review_items WHERE kind = 'weight_screen'").fetchone()
    assert item["link"] == f"/clinician/nutrition/{P_MAYA}" and item["priority"] == "routine"
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Eating screen positive" in brief["attention_flags"]

    assert client.post(f"/api/weight/review-items/{item['id']}/resolve", headers=MAYA, json={"action": "clear"}).status_code == 403
    assert client.post(f"/api/weight/review-items/{item['id']}/resolve", headers=OKAFOR,
                       json={"action": "acknowledge"}).status_code == 422
    assert client.post(f"/api/weight/review-items/{item['id']}/resolve", headers=OKAFOR,
                       json={"action": "clear", "note": "Discussed; fine to proceed slowly"}).status_code == 200
    assert client.get(f"/api/weight/patients/{P_MAYA}", headers=MAYA).json()["screening"]["state"] == "cleared"
    ok = client.post(f"/api/weight/patients/{P_MAYA}/goal", headers=MAYA,
                     json={"screening_id": body["id"], "target_weight_kg": 72, "pace_kg_week": 0.25})
    assert ok.status_code == 201


def test_keeping_coaching_paused(client):
    body = client.post(f"/api/weight/patients/{P_PARK}/screening", headers=PARK,
                       json={"answers": {**NO, "sick": True, "fat": True}}).json()
    with db() as conn:
        item = conn.execute("SELECT id::text FROM review_items WHERE kind = 'weight_screen'").fetchone()
    client.post(f"/api/weight/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "keep_paused"})
    view = client.get(f"/api/weight/patients/{P_PARK}", headers=PARK).json()
    assert view["screening"]["state"] == "declined_by_care_team" and not view["can_set_goal"]
    assert body["id"]


# --- Weigh-ins -------------------------------------------------------------------------------------------------------


def test_weigh_ins_live_in_observations_and_other_sources_count(client):
    r = client.post(f"/api/weight/patients/{P_MAYA}/weigh-ins", headers=MAYA, json={"weight_kg": 77.46})
    assert r.status_code == 201
    with db() as conn:
        row = conn.execute(
            """SELECT loinc_code, unit, category, source, value FROM observations
               WHERE patient_id = %s AND loinc_code = '29463-7' ORDER BY effective_at DESC LIMIT 1""", (P_MAYA,)).fetchone()
        assert row == {"loinc_code": "29463-7", "unit": "kg", "category": "vital-signs", "source": "manual", "value": 77.5}
        conn.execute(
            """INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                         category, source, device)
               VALUES (%s, '29463-7', 'Body weight', 77.1, 'kg', 'N', now() + interval '1 minute', 'vital-signs', 'device', 'Demo scale')""",
            (P_MAYA,))
        conn.commit()
    view = client.get(f"/api/weight/patients/{P_MAYA}", headers=MAYA).json()
    assert view["latest"]["value"] == 77.1 and view["latest"]["source"] == "device"
    assert view["bmi"] == round(77.1 / 1.65 ** 2, 1) and view["height"]["value"] == 165
    assert len(view["weigh_ins"]) == 6
    assert view["weekly"][-1]["average"] <= 78
    # A device reading can't be deleted by the patient; their own typed one can.
    device = view["weigh_ins"][-1]["id"]
    assert client.delete(f"/api/weight/patients/{P_MAYA}/weigh-ins/{device}", headers=MAYA).status_code == 404
    assert client.post(f"/api/weight/patients/{P_MAYA}/weigh-ins", headers=MAYA, json={"weight_kg": 10}).status_code == 422


def test_seeded_goal_and_trend(client):
    view = client.get(f"/api/weight/patients/{P_MAYA}", headers=MAYA).json()
    assert [w["value"] for w in view["weigh_ins"]] == [79.2, 78.8, 78.3, 77.9]
    g = view["goal"]
    assert g["status"] == "active" and g["target_weight_kg"] == 72 and g["pace_kg_week"] == 0.5
    assert g["percent"] == round(100 * (79.2 - 77.9) / (79.2 - 72))
    assert view["guardrails"]["min_target_kg"] == 50.4


def test_weekly_check_in_job_notifies_once(client):
    now = datetime.now(timezone.utc)
    with db() as conn:
        first = run_job(conn, "weight_coach_weekly", now)["detail"]
        again = run_job(conn, "weight_coach_weekly", now)["detail"]
        assert first["checkins"] == 1 and again["checkins"] == 0
        n = conn.execute("SELECT title, link FROM notifications WHERE kind = 'weight_coach'").fetchall()
        assert n == [{"title": "Your weekly weight check-in", "link": "/weight"}]
        c = conn.execute("SELECT message FROM weight_checkins").fetchone()
        assert c["message"]
        nxt = run_job(conn, "weight_coach_weekly", now + timedelta(days=7))["detail"]
        assert nxt["checkins"] == 1
    view = client.get(f"/api/weight/patients/{P_MAYA}", headers=MAYA).json()
    assert len(view["checkins"]) == 2


def test_access_control(client):
    assert client.get(f"/api/weight/patients/{P_MAYA}", headers=PARK).status_code == 403
    assert client.post(f"/api/weight/patients/{P_MAYA}/weigh-ins", headers=OKAFOR, json={"weight_kg": 70}).status_code == 403
    assert client.post(f"/api/weight/patients/{P_MAYA}/screening", headers=PARK, json={"answers": NO}).status_code == 403
    assert client.get(f"/api/weight/patients/{P_MAYA}", headers=OKAFOR).status_code == 200
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'weight_viewed'").fetchone()["n"] == 1
