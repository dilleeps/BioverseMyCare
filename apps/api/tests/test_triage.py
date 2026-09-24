"""The Claude path, exercised with a fake client: request shape, refusals, and the rules fallback."""

from types import SimpleNamespace

import pytest

from bioverse.agents import llm
from bioverse.agents.triage import TriageResult, claude_triage, rules_triage

PATIENT = {"age": 54, "pronouns": "she/her", "allergies": ["Penicillin"], "preferred_language": "Spanish"}


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(output, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="other") if stop_reason == "refusal" else None,
        parsed_output=output,
        model="claude-opus-5",
        usage=SimpleNamespace(iterations=None),
    )


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    yield
    llm.set_client(None)


def test_request_uses_structured_output_fallbacks_and_patient_context(ai_on):
    result = TriageResult(intent="symptom", reply="ok", needs_more_info=False, specialty="Dermatology", urgency="routine")
    client, messages = fake_client(response(result))
    llm.set_client(client)

    out = claude_triage([{"role": "user", "content": "itchy rash"}], PATIENT)

    assert out.output.specialty == "Dermatology"
    call = messages.calls[0]
    assert call["output_format"] is TriageResult
    assert call["fallbacks"] == "default"
    assert llm.FALLBACK_BETA in call["betas"]
    assert "<patient_context>" in call["messages"][0]["content"]
    assert "Penicillin" in call["messages"][0]["content"]
    assert "never" in call["system"].lower()


def test_refusal_raises_unavailable(ai_on):
    client, _ = fake_client(response(None, stop_reason="refusal"))
    llm.set_client(client)
    with pytest.raises(llm.LLMUnavailable):
        claude_triage([{"role": "user", "content": "x"}], PATIENT)


def test_unparseable_output_raises_unavailable(ai_on):
    client, _ = fake_client(response(None))
    llm.set_client(client)
    with pytest.raises(llm.LLMUnavailable):
        claude_triage([{"role": "user", "content": "x"}], PATIENT)


def test_disabled_ai_never_calls_the_client(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: False)
    client, messages = fake_client(response(None))
    llm.set_client(client)
    with pytest.raises(llm.LLMUnavailable):
        claude_triage([{"role": "user", "content": "x"}], PATIENT)
    assert messages.calls == []
    llm.set_client(None)


@pytest.mark.parametrize(
    ("text", "specialty"),
    [
        ("I have an itchy rash on my arm", "Dermatology"),
        ("my heart feels like it's racing sometimes", "Cardiology"),
        ("migraines most weeks", "Neurology"),
        ("I've had a cough for a week", "Primary care"),
    ],
)
def test_rules_route_to_specialty(text, specialty):
    result = rules_triage([{"role": "user", "content": text}], PATIENT)
    assert result.specialty == specialty
    assert result.urgency == "routine"


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Explain my lab report", "results"),
        ("What happened with my health this year?", "health_story"),
        ("show me my care plan", "care_plan"),
    ],
)
def test_rules_detect_navigation_intents(text, intent):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent == intent
