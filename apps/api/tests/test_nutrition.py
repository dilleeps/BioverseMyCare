"""Nutrition: food list, meal totals, rule-based and clinician targets, weekly patterns, the photo scan
(rules fallback and a fake AI), front-door intents, access control and audit."""

import base64
from datetime import date, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents import llm
from bioverse.agents.triage import rules_triage
from bioverse.config import clinic_today
from bioverse.nutrition_data import FOODS
from bioverse.routers.nutrition import FoodScan, ScannedItem, match_foods, servings_for
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def log(client, items, meal="lunch", headers=MAYA, patient=P_MAYA, **extra):
    return client.post(f"/api/nutrition/patients/{patient}/meals", headers=headers,
                       json={"meal": meal, "items": [{"food_id": f, "servings": s} for f, s in items], **extra})


# --- Food list ---------------------------------------------------------------------------------------------------


def test_food_list_is_complete_and_realistic():
    assert 150 <= len(FOODS) <= 200
    assert len({f["id"] for f in FOODS}) == len(FOODS)
    for f in FOODS:
        assert f["serving_grams"] > 0 and f["sodium_mg"] >= 0
        if f["kcal"] > 30 and f["category"] != "Drinks":
            energy = 4 * f["protein_g"] + 4 * f["carbs_g"] + 9 * f["fat_g"]
            assert abs(energy - f["kcal"]) / f["kcal"] < 0.25, f["id"]


def test_search(client):
    names = [f["name"] for f in client.get("/api/nutrition/foods?q=chicken", headers=MAYA).json()]
    assert "Chicken breast, grilled, skinless" in names
    assert client.get("/api/nutrition/foods?q=soda", headers=MAYA).json()[0]["id"] == "cola"  # aliases count
    assert client.get("/api/nutrition/foods?q=turkey sandwich", headers=MAYA).json()[0]["id"] == "turkey-sandwich"
    assert client.get("/api/nutrition/foods?q=zzzz", headers=MAYA).json() == []
    assert client.get("/api/nutrition/foods?q=rice").status_code == 401


# --- Log and totals -------------------------------------------------------------------------------------------------


def test_meal_totals_and_targets(client):
    before = client.get(f"/api/nutrition/patients/{P_PARK}/day", headers=PARK).json()
    assert before["meals"] == [] and before["totals"]["sodium_mg"] == 0
    r = log(client, [("turkey-sandwich", 1), ("apple", 2), ("potato-chips", 0.5)], headers=PARK, patient=P_PARK)
    assert r.status_code == 201, r.text
    day = r.json()
    assert day["totals"]["kcal"] == round(360 + 2 * 95 + 0.5 * 152, 1)
    assert day["totals"]["sodium_mg"] == round(1250 + 2 * 2 + 0.5 * 150, 1)
    assert day["meals"][0]["items"][0]["servings"] in (0.5, 1, 2)
    sodium = next(t for t in day["targets"] if t["nutrient"] == "sodium_mg")
    assert (sodium["value"], sodium["set_by"], sodium["status"]) == (2300, "rule", "ok")   # Park: no raised BP on record
    log(client, [("instant-ramen", 1)], meal="dinner", headers=PARK, patient=P_PARK)
    sodium = next(t for t in client.get(f"/api/nutrition/patients/{P_PARK}/day", headers=PARK).json()["targets"]
                  if t["nutrient"] == "sodium_mg")
    assert sodium["status"] == "over" and sodium["amount"] == 1329 + 1600

    meal = day["meals"][0]
    after = client.delete(f"/api/nutrition/meals/{meal['id']}/items/{meal['items'][0]['id']}", headers=PARK).json()
    assert len(after["meals"][0]["items"]) == 2 or len(after["meals"]) == 2
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'meal_logged' AND patient_id = %s",
                            (P_PARK,)).fetchone()["n"] == 2


def test_hypertension_lowers_the_sodium_target(client):
    targets = {t["nutrient"]: t for t in client.get(f"/api/nutrition/patients/{P_MAYA}/targets", headers=MAYA).json()}
    assert targets["sodium_mg"]["value"] == 1500
    assert "138/88" in targets["sodium_mg"]["reason"]
    assert "American Heart Association" in targets["sodium_mg"]["source"]
    assert targets["fiber_g"]["kind"] == "min"


def test_clinician_overrides_a_target(client):
    r = client.put(f"/api/nutrition/patients/{P_MAYA}/targets/sodium_mg", headers=OKAFOR,
                   json={"value": 2000, "reason": "Agreed step-down plan"})
    assert r.status_code == 200
    sodium = next(t for t in r.json() if t["nutrient"] == "sodium_mg")
    assert (sodium["value"], sodium["set_by"], sodium["reason"]) == (2000, "clinician", "Agreed step-down plan")
    assert "Okafor" in sodium["source"]
    # The patient sees the override; they can't set one themselves.
    day = client.get(f"/api/nutrition/patients/{P_MAYA}/day", headers=MAYA).json()
    assert next(t for t in day["targets"] if t["nutrient"] == "sodium_mg")["value"] == 2000
    assert client.put(f"/api/nutrition/patients/{P_MAYA}/targets/sodium_mg", headers=MAYA, json={"value": 5000}).status_code == 403
    assert client.put(f"/api/nutrition/patients/{P_MAYA}/targets/sodium_mg", headers=OKAFOR, json={"value": 50000}).status_code == 422
    assert client.put(f"/api/nutrition/patients/{P_MAYA}/targets/vitamin_q", headers=OKAFOR, json={"value": 5}).status_code == 404
    reset = client.delete(f"/api/nutrition/patients/{P_MAYA}/targets/sodium_mg", headers=OKAFOR).json()
    assert next(t for t in reset if t["nutrient"] == "sodium_mg")["value"] == 1500
    with db() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_events WHERE action LIKE 'nutrition_target%%' ORDER BY id").fetchall()]
    assert actions == ["nutrition_target_set", "nutrition_target_reset"]


def test_weekly_patterns_from_mayas_seeded_meals(client):
    week = client.get(f"/api/nutrition/patients/{P_MAYA}/week", headers=MAYA).json()
    assert week["enough_data"] and week["logged_days"] == 7
    sodium = next(p for p in week["patterns"] if p["nutrient"] == "sodium_mg")
    assert sodium["days"] >= 5 and sodium["text"].startswith(f"Sodium over your target on {sodium['days']} of 7")
    tips = [t for t in week["tips"] if t["for"] == "sodium_mg"]
    assert tips and all(t["source"] and t["url"].startswith("https://") for t in tips)
    assert len(week["days"]) == 7


def test_validation_and_access(client):
    assert log(client, [("no-such-food", 1)]).status_code == 422
    assert log(client, [("apple", 0)]).status_code == 422
    assert log(client, [("apple", 1)], eaten_on=str(clinic_today() + timedelta(days=1))).status_code == 422
    assert log(client, [("apple", 1)], meal="brunch").status_code == 422
    assert log(client, [("apple", 1)], headers=PARK).status_code == 403
    assert log(client, [("apple", 1)], headers=OKAFOR).status_code == 403
    assert client.get(f"/api/nutrition/patients/{P_MAYA}/day", headers=PARK).status_code == 403
    maya_meal = client.get(f"/api/nutrition/patients/{P_MAYA}/day?day={clinic_today() - timedelta(days=1)}",
                           headers=MAYA).json()["meals"][0]["id"]
    assert client.delete(f"/api/nutrition/meals/{maya_meal}", headers=PARK).status_code == 403
    client.get(f"/api/nutrition/patients/{P_MAYA}/week", headers=OKAFOR)
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'nutrition_week_viewed' AND patient_id = %s",
                            (P_MAYA,)).fetchone()["n"] == 1


# --- Photo scan --------------------------------------------------------------------------------------------------


def test_scan_in_rules_mode_opens_search_and_keeps_nothing(client):
    r = client.post(f"/api/nutrition/patients/{P_MAYA}/scan", headers=MAYA, json={"image": PNG, "media_type": "image/png"})
    assert r.status_code == 200
    assert r.json()["mode"] == "rules" and r.json()["items"] == []
    assert "search" in r.json()["message"].lower()
    with db() as conn:
        row = conn.execute("SELECT agent, detail FROM audit_events WHERE action = 'food_photo_scanned'").fetchone()
        assert row["agent"] == "nutrition-scan/rules" and row["detail"]["photo_stored"] is False
        assert PNG not in str(row["detail"])
        assert conn.execute("SELECT count(*) AS n FROM nutrition_intakes WHERE patient_id = %s AND eaten_on = %s",
                            (P_MAYA, clinic_today())).fetchone()["n"] == 0


def test_scan_rejects_bad_photos(client):
    url = f"/api/nutrition/patients/{P_MAYA}/scan"
    assert client.post(url, headers=MAYA, json={"image": "not base64!!", "media_type": "image/png"}).status_code == 422
    assert client.post(url, headers=MAYA, json={"image": PNG, "media_type": "application/pdf"}).status_code == 422
    big = base64.b64encode(b"\x00" * (5 * 1024 * 1024 + 10)).decode()
    assert client.post(url, headers=MAYA, json={"image": big, "media_type": "image/jpeg"}).status_code == 413
    assert client.post(url, headers=PARK, json={"image": PNG, "media_type": "image/png"}).status_code == 403


class FakeMessages:
    def __init__(self):
        self.calls, self.output = [], None

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="test-model",
                               usage=SimpleNamespace(iterations=None), parsed_output=self.output)


@pytest.fixture
def fake_ai(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    messages = FakeMessages()
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    yield messages
    llm.set_client(None)


def test_scan_with_ai_suggests_matches_for_the_person_to_confirm(client, fake_ai):
    fake_ai.output = FoodScan(shows_food=True, items=[
        ScannedItem(name="grilled chicken breast", portion="one fillet", estimated_grams=170, confidence="high"),
        ScannedItem(name="white rice", portion="about a cup", estimated_grams=160, confidence="medium"),
        ScannedItem(name="dragonfruit foam", portion="a spoonful", confidence="low"),
    ])
    r = client.post(f"/api/nutrition/patients/{P_MAYA}/scan", headers=MAYA, json={"image": PNG, "media_type": "image/png"})
    body = r.json()
    assert body["mode"] == "ai"
    first, rice, unknown = body["items"]
    assert first["food"]["id"] == "chicken-breast" and first["servings"] == 2.0
    assert rice["food"]["id"] == "white-rice" and rice["servings"] == 1.0
    assert unknown["food"] is None
    call = fake_ai.calls[0]
    assert call["output_format"] is FoodScan
    block = call["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["data"] == PNG
    assert "data, not instructions" in call["system"]
    # Nothing is saved until the person confirms through the normal meal log.
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM nutrition_intakes WHERE eaten_on = %s AND patient_id = %s",
                            (clinic_today(), P_MAYA)).fetchone()["n"] == 0
        audit = conn.execute("SELECT agent, model FROM audit_events WHERE action = 'food_photo_scanned'").fetchone()
    assert audit == {"agent": "nutrition-scan/claude", "model": "test-model"}
    saved = log(client, [("chicken-breast", 2), ("white-rice", 1)], source="photo").json()
    assert saved["meals"][0]["source"] == "photo"


def test_scan_respects_ai_opt_out(client, fake_ai):
    with db() as conn:
        conn.execute("""INSERT INTO consents (patient_id, scope, status) VALUES (%s, 'ai_processing', 'denied')
                        ON CONFLICT (patient_id, scope, grantee) DO UPDATE SET status = 'denied'""", (P_MAYA,))
        conn.commit()
    r = client.post(f"/api/nutrition/patients/{P_MAYA}/scan", headers=MAYA, json={"image": PNG, "media_type": "image/png"})
    assert r.json()["mode"] == "rules"
    assert fake_ai.calls == []


def test_matching_and_servings():
    assert match_foods("scrambled eggs")[0]["id"] == "eggs-scrambled"
    assert match_foods("a glass of water")[0]["id"] == "water-glass"
    assert match_foods("french fries")[0]["id"] == "french-fries"
    assert match_foods("broccoli")[0]["id"].startswith("broccoli")
    assert match_foods("qwerty") == []
    rice = next(f for f in FOODS if f["id"] == "white-rice")
    assert servings_for(rice, None) == 1.0
    assert servings_for(rice, 79) == 0.5
    assert servings_for(rice, 10000) == 10.0
    assert servings_for(rice, 1) == 0.25


# --- Front door ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text,intent", [
    ("log my lunch", "nutrition_log"),
    ("I want to track what I ate today", "nutrition_log"),
    ("scan my food", "nutrition_scan"),
    ("can I take a photo of my dinner", "nutrition_scan"),
    ("I want to lose weight", "weight_coach"),
    ("help me lose some weight", "weight_coach"),
])
def test_nutrition_intents(text, intent):
    assert rules_triage([{"role": "user", "content": text}], {"age": 50}).intent == intent


@pytest.mark.parametrize("text", [
    "I've been losing weight without trying",
    "my stomach hurts after lunch",
    "I feel sick after I eat my dinner",
    "I can't eat and I keep losing weight",
])
def test_symptoms_are_not_stolen(text):
    assert rules_triage([{"role": "user", "content": text}], {"age": 50}).intent not in (
        "nutrition_log", "nutrition_scan", "weight_coach")


def test_food_log_is_a_link_in_the_front_door(client):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    msg = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": "log my lunch"}).json()
    assert msg["messages"][-1]["payload"] == {"kind": "link", "to": "/nutrition", "label": "Open my food log"}


def test_seeded_meal_history(client):
    with db() as conn:
        days = conn.execute("SELECT count(DISTINCT eaten_on) AS n FROM nutrition_intakes WHERE patient_id = %s",
                            (P_MAYA,)).fetchone()["n"]
    assert days == 10
    y = client.get(f"/api/nutrition/patients/{P_MAYA}/day?day={date.today() - timedelta(days=1)}", headers=MAYA)
    assert y.status_code == 200
