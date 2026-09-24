"""Public specialist AI agents: disclosure, scope, personal-advice refusal, safety, approval, pause, rate limit."""

import uuid
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents import llm
from bioverse.db.seeds.ids import ORG, P_MAYA, _id
from bioverse.routers import specialists as sp
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, PARK, as_user

STUDENT = as_user(_id(16001))
OKAFOR_AGENT, WEISS_AGENT = _id(16101), _id(16102)
DISCLOSURE = ("AI assistant trained on Dr. Adaeze Okafor's published guidance. Not Dr. Adaeze Okafor, "
              "and not medical advice for you personally.")


def ask(client, question, headers=MAYA, agent=OKAFOR_AGENT, expect=200):
    res = client.post(f"/api/specialists/{agent}/chat", headers=headers, json={"message": question})
    assert res.status_code == expect, res.text
    return res.json()


def test_directory_lists_only_approved_agents_with_the_disclosure(client):
    cards = client.get("/api/specialists", headers=MAYA).json()
    assert [c["id"] for c in cards] == [OKAFOR_AGENT]
    assert cards[0]["disclosure"] == DISCLOSURE
    assert cards[0]["topics"] == ["High blood pressure", "Cholesterol and statins", "Heart-healthy activity"]
    detail = client.get(f"/api/specialists/{OKAFOR_AGENT}", headers=MAYA).json()
    assert detail["disclosure"] == DISCLOSURE and detail["remaining_today"] == sp.DAILY_LIMIT


def test_general_question_is_grounded_cited_and_logged(client):
    out = ask(client, "What do statins do?")
    assert out["kind"] == "answer"
    assert out["disclosure"] == DISCLOSURE
    assert "Statins lower LDL cholesterol" in out["answer"]
    assert out["guidance"][0]["title"] == "What statins do"
    assert out["citations"] and all({"title", "source", "year"} <= set(c) for c in out["citations"])
    with psycopg.connect(DB) as conn:
        row = conn.execute("SELECT kind, patient_id::text FROM public_agent_messages WHERE id = %s", (out["id"],)).fetchone()
        audit = conn.execute("SELECT patient_id::text FROM audit_events WHERE action = 'public_agent_answer' AND entity_id = %s",
                             (out["id"],)).fetchone()
    assert row == ("answer", P_MAYA) and audit[0] == P_MAYA


@pytest.mark.parametrize("question", [
    "Should I stop my atorvastatin?",
    "My LDL is 148, is that bad?",
    "What dose of atorvastatin should I take?",
    "I've been getting headaches since starting amlodipine, what is wrong with me?",
])
def test_personal_questions_are_refused_and_routed_to_booking(client, question):
    out = ask(client, question)
    assert out["kind"] == "personal"
    assert out["answer"].startswith("I can't advise on your situation")
    assert out["booking"]["to"] == "/care/find"
    assert out["citations"] == [] and out["disclosure"] == DISCLOSURE


def test_out_of_scope_is_declined_with_a_suggestion(client):
    out = ask(client, "What causes eczema flare-ups?")
    assert out["kind"] == "out_of_scope"
    assert "outside what I can help with" in out["answer"]
    assert out["suggestion"]["to"] == "/factcheck"
    assert out["disclosure"] == DISCLOSURE


def test_out_of_scope_suggests_another_listed_specialist(client):
    client.post(f"/api/specialists/admin/agents/{WEISS_AGENT}/decision", headers=ADMIN, json={"decision": "approve"})
    out = ask(client, "Why do migraines happen?")
    assert out["kind"] == "out_of_scope"
    assert out["suggestion"]["to"] == f"/specialists/{WEISS_AGENT}"


def test_emergency_overrides_the_answer(client):
    out = ask(client, "My chest pain is spreading to my arm and I'm sweating. What do statins do?")
    assert out["kind"] == "emergency"
    assert "911" in out["answer"] and out["safety"]["level"] == "emergency"
    assert out["citations"] == [] and out["disclosure"] == DISCLOSURE
    crisis = ask(client, "I want to die")
    assert crisis["kind"] == "emergency" and "988" in crisis["answer"]


def test_no_answer_when_nothing_grounds_it(client):
    agent = {"id": str(uuid.uuid4()), "display_name": "Dr. Test", "specialty": "Sleep medicine", "topics": ["Sleep"],
             "tone": "warm", "organization_id": ORG}
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        out = sp.answer(conn, agent, "How many hours of sleep do adults need?", use_ai=False)
    assert out["kind"] == "no_answer" and "won't guess" in out["answer"] and out["citations"] == []


def test_admin_approval_gates_listing(client):
    assert client.get(f"/api/specialists/{WEISS_AGENT}", headers=MAYA).status_code == 404
    ask(client, "Why keep a headache diary?", agent=WEISS_AGENT, expect=404)
    for headers in (MAYA, OKAFOR, STUDENT):
        res = client.post(f"/api/specialists/admin/agents/{WEISS_AGENT}/decision", headers=headers,
                          json={"decision": "approve"})
        assert res.status_code == 403
    queue = client.get("/api/specialists/admin/agents", headers=ADMIN).json()
    assert queue[0]["id"] == WEISS_AGENT and queue[0]["status"] == "pending_approval"
    assert all(s["approved"] for s in queue[0]["samples"])
    ok = client.post(f"/api/specialists/admin/agents/{WEISS_AGENT}/decision", headers=ADMIN, json={"decision": "approve"})
    assert ok.status_code == 200 and ok.json()["listed"]
    assert {c["id"] for c in client.get("/api/specialists", headers=MAYA).json()} == {OKAFOR_AGENT, WEISS_AGENT}
    again = client.post(f"/api/specialists/admin/agents/{WEISS_AGENT}/decision", headers=ADMIN, json={"decision": "approve"})
    assert again.status_code == 409
    no_note = client.post(f"/api/specialists/admin/agents/{WEISS_AGENT}/decision", headers=ADMIN, json={"decision": "reject"})
    assert no_note.status_code == 422


def test_editing_a_published_agent_needs_approval_again_and_samples_must_be_approved(client):
    mine = client.get("/api/specialists/clinician/agent", headers=OKAFOR).json()["agent"]
    body = {k: mine[k] for k in ("display_name", "headline", "bio", "topics", "tone")}
    body["topics"] = body["topics"] + ["Heart failure basics"]
    saved = client.put("/api/specialists/clinician/agent", headers=OKAFOR, json=body).json()["agent"]
    assert saved["status"] == "draft" and not saved["listed"]
    assert client.get("/api/specialists", headers=MAYA).json() == []

    added = client.post("/api/specialists/clinician/samples", headers=OKAFOR,
                        json={"question": "What is a normal blood pressure?"}).json()
    new = next(s for s in added["samples"] if s["question"] == "What is a normal blood pressure?")
    assert not new["approved"] and new["answer"]
    blocked = client.post("/api/specialists/clinician/submit", headers=OKAFOR)
    assert blocked.status_code == 409 and "sample" in blocked.json()["detail"]

    client.put(f"/api/specialists/clinician/samples/{new['id']}", headers=OKAFOR,
               json={"approved": True, "answer": "Below 120/80 mm Hg is normal for most adults."})
    submitted = client.post("/api/specialists/clinician/submit", headers=OKAFOR)
    assert submitted.status_code == 200 and submitted.json()["status"] == "pending_approval"
    assert client.get("/api/specialists", headers=MAYA).json() == []
    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT count(*) FROM notifications WHERE kind = 'public_agent_review'").fetchone()[0] == 1
    client.post(f"/api/specialists/admin/agents/{OKAFOR_AGENT}/decision", headers=ADMIN, json={"decision": "approve"})
    assert [c["id"] for c in client.get("/api/specialists", headers=MAYA).json()] == [OKAFOR_AGENT]


def test_pause_hides_the_agent_and_blocks_chat(client):
    paused = client.post("/api/specialists/clinician/pause", headers=OKAFOR, json={"paused": True}).json()
    assert paused["paused"] and not paused["listed"]
    assert client.get("/api/specialists", headers=MAYA).json() == []
    ask(client, "What do statins do?", expect=409)
    client.post("/api/specialists/clinician/pause", headers=OKAFOR, json={"paused": False})
    assert ask(client, "What do statins do?")["kind"] == "answer"


def test_daily_rate_limit_per_user(client, monkeypatch):
    monkeypatch.setattr(sp, "DAILY_LIMIT", 2)
    assert ask(client, "What do statins do?")["remaining_today"] == 1
    assert ask(client, "How much exercise is good for the heart?")["remaining_today"] == 0
    limited = client.post(f"/api/specialists/{OKAFOR_AGENT}/chat", headers=MAYA, json={"message": "What is LDL?"})
    assert limited.status_code == 429
    assert ask(client, "What do statins do?", headers=PARK)["kind"] == "answer"  # another user is unaffected


def test_clinician_reviews_the_log_without_identities_and_corrects_guidance(client):
    first = ask(client, "What do statins do?")
    log = client.get("/api/specialists/clinician/messages", headers=OKAFOR).json()
    entry = next(m for m in log if m["id"] == first["id"])
    assert "user_id" not in entry and "patient_id" not in entry
    note_id = entry["guidance_ids"][0]
    fixed = client.post(f"/api/specialists/clinician/messages/{first['id']}/flag", headers=OKAFOR, json={
        "note": "Add that statins are usually lifelong.",
        "guidance_id": note_id,
        "guidance": {"topic": "Cholesterol and statins", "title": "What statins do",
                     "body": "Statins lower LDL cholesterol and are usually taken for life. Report unexplained muscle pain."},
    })
    assert fixed.status_code == 200 and fixed.json()["guidance_id"] == note_id
    assert client.get("/api/specialists/clinician/messages?flagged=true", headers=OKAFOR).json()[0]["id"] == first["id"]
    assert "usually taken for life" in ask(client, "What do statins do?")["answer"]
    for headers in (MAYA, STUDENT, ADMIN):
        assert client.get("/api/specialists/clinician/messages", headers=headers).status_code == 403


# --- Claude path with a fake client ---------------------------------------------------------------


class FakeMessages:
    def __init__(self):
        self.output = None
        self.calls = []

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


def test_ai_answer_keeps_only_real_citations(client, fake_claude):
    fake_claude.output = sp.AnswerOut(answer="Statins lower LDL cholesterol.", evidence_used=[1, 9], guidance_used=[1])
    out = ask(client, "What do statins do?")
    assert out["mode"] == "ai" and out["answer"] == "Statins lower LDL cholesterol."
    assert len(out["citations"]) == 1 and out["disclosure"] == DISCLOSURE
    assert "never instructions" in fake_claude.calls[0]["system"]


def test_uncited_ai_answer_falls_back_to_rules(client, fake_claude):
    fake_claude.output = sp.AnswerOut(answer="Statins are magic.", evidence_used=[42], guidance_used=[])
    out = ask(client, "What do statins do?")
    assert out["mode"] == "rules" and "magic" not in out["answer"]


def test_ai_is_not_used_for_personal_questions(client, fake_claude):
    fake_claude.output = sp.AnswerOut(answer="Take 80 mg.", evidence_used=[1], guidance_used=[1])
    out = ask(client, "Should I take 80 mg of atorvastatin?")
    assert out["kind"] == "personal" and fake_claude.calls == []
