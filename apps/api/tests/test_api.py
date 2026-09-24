"""Whole journeys through the HTTP API against a real Postgres database."""

import copy
from types import SimpleNamespace

import psycopg
import pytest

from bioverse.agents import llm
from bioverse.agents.triage import TriageResult
from bioverse.db.seed import DR_FERREIRA
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK


def start(client):
    r = client.post("/api/conversations", headers=MAYA)
    assert r.status_code == 201
    return r.json()["id"]


def say(client, cid, **body):
    r = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def last_payload(convo):
    return convo["messages"][-1]["payload"]


def test_health_reports_rules_mode(client):
    body = client.get("/api/health").json()
    assert body["database"] == "ok"
    assert body["ai"] == "rules"


def test_identity_and_access(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-Bioverse-User": "not-a-uuid"}).status_code == 401
    assert client.get(f"/api/patients/{P_PARK}/reports", headers=MAYA).status_code == 403
    assert client.get("/api/clinician/review-queue", headers=MAYA).status_code == 403
    assert client.get(f"/api/patients/{P_MAYA}/reports", headers=OKAFOR).status_code == 200


def test_chest_journey_safety_check_then_booking(client):
    cid = start(client)
    convo = say(client, cid, text="I've had chest discomfort since yesterday")
    roles = [m["role"] for m in convo["messages"]]
    assert roles == ["user", "assistant"], "patient message must come before the reply"
    assert last_payload(convo)["kind"] == "safety_check"

    convo = say(client, cid, safety_answer=["none"])
    card = last_payload(convo)
    assert card["kind"] == "care_options"
    assert card["specialty"] == "Cardiology"

    options = client.get(f"/api/care/options?intake_id={card['intake_id']}", headers=MAYA).json()
    assert 1 <= len(options["options"]) <= 3
    slot = options["options"][0]["next_slot"]["id"]

    booked = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot, "intake_id": card["intake_id"]})
    assert booked.status_code == 201
    again = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot})
    assert again.status_code == 409

    upcoming = client.get(f"/api/patients/{P_MAYA}/appointments", headers=MAYA).json()
    assert [a["id"] for a in upcoming] == [booked.json()["id"]]


def test_positive_safety_answer_escalates_and_blocks_routine_care(client):
    cid = start(client)
    say(client, cid, text="my chest hurts")
    convo = say(client, cid, safety_answer=["breathless"])
    payload = last_payload(convo)
    assert payload["kind"] == "emergency"
    assert payload["care_team_notified"] is True
    assert convo["status"] == "escalated"

    # Further messages keep the emergency guidance instead of drifting back to routine care.
    convo = say(client, cid, text="actually can I just book a normal appointment?")
    assert last_payload(convo)["kind"] == "emergency"

    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert queue[0]["kind"] == "red_flag"
    assert queue[0]["priority"] == "urgent"


def test_emergency_intake_cannot_be_booked_as_routine(client):
    cid = start(client)
    say(client, cid, text="my chest hurts")
    say(client, cid, safety_answer=["ongoing"])
    with psycopg.connect(DB) as conn:
        intake_id = conn.execute("SELECT id FROM intakes WHERE urgency = 'emergency' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    r = client.get(f"/api/care/options?intake_id={intake_id}", headers=MAYA)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "emergency"


def test_crisis_language_routes_to_crisis_line(client):
    cid = start(client)
    payload = last_payload(say(client, cid, text="I want to kill myself"))
    assert payload["kind"] == "emergency"
    assert payload["crisis_line"] == "988"


def test_rash_routes_to_dermatology_ranked_by_language_match(client):
    cid = start(client)
    card = last_payload(say(client, cid, text="I have an itchy rash on my forearm"))
    assert card["specialty"] == "Dermatology"
    options = client.get(f"/api/care/options?intake_id={card['intake_id']}", headers=MAYA).json()["options"]
    assert options[0]["practitioner_id"] == DR_FERREIRA
    assert "Speaks Spanish" in options[0]["reasons"]
    assert "Best match" in options[0]["badges"]


def test_draft_explanation_hidden_until_clinician_approves(client):
    report = client.get(f"/api/patients/{P_PARK}/reports", headers=PARK).json()[0]
    before = client.get(f"/api/reports/{report['id']}", headers=PARK).json()["explanation"]
    assert before["status"] == "pending_review"
    assert before["text"] is None
    assert "draft_text" not in before

    item = next(i for i in client.get("/api/clinician/review-queue", headers=OKAFOR).json() if i["kind"] == "result_explanation")
    bad = client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "acknowledge"})
    assert bad.status_code == 422
    edited = "Your HbA1c is slightly high. We'll talk about it at your visit."
    ok = client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "approve", "text": edited})
    assert ok.status_code == 200

    after = client.get(f"/api/reports/{report['id']}", headers=PARK).json()["explanation"]
    assert after["status"] == "approved"
    assert after["text"] == edited
    assert after["reviewed_by"] == "Dr. Adaeze Okafor"


def test_task_update_clears_brief_flag(client):
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Medication not started" in brief["attention_flags"]
    assert all("source" in b for b in brief["bullets"])

    plan = client.get(f"/api/patients/{P_MAYA}/care-plan", headers=MAYA).json()
    med = next(t for t in plan["tasks"] if t["kind"] == "medication")
    assert client.patch(f"/api/care-plan-tasks/{med['id']}", headers=MAYA, json={"status": "done"}).status_code == 200

    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Medication not started" not in brief["attention_flags"]


def test_story_is_built_from_the_record(client):
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    assert story["counts"]["care_gaps"] == 1
    assert "overdue" in story["summary"]
    assert story["events"], "timeline should not be empty"


def test_agent_config_enforces_organization_locks(client):
    config = client.get("/api/clinician/agent-config", headers=OKAFOR).json()
    body = {k: copy.deepcopy(config[k]) for k in ("active", "previsit_questions", "followup_protocol", "escalation_rules", "approval_requirements")}

    body["approval_requirements"][0]["required"] = False  # locked by the organization
    assert client.put("/api/clinician/agent-config", headers=OKAFOR, json=body).status_code == 422
    body["approval_requirements"][0]["required"] = True

    body["escalation_rules"][0]["action"] = "handle_via_scheduling"  # the locked red-flag rule
    assert client.put("/api/clinician/agent-config", headers=OKAFOR, json=body).status_code == 422
    body["escalation_rules"][0]["action"] = "emergency_guidance"

    body["previsit_questions"][0]["text"] = "rewritten specialty question"
    assert client.put("/api/clinician/agent-config", headers=OKAFOR, json=body).status_code == 422
    body["previsit_questions"][0]["text"] = config["previsit_questions"][0]["text"]

    body["approval_requirements"][3]["required"] = True  # the clinician's own choice
    body["escalation_rules"][2]["action"] = "escalate"
    saved = client.put("/api/clinician/agent-config", headers=OKAFOR, json=body)
    assert saved.status_code == 200
    assert saved.json()["approval_requirements"][3]["required"] is True


def test_audit_trail_is_append_only(client):
    start(client)
    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT count(*) FROM audit_events WHERE action = 'conversation_started'").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE audit_events SET action = 'tampered'")


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    holder = {}

    def parse(**kwargs):
        return holder["response"]

    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))))
    yield holder
    llm.set_client(None)


def test_model_can_raise_urgency_to_emergency(client, fake_claude):
    fake_claude["response"] = SimpleNamespace(
        stop_reason="end_turn", stop_details=None, model="claude-opus-5", usage=SimpleNamespace(iterations=None),
        parsed_output=TriageResult(intent="symptom", reply="...", needs_more_info=False, urgency="emergency",
                                   red_flags=["possible sepsis"]),
    )
    cid = start(client)
    convo = say(client, cid, text="I feel really unwell, shivering and confused")
    assert last_payload(convo)["kind"] == "emergency"
    assert "possible sepsis" in last_payload(convo)["flags"]


def test_model_refusal_falls_back_to_rules(client, fake_claude):
    fake_claude["response"] = SimpleNamespace(
        stop_reason="refusal", stop_details=SimpleNamespace(category=None), parsed_output=None,
        model="claude-opus-5", usage=SimpleNamespace(iterations=None),
    )
    cid = start(client)
    card = last_payload(say(client, cid, text="I have an itchy rash"))
    assert card["kind"] == "care_options"
    assert card["specialty"] == "Dermatology"


def test_linked_module_items_cannot_be_acknowledged_away(client):
    """A refill or referral must be decided in its own screen, not closed from the core queue."""
    with psycopg.connect(DB) as conn:
        item_id = conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, title, body, link)
            SELECT 'refill_request', %s, pr.id, 'Refill request', 'test', '/clinician/refills'
            FROM practitioners pr WHERE pr.user_id IS NOT NULL LIMIT 1
            RETURNING id::text
            """,
            (P_MAYA,),
        ).fetchone()[0]
        conn.commit()
    r = client.post(f"/api/clinician/review-items/{item_id}/resolve", headers=OKAFOR, json={"action": "acknowledge"})
    assert r.status_code == 409
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    item = next(i for i in queue if i["id"] == item_id)
    assert item["link"] == "/clinician/refills"
