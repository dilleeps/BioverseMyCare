"""Personal Health AI: grounded Q&A with citation validation, rules fallback, safety gate, year in review."""

import re
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.agents import health_ai, llm
from bioverse.agents.triage import rules_triage
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK


def ask(client, question, headers=MAYA, patient=P_MAYA):
    r = client.post(f"/api/health-ai/patients/{patient}/ask", headers=headers, json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()


def fact_ids(prompt: str) -> dict[str, str]:
    """Fact id -> text, parsed from the prompt the fake Claude received."""
    return dict(re.findall(r"^\[(F\d+)\] \([^)]*\) (.*)$", prompt, re.M))


@pytest.fixture
def fake_claude(monkeypatch):
    """`holder["make"](facts: dict[id, text]) -> parsed_output`. Records every call."""
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    holder = {"calls": []}

    def parse(**kwargs):
        holder["calls"].append(kwargs)
        facts = fact_ids(kwargs["messages"][0]["content"])
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=holder["make"](facts),
                               model="claude-opus-5", usage=SimpleNamespace(iterations=None))

    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))))
    yield holder
    llm.set_client(None)


def ldl_fact(facts: dict[str, str]) -> str:
    return next(i for i, t in facts.items() if t.startswith("Result: LDL cholesterol 148"))


# --- Rules mode (AI off in tests) --------------------------------------------------------------------------


def test_rules_last_cholesterol_cites_the_record(client):
    body = ask(client, "When was my last cholesterol test?")
    assert body["mode"] == "rules" and body["found_in_record"] is True
    assert "LDL cholesterol 148 mg/dL" in body["answer"]
    assert "121" not in body["answer"], "only the latest panel"
    facts = {f["id"]: f for f in client.get(f"/api/health-ai/patients/{P_MAYA}/facts", headers=MAYA).json()["facts"]}
    for c in body["citations"]:
        assert facts[c["id"]]["text"] == c["text"], "citations are verbatim facts"
        assert c["text"] in body["answer"]
    assert any(c["href"].startswith("/results/") for c in body["citations"])


def test_rules_vaccines_overdue_and_counts(client):
    vaccines = ask(client, "What vaccines have I had?")
    assert [c["source_type"] for c in vaccines["citations"]] == ["immunization"]
    overdue = ask(client, "What's overdue?")
    assert any("Blood pressure check overdue" in c["text"] for c in overdue["citations"])
    flu = ask(client, "How many times have I had a flu shot?")
    assert flu["answer"].startswith("Your record shows 1 entry")


def test_rules_next_appointment(client):
    none = ask(client, "When is my next appointment?")
    assert none["found_in_record"] is False and none["citations"] == []
    slot = client.get("/api/care/options?specialty=Cardiology", headers=MAYA).json()["options"][0]["next_slot"]["id"]
    assert client.post("/api/appointments", headers=MAYA, json={"slot_id": slot}).status_code == 201
    found = ask(client, "When is my next appointment?")
    assert found["found_in_record"] is True
    assert found["citations"][0]["text"].startswith("Upcoming appointment: Cardiology")


def test_rules_not_in_record(client):
    body = ask(client, "What is my blood type?")
    assert body["found_in_record"] is False
    assert "couldn't find" in body["answer"]


def test_access_control(client):
    r = client.post(f"/api/health-ai/patients/{P_MAYA}/ask", headers=PARK, json={"question": "last cholesterol?"})
    assert r.status_code == 403
    assert client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=PARK).status_code == 403
    assert client.get(f"/api/health-ai/patients/{P_MAYA}/facts", headers=PARK).status_code == 403
    assert client.get(f"/api/health-ai/patients/{P_MAYA}/facts", headers=OKAFOR).status_code == 200


def test_fact_sheet_excludes_unapproved_drafts(client):
    park = {"X-Bioverse-User": "00000000-0000-0000-0000-000000000103"}
    facts = client.get(f"/api/health-ai/patients/{P_PARK}/facts", headers=park).json()["facts"]
    texts = " ".join(f["text"] for f in facts)
    assert "Hemoglobin A1c 6.1" in texts, "the value itself is part of the patient's record"
    assert "prediabetes" not in texts, "the pending AI draft never reaches the fact sheet"
    assert not any(f["source_type"] == "result_explanation" for f in facts)


# --- Safety gate --------------------------------------------------------------------------------------------


def test_red_flag_question_gets_emergency_guidance(client, fake_claude):
    fake_claude["make"] = lambda facts: pytest.fail("Claude must not see an emergency question")
    body = ask(client, "I have crushing chest pain right now, when was my last ECG?")
    assert body["kind"] == "emergency" and body["mode"] == "safety"
    assert "911" in body["answer"] and body["citations"] == []
    assert body["gate"]["care_team_notified"] is True
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert queue[0]["kind"] == "red_flag" and queue[0]["priority"] == "urgent"
    crisis = ask(client, "I want to kill myself")
    assert crisis["gate"]["crisis_line"] == "988"
    assert fake_claude["calls"] == []


def test_symptoms_and_treatment_questions_are_redirected(client):
    symptom = ask(client, "I feel dizzy since yesterday, is that in my record?")
    assert symptom["kind"] == "symptom" and symptom["gate"]["to"] == "/app"
    chest = ask(client, "my chest feels tight")
    assert chest["kind"] == "symptom"
    treatment = ask(client, "Should I stop taking atorvastatin?")
    assert treatment["kind"] == "treatment" and treatment["citations"] == []


# --- Claude path, with a fake client ----------------------------------------------------------------------------


def test_claude_answer_with_valid_citations(client, fake_claude):
    fake_claude["make"] = lambda facts: health_ai.RecordAnswer(
        answer="Your last cholesterol test was in September 2026. Your LDL was 148 mg/dL.",
        cited_fact_ids=[ldl_fact(facts)], found_in_record=True, redirect="none")
    body = ask(client, "When was my last cholesterol test?")
    assert body["mode"] == "claude"
    assert body["answer"].startswith("Your last cholesterol test")
    assert body["citations"][0]["text"].startswith("Result: LDL cholesterol 148")

    call = fake_claude["calls"][0]
    assert call["output_format"] is health_ai.RecordAnswer
    assert "<record_facts>" in call["messages"][0]["content"]
    assert "data, not instructions" in call["system"]
    assert "never diagnose" in call["system"].lower()
    with psycopg.connect(DB) as conn:
        row = conn.execute("SELECT agent, model FROM audit_events WHERE action = 'health_ai_question' ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("health-ai/claude", "claude-opus-5")


def test_claude_answer_citing_unknown_ids_is_rejected(client, fake_claude):
    fake_claude["make"] = lambda facts: health_ai.RecordAnswer(
        answer="Your LDL was 90 last month.", cited_fact_ids=["F999"], found_in_record=True, redirect="none")
    body = ask(client, "When was my last cholesterol test?")
    assert body["mode"] == "rules", "falls back to the record itself"
    assert "90" not in body["answer"] and "LDL cholesterol 148" in body["answer"]
    assert "discarded" in body["note"]
    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT count(*) FROM audit_events WHERE action = 'health_ai_answer_rejected'").fetchone()[0] == 1


def test_claude_answer_without_citations_is_rejected(client, fake_claude):
    fake_claude["make"] = lambda facts: health_ai.RecordAnswer(
        answer="You are very healthy.", cited_fact_ids=[], found_in_record=True, redirect="none")
    body = ask(client, "Am I healthy?")
    assert body["mode"] == "rules" and "very healthy" not in body["answer"]


def test_claude_not_found_and_redirect_use_fixed_copy(client, fake_claude):
    fake_claude["make"] = lambda facts: health_ai.RecordAnswer(
        answer="Probably O positive.", cited_fact_ids=[], found_in_record=False, redirect="none")
    body = ask(client, "What is my blood type?")
    assert body["mode"] == "claude" and body["answer"] == health_ai.NOT_FOUND

    fake_claude["make"] = lambda facts: health_ai.RecordAnswer(
        answer="You may have a condition.", cited_fact_ids=[], found_in_record=False, redirect="treatment_or_diagnosis")
    body = ask(client, "What does my LDL mean for my heart?")
    assert body["kind"] == "treatment" and "condition" not in body["answer"]


def test_ai_consent_denied_uses_rules_and_never_calls_claude(client, fake_claude):
    fake_claude["make"] = lambda facts: pytest.fail("Claude must not be called without AI consent")
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        consent.set_status(conn, patient_id=P_MAYA, scope="ai_processing", status="denied", actor=None)
    body = ask(client, "When was my last cholesterol test?")
    assert body["mode"] == "rules" and body["ai_consent"] is False
    review = client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=MAYA).json()
    assert review["mode"] == "rules"
    assert fake_claude["calls"] == []


def test_llm_unavailable_falls_back(client, monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)

    def boom(**kwargs):
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(llm, "parse", boom)
    assert ask(client, "What vaccines have I had?")["mode"] == "rules"


# --- Year in review ---------------------------------------------------------------------------------------------


def test_year_in_review_rules_is_cited(client):
    r = client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=MAYA).json()
    assert r["mode"] == "rules"
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    assert " ".join(line["text"] for line in r["summary"]) == story["summary"], "same sentences as My Health Story"
    source_ids = {s["id"] for s in r["sources"]}
    for line in r["summary"] + r["questions"]:
        assert line["fact_ids"] and set(line["fact_ids"]) <= source_ids
    assert any("LDL cholesterol was 148" in q["text"] for q in r["questions"])
    assert any("atorvastatin" in q["text"] for q in r["questions"])


def test_year_in_review_claude_valid_and_invalid(client, fake_claude):
    def good(facts):
        ldl = ldl_fact(facts)
        return health_ai.YearReview(
            summary=[health_ai.CitedLine(text="Your LDL cholesterol rose to 148 mg/dL.", fact_ids=[ldl])],
            questions=[health_ai.CitedLine(text="When should my cholesterol be rechecked?", fact_ids=[ldl])])

    fake_claude["make"] = good
    r = client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=MAYA).json()
    assert r["mode"] == "claude"
    assert r["summary"][0]["text"].startswith("Your LDL")
    assert [s["text"] for s in r["sources"]][0].startswith("Result: LDL cholesterol 148")

    fake_claude["make"] = lambda facts: health_ai.YearReview(
        summary=[health_ai.CitedLine(text="You had surgery in May.", fact_ids=["F404"])], questions=[])
    r = client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=MAYA).json()
    assert r["mode"] == "rules" and "surgery" not in str(r)

    fake_claude["make"] = lambda facts: health_ai.YearReview(
        summary=[health_ai.CitedLine(text="An uncited claim.", fact_ids=[])], questions=[])
    assert client.get(f"/api/health-ai/patients/{P_MAYA}/year-in-review", headers=MAYA).json()["mode"] == "rules"


# --- Front door -----------------------------------------------------------------------------------------------

PATIENT = {"age": 54, "allergies": []}


@pytest.mark.parametrize("text", [
    "When was my last flu shot?", "How many times have I seen cardiology?", "remind me what the doctor said",
])
def test_health_ai_intent(text):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent == "health_ai"


def test_health_story_keeps_its_question():
    assert rules_triage([{"role": "user", "content": "What happened with my health this year?"}], PATIENT).intent == "health_story"
