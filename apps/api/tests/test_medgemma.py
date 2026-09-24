"""MedGemma provider: request shape, JSON extraction and repair, provider order and fallback."""

import io
import json

import pytest
from pydantic import BaseModel

from bioverse.agents import llm, medgemma
from bioverse.config import get_settings


class Triage(BaseModel):
    urgency: str
    specialty: str


class FakeEndpoint:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req.full_url, json.loads(req.data), dict(req.header_items())))
        body = {"predictions": {"choices": [{"message": {"content": self.replies.pop(0)}}]}}
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("BIOVERSE_MEDGEMMA_ENDPOINT", "1234567890")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("BIOVERSE_MEDGEMMA_DNS", "1234567890.us-central1-555.prediction.vertexai.goog")
    monkeypatch.setenv("BIOVERSE_GCP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("BIOVERSE_MEDGEMMA_MODEL", "medgemma-1.5-4b-it")

    def install(*replies):
        fake = FakeEndpoint(replies)
        monkeypatch.setattr(medgemma.urllib.request, "urlopen", fake)
        return fake
    return install


def test_request_shape_and_image_conversion(endpoint):
    fake = endpoint('{"urgency": "routine", "specialty": "Dermatology"}')
    out = medgemma.parse(system="You triage.", output_format=Triage, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
        {"type": "text", "text": "Itchy rash"}]}])
    assert out == Triage(urgency="routine", specialty="Dermatology")
    url, body, headers = fake.requests[0]
    assert url == ("https://1234567890.us-central1-555.prediction.vertexai.goog/v1/projects/demo-project/"
                   "locations/us-central1/endpoints/1234567890:predict")
    assert headers["Authorization"] == "Bearer test-token"
    inst = body["instances"][0]
    assert inst["@requestFormat"] == "chatCompletions" and inst["temperature"] == 0
    assert inst["messages"][0]["role"] == "system" and "JSON Schema" in inst["messages"][0]["content"][0]["text"]
    assert inst["messages"][1]["content"][0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def test_thinking_trace_and_fences_are_stripped(endpoint):
    endpoint('<unused94>thought\nlet me think {not json}<unused95>```json\n{"urgency": "moderate", "specialty": "Cardiology"}\n```')
    assert medgemma.parse(system="s", messages=[{"role": "user", "content": "chest"}],
                          output_format=Triage).specialty == "Cardiology"


def test_one_repair_turn_then_give_up(endpoint):
    fake = endpoint("Sure! The urgency is routine.", '{"urgency": "routine", "specialty": "Primary care"}')
    assert medgemma.parse(system="s", messages=[{"role": "user", "content": "x"}],
                          output_format=Triage).specialty == "Primary care"
    assert len(fake.requests) == 2 and "corrected JSON" in json.dumps(fake.requests[1][1])
    endpoint("nope", "still nope")
    with pytest.raises(medgemma.MedGemmaUnavailable):
        medgemma.parse(system="s", messages=[{"role": "user", "content": "x"}], output_format=Triage)


def test_text_only_endpoint_refuses_images(endpoint, monkeypatch):
    monkeypatch.setenv("BIOVERSE_MEDGEMMA_MULTIMODAL", "false")
    with pytest.raises(medgemma.MedGemmaUnavailable):
        medgemma.to_chat_messages("s", [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A"}}]}])


def test_llm_uses_medgemma_first_and_falls_back_to_claude(endpoint, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AI", "on")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()
    try:
        assert get_settings().ai_providers == ("medgemma", "claude")
        endpoint('{"urgency": "routine", "specialty": "Neurology"}')
        r = llm.parse(system="s", messages=[{"role": "user", "content": "x"}], output_format=Triage)
        assert r.model == "medgemma-1.5-4b-it" and not r.fell_back and llm.active_provider() == "medgemma"

        endpoint("bad", "bad")          # MedGemma fails twice -> Claude answers
        claude_calls = []

        class Resp:
            stop_reason, stop_details, model = "end_turn", None, "claude-opus-5"
            parsed_output = Triage(urgency="routine", specialty="Neurology")
            usage = None

        def fake_parse(**kw):
            claude_calls.append(kw)
            return Resp()
        from types import SimpleNamespace
        llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=fake_parse))))
        r = llm.parse(system="s", messages=[{"role": "user", "content": "x"}], output_format=Triage)
        assert r.model == "claude-opus-5" and r.fell_back and claude_calls
    finally:
        llm.set_client(None)
        get_settings.cache_clear()


def test_rules_mode_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("BIOVERSE_MEDGEMMA_ENDPOINT", raising=False)
    monkeypatch.setenv("BIOVERSE_AI", "on")
    get_settings.cache_clear()
    try:
        with pytest.raises(llm.LLMUnavailable):
            llm.parse(system="s", messages=[{"role": "user", "content": "x"}], output_format=Triage)
    finally:
        get_settings.cache_clear()
