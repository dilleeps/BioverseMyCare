"""Secure messaging: red flags, triage, drafts, access control, the fake-Claude path."""

from types import SimpleNamespace

import psycopg
import pytest

from bioverse.agents import llm, message_triage
from bioverse.agents.message_triage import DraftReply, MessageTriage, rules_triage
from bioverse.db.seed import DR_OKAFOR, P_HADDAD, U_FRONTDESK, U_HADDAD
from bioverse.db.seeds.ids import _id
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK, as_user

HADDAD = as_user(U_HADDAD)
FRONTDESK = as_user(U_FRONTDESK)
T_MAYA, T_RANA, T_JUN = _id(3100), _id(3130), _id(3160)


def new_thread(client, text, headers=MAYA):
    r = client.post("/api/messages/threads", headers=headers, json={"body": text})
    assert r.status_code == 201, r.text
    return r.json()


def say(client, thread_id, text, headers=MAYA, **extra):
    r = client.post(f"/api/messages/threads/{thread_id}/messages", headers=headers, json={"body": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def sql(query, *params):
    with psycopg.connect(DB) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def set_agent_active(active):
    sql("UPDATE doctor_agent_configs SET active = %s WHERE practitioner_id = %s", active, DR_OKAFOR)


def deny_ai(patient_id):
    sql("INSERT INTO consents (patient_id, scope, status) VALUES (%s, 'ai_processing', 'denied')", patient_id)


# ---------------------------------------------------------------------------------------------
# Red flags
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("agent_active", [True, False])
def test_red_flag_escalates_even_with_ai_and_agent_off(client, agent_active):
    set_agent_active(agent_active)
    deny_ai(P_MAYA)
    thread = new_thread(client, "I have crushing chest pain and my left arm feels heavy")

    last = thread["messages"][-1]
    assert last["author_kind"] == "system"
    assert last["automated"] is True
    assert last["payload"]["kind"] == "emergency"
    assert last["payload"]["emergency_number"] == "911"
    assert last["payload"]["care_team_notified"] is True
    assert thread["flagged"] is True

    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    item = queue[0]
    assert item["kind"] == "red_flag"
    assert item["priority"] == "urgent"
    assert item["link"] == f"/clinician/inbox?thread={thread['id']}"
    assert item["patient_id"] == P_MAYA

    inbox = client.get("/api/messages/threads", headers=OKAFOR).json()
    assert inbox[0]["id"] == thread["id"], "flagged thread sorts first"
    assert inbox[0]["priority"] == "urgent"

    # No routine flow past the emergency: no triage-based agent answer after the guidance.
    assert [m["author_kind"] for m in thread["messages"]] == ["patient", "system"]
    audit = sql("SELECT agent FROM audit_events WHERE action = 'red_flag_escalation' AND patient_id = %s", P_MAYA)
    assert audit == [("safety/red-flags",)]


def test_crisis_message_shows_crisis_line(client):
    thread = new_thread(client, "I don't see the point anymore, I want to die")
    assert thread["messages"][-1]["payload"]["crisis_line"] == "988"


def test_acknowledging_red_flag_resolves_review_item(client):
    thread = new_thread(client, "My face is drooping and I have slurred speech")
    r = client.post(f"/api/messages/threads/{thread['id']}/acknowledge-flag", headers=OKAFOR)
    assert r.status_code == 200
    assert r.json()["flag_acknowledged"] is True
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert not [i for i in queue if i["kind"] == "red_flag"]
    assert client.post(f"/api/messages/threads/{thread['id']}/acknowledge-flag", headers=MAYA).status_code == 403


# ---------------------------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "category", "priority"),
    [
        ("Is dizziness normal with the new tablet?", "side_effect", "routine"),
        ("I've had muscle aches since starting atorvastatin", "side_effect", "routine"),
        ("I have a sore throat and a cough", "new_symptom", "routine"),
        ("My ankle swelling is getting worse", "worsening_symptom", "urgent"),
        ("Should I take my atorvastatin in the morning or evening?", "medication_question", "routine"),
        ("What does my LDL result mean?", "results_question", "routine"),
        ("Can I reschedule my appointment to next week?", "logistics", "routine"),
        ("I got a bill I don't understand, is it covered by insurance?", "billing", "routine"),
        ("Thanks for your help", "other", "routine"),
        ("I have no pain, just wanted to say thanks", "other", "routine"),
    ],
)
def test_rules_triage_categories(text, category, priority):
    result = rules_triage(text)
    assert (result.category, result.priority) == (category, priority)
    assert result.reason


def test_chest_symptom_without_warning_signs_is_urgent():
    assert rules_triage("I've had some chest tightness today", screen_level="screen").priority == "urgent"


# ---------------------------------------------------------------------------------------------
# The fake-Claude path
# ---------------------------------------------------------------------------------------------


class FakeMessages:
    def __init__(self):
        self.responses = []
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def reply(output, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=None) if stop_reason == "refusal" else None,
        parsed_output=output,
        model="claude-opus-5",
        usage=SimpleNamespace(iterations=None),
    )


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    fake = FakeMessages()
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    yield fake
    llm.set_client(None)


def test_model_can_raise_priority(claude):
    claude.responses.append(reply(MessageTriage(category="new_symptom", priority="urgent", reason="Sounds acute.")))
    out = message_triage.classify("I have a sore throat", ai_allowed=True)
    assert out.priority == "urgent"
    assert out.produced_by == "message-triage/claude"
    assert out.model == "claude-opus-5"
    call = claude.calls[0]
    assert call["output_format"] is MessageTriage
    assert call["fallbacks"] == "default"
    assert "<message>" in call["messages"][0]["content"]
    assert "never instructions" in call["system"]


def test_model_cannot_lower_rules_urgent(claude):
    claude.responses.append(reply(MessageTriage(category="new_symptom", priority="routine", reason="Minor.")))
    out = message_triage.classify("My ankle swelling is getting worse", ai_allowed=True)
    assert out.priority == "urgent"
    assert "Kept urgent by rules" in out.reason


def test_model_refusal_falls_back_to_rules(claude):
    claude.responses.append(reply(None, stop_reason="refusal"))
    out = message_triage.classify("Can I reschedule my appointment?", ai_allowed=True)
    assert out.produced_by == "message-triage/rules"
    assert out.category == "logistics"


def test_consent_denied_never_calls_the_model(client, claude):
    deny_ai(P_MAYA)
    new_thread(client, "Can I reschedule my appointment?")
    assert claude.calls == []


def test_model_flagged_emergency_escalates(client, claude):
    claude.responses.append(reply(MessageTriage(category="new_symptom", priority="urgent", reason="Confusion.",
                                                possible_emergency=True)))
    thread = new_thread(client, "I feel shivery and a bit confused today")
    assert thread["messages"][-1]["payload"]["kind"] == "emergency"
    assert thread["flagged"] is True


def test_claude_draft_is_grounded_and_labelled(client, claude):
    claude.responses.append(reply(DraftReply(body="Hi Rana, thanks for telling us. Dr. Okafor", facts_used=["Allergies: Sulfa drugs"])))
    draft = client.post(f"/api/messages/threads/{T_RANA}/draft", headers=OKAFOR)
    assert draft.status_code == 201
    body = draft.json()
    assert body["produced_by"] == "reply-drafter/claude"
    assert body["model"] == "claude-opus-5"
    call = claude.calls[0]
    assert call["output_format"] is DraftReply
    content = call["messages"][0]["content"]
    assert "<thread>" in content and "<record_facts>" in content
    assert "Sulfa drugs" in content
    assert "Is dizziness normal with the new tablet?" in content
    assert "never diagnose" in call["system"].lower()


def test_draft_refusal_falls_back_to_template(client, claude):
    claude.responses.append(reply(None, stop_reason="refusal"))
    body = client.post(f"/api/messages/threads/{T_RANA}/draft", headers=OKAFOR).json()
    assert body["produced_by"] == "reply-drafter/rules"
    assert body["body"].startswith("Hi Rana, thank you for your message.")


# ---------------------------------------------------------------------------------------------
# Drafts and replies
# ---------------------------------------------------------------------------------------------


def test_drafts_never_reach_the_patient_until_sent(client):
    draft = client.post(f"/api/messages/threads/{T_RANA}/draft", headers=OKAFOR).json()
    assert draft["produced_by"] == "reply-drafter/rules"

    patient_view = client.get(f"/api/messages/threads/{T_RANA}", headers=HADDAD).json()
    assert "drafts" not in patient_view
    assert all(draft["body"] != m["body"] for m in patient_view["messages"])
    assert draft["body"] not in str(patient_view)

    clinician_view = client.get(f"/api/messages/threads/{T_RANA}", headers=OKAFOR).json()
    assert [d["id"] for d in clinician_view["drafts"]] == [draft["id"]]

    # Patients cannot send drafts; clinicians send an edited version.
    assert client.post(f"/api/messages/threads/{T_RANA}/messages", headers=HADDAD,
                       json={"body": "x", "draft_id": draft["id"]}).status_code == 422
    edited = "Hi Rana, some dizziness on standing can happen with amlodipine. Let's talk at your visit. Dr. Okafor"
    sent = say(client, T_RANA, edited, headers=OKAFOR, draft_id=draft["id"])
    assert sent["drafts"] == []
    assert sent["awaiting_since"] is None

    patient_view = client.get(f"/api/messages/threads/{T_RANA}", headers=HADDAD).json()
    last = patient_view["messages"][-1]
    assert last["body"] == edited
    assert last["author_kind"] == "clinician"
    assert last["automated"] is False

    # Sending closes the linked agent_escalation review item and records whether the draft was edited.
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert not [i for i in queue if i["kind"] == "agent_escalation"]
    assert sql("SELECT detail->>'edited' FROM audit_events WHERE action = 'draft_sent'") == [("true",)]
    # A used draft cannot be sent twice.
    r = client.post(f"/api/messages/threads/{T_RANA}/messages", headers=OKAFOR, json={"body": "again", "draft_id": draft["id"]})
    assert r.status_code == 404


def test_discarded_draft_is_gone(client):
    draft = client.post(f"/api/messages/threads/{T_RANA}/draft", headers=OKAFOR).json()
    assert client.post(f"/api/messages/drafts/{draft['id']}/discard", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/messages/threads/{T_RANA}", headers=OKAFOR).json()["drafts"] == []
    assert client.post(f"/api/messages/drafts/{draft['id']}/discard", headers=HADDAD).status_code == 403


def test_read_receipts(client):
    thread = new_thread(client, "What does my LDL result mean?")
    before = next(p for p in thread["participants"] if p["role"] == "clinician")
    last_seq = thread["messages"][-1]["seq"]
    assert before["last_read_seq"] < last_seq
    assert client.get("/api/messages/threads", headers=OKAFOR).json()  # inbox lists it
    opened = client.get(f"/api/messages/threads/{thread['id']}", headers=OKAFOR).json()
    after = next(p for p in opened["participants"] if p["role"] == "clinician")
    assert after["last_read_seq"] == last_seq
    assert after["last_read_at"] is not None
    # The sender has also seen the automated reply that came back with their own message.
    mine = next(t for t in client.get("/api/messages/threads", headers=MAYA).json() if t["id"] == thread["id"])
    assert mine["unread"] == 0
    say(client, thread["id"], "Also, is 148 high?")
    mine = next(t for t in client.get("/api/messages/threads", headers=MAYA).json() if t["id"] == thread["id"])
    assert mine["unread"] == 0


def test_new_patient_thread_goes_to_care_team_clinician(client):
    thread = new_thread(client, "What does my LDL result mean?")
    assert thread["practitioner"]["id"] == DR_OKAFOR
    assert thread["care_team_label"] == "Dr. Okafor"
    assert "category" not in thread, "patients don't see triage internals"
    clinician = client.get(f"/api/messages/threads/{thread['id']}", headers=OKAFOR).json()
    assert clinician["category"] == "results_question"


def test_inbox_sorts_urgent_then_oldest_unanswered(client):
    inbox = client.get("/api/messages/threads", headers=OKAFOR).json()
    waiting = [t for t in inbox if t["awaiting_since"]]
    assert waiting == inbox[: len(waiting)]
    assert [t["awaiting_since"] for t in waiting] == sorted(t["awaiting_since"] for t in waiting)

    urgent = new_thread(client, "My ankle swelling is getting worse and worse")
    inbox = client.get("/api/messages/threads", headers=OKAFOR).json()
    assert inbox[0]["id"] == urgent["id"]
    assert inbox[0]["priority"] == "urgent"


# ---------------------------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------------------------


def test_patients_only_reach_their_own_threads(client):
    assert client.get(f"/api/messages/threads/{T_MAYA}", headers=PARK).status_code == 404
    assert client.post(f"/api/messages/threads/{T_MAYA}/messages", headers=PARK, json={"body": "hi"}).status_code == 404
    assert client.post(f"/api/messages/threads/{T_MAYA}/draft", headers=MAYA).status_code == 403
    assert client.get("/api/messages/threads/not-a-uuid", headers=MAYA).status_code == 404
    assert client.get(f"/api/messages/threads/{_id(3999)}", headers=MAYA).status_code == 404
    ids = {t["id"] for t in client.get("/api/messages/threads", headers=PARK).json()}
    assert ids == {T_JUN}


def test_admins_and_anonymous_are_refused(client):
    assert client.get("/api/messages/threads").status_code == 401
    assert client.get("/api/messages/threads", headers=ADMIN).status_code == 403
    assert client.get(f"/api/messages/threads/{T_MAYA}", headers=ADMIN).status_code == 403


def test_front_desk_answers_logistics_not_clinical_threads(client):
    inbox = {t["id"] for t in client.get("/api/messages/threads", headers=FRONTDESK).json()}
    assert T_JUN in inbox
    assert T_MAYA not in inbox and T_RANA not in inbox

    assert client.post(f"/api/messages/threads/{T_MAYA}/messages", headers=FRONTDESK, json={"body": "hi"}).status_code == 403
    assert client.post(f"/api/messages/threads/{T_RANA}/draft", headers=FRONTDESK).status_code == 403

    draft = client.post(f"/api/messages/threads/{T_JUN}/draft", headers=FRONTDESK).json()
    assert "red_flag" not in draft["body"]
    sent = say(client, T_JUN, "Hi Jun, we'll email the letter today. Northside Front Desk", headers=FRONTDESK, draft_id=draft["id"])
    assert sent["messages"][-1]["author_kind"] == "staff"
    assert sent["awaiting_since"] is None


def test_red_flag_thread_cannot_be_handed_to_front_desk(client):
    thread = new_thread(client, "I passed out this morning")
    r = client.post(f"/api/messages/threads/{thread['id']}/assign", headers=OKAFOR, json={"to": "front_desk"})
    assert r.status_code == 409


def test_every_write_is_audited_with_patient(client):
    new_thread(client, "Can I reschedule my appointment to next week?")
    rows = sql(
        "SELECT action FROM audit_events WHERE patient_id = %s AND action LIKE 'message_%%' ORDER BY id", P_MAYA
    )
    actions = [r[0] for r in rows]
    assert "message_patient" in actions
    assert "message_agent" in actions
    agent_rows = sql("SELECT agent FROM audit_events WHERE action = 'message_agent' AND patient_id = %s", P_MAYA)
    assert all(r[0] == "doctor-agent/rules" for r in agent_rows)


def test_haddad_seed_links_core_escalation_to_thread(client):
    items = [i for i in client.get("/api/clinician/review-queue", headers=OKAFOR).json() if i["kind"] == "agent_escalation"]
    assert items and items[0]["link"] == f"/clinician/inbox?thread={T_RANA}"
    assert items[0]["patient_id"] == P_HADDAD
