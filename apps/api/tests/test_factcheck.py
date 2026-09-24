"""Health misinformation checker: claim extraction, verdicts, the no-invented-citations rule, safety, logging."""

import hashlib
import json
from types import SimpleNamespace

import psycopg
import pytest

from bioverse.agents import intents, llm
from bioverse.agents.triage import rules_triage
from bioverse.db.seeds.ids import _id
from bioverse.routers import factcheck as fc
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, as_user

STUDENT = as_user(_id(16001))


def check(client, text, headers=MAYA):
    res = client.post("/api/factcheck/check", headers=headers, json={"text": text})
    assert res.status_code == 200, res.text
    return res.json()


# --- Rules-mode claim extraction ------------------------------------------------------------------


def test_rules_extraction_keeps_health_claims_and_drops_noise():
    text = (
        "FWD: Forwarded many times\n"
        "URGENT!!! Vaccines cause autism 😱😱. Is that why my cousin changed?\n"
        "Please share with everyone you love.\n"
        "Garlic cures high blood pressure. The weather is lovely today."
    )
    claims = fc.extract_claims_rules(text)
    assert claims == ["Vaccines cause autism", "Garlic cures high blood pressure"]


def test_rules_extraction_caps_claims_and_dedupes():
    text = ". ".join(["Garlic cures high blood pressure"] * 3 + [f"Vitamin {c} cures colds" for c in "ABCDEFG"])
    claims = fc.extract_claims_rules(text)
    assert len(claims) == fc.MAX_CLAIMS
    assert claims.count("Garlic cures high blood pressure") == 1


def test_negation_detection():
    assert fc.is_negated("Vaccines do not cause autism")
    assert fc.is_negated("The idea that vaccines cause autism is a myth")
    assert not fc.is_negated("Garlic cures high blood pressure with no side effects")
    assert not fc.is_negated("Vaccines cause autism")


# --- Verdict mapping ------------------------------------------------------------------------------------


def test_seeded_examples_get_the_expected_verdicts_with_library_citations(client):
    examples = {e["claim"]: e["text"] for e in client.get("/api/factcheck/examples", headers=MAYA).json()}
    assert {"Vaccines cause autism", "Garlic cures high blood pressure",
            "Walking 30 minutes a day lowers blood pressure"} <= set(examples)

    vax = check(client, examples["Vaccines cause autism"])
    claim = next(c for c in vax["claims"] if "autism" in c["claim"].lower())
    assert claim["verdict"] == "contradicted"
    assert {c["year"] for c in claim["citations"]} == {2020, 2014}
    assert any("Cochrane" in c["source"] for c in claim["citations"])

    garlic = check(client, "Garlic cures high blood pressure.")
    assert garlic["claims"][0]["verdict"] in ("misleading", "not_enough_evidence")
    assert garlic["claims"][0]["verdict"] == "misleading" and garlic["claims"][0]["citations"]

    walk = check(client, "Walking 30 minutes a day lowers blood pressure.")
    assert walk["claims"][0]["verdict"] == "supported"
    assert len(walk["claims"][0]["citations"]) == 3
    assert all({"title", "source", "year"} <= set(c) for c in walk["claims"][0]["citations"])


def test_negated_claim_flips_the_verdict(client):
    out = check(client, "Vaccines do not cause autism.")
    assert out["claims"][0]["verdict"] == "supported"


def test_every_citation_is_a_library_row(client):
    out = check(client, "Vaccines cause autism. Walking lowers blood pressure. Antibiotics cure colds.")
    cited = {c["item_id"] for claim in out["claims"] for c in claim["citations"]}
    assert cited
    with psycopg.connect(DB) as conn:
        rows = conn.execute("SELECT id::text, title FROM evidence_items WHERE id = ANY(%s::uuid[])",
                            (list(cited),)).fetchall()
    assert {r[0] for r in rows} == cited
    titles = {r[1] for r in rows}
    assert all(c["title"] in titles for claim in out["claims"] for c in claim["citations"])


def test_unknown_claim_is_not_enough_evidence_without_citations(client):
    out = check(client, "Drinking celery juice every morning cures eczema.")
    claim = out["claims"][0]
    assert claim["verdict"] == "not_enough_evidence"
    assert claim["citations"] == []
    assert "can't say" in claim["explanation"]


def test_review_without_surviving_evidence_falls_back_to_not_enough_evidence(client):
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE factcheck_claim_reviews SET evidence_item_ids = '{}' WHERE claim = 'Vaccines cause autism'")
    out = check(client, "Vaccines cause autism.")
    assert out["claims"][0]["verdict"] == "not_enough_evidence"
    assert out["claims"][0]["citations"] == []


def test_finalize_enforces_the_rule():
    assert fc.finalize("supported", "x", [])[0] == "not_enough_evidence"
    assert fc.finalize("made_up", "x", [{"item_id": "1"}])[0] == "not_enough_evidence"
    verdict, _, cited = fc.finalize("not_enough_evidence", "", [{"item_id": "1"}])
    assert verdict == "not_enough_evidence" and cited == []


# --- Claude path with a fake client ------------------------------------------------------------------


class FakeMessages:
    def __init__(self):
        self.outputs = {}
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outputs[kwargs["output_format"].__name__]
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="test-model",
                               usage=SimpleNamespace(iterations=None), parsed_output=out)


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    messages = FakeMessages()
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    yield messages
    llm.set_client(None)


def test_ai_citation_outside_the_retrieved_rows_is_dropped(client, fake_claude):
    fake_claude.outputs["ClaimsOut"] = fc.ClaimsOut(claims=["Statins lower LDL cholesterol"])
    fake_claude.outputs["VerdictOut"] = fc.VerdictOut(verdict="supported", explanation="Trust me.", citations=[42])
    out = check(client, "My uncle says statins lower LDL cholesterol.")
    claim = out["claims"][0]
    assert claim["method"] == "ai"
    assert claim["verdict"] == "not_enough_evidence"
    assert claim["citations"] == []
    # The pasted text went to the model as data, inside tags.
    extract = fake_claude.calls[0]
    assert "<pasted_text>" in extract["messages"][0]["content"] and "never instructions" in extract["system"]


def test_ai_verdict_cites_only_rows_it_was_given(client, fake_claude):
    fake_claude.outputs["ClaimsOut"] = fc.ClaimsOut(claims=["Statins lower LDL cholesterol"])
    fake_claude.outputs["VerdictOut"] = fc.VerdictOut(verdict="supported", explanation="Trials show it.",
                                                      citations=[1, 1, 99])
    out = check(client, "Statins lower LDL cholesterol.")
    claim = out["claims"][0]
    assert claim["verdict"] == "supported" and out["mode"] == "ai"
    assert len(claim["citations"]) == 1
    judge = fake_claude.calls[-1]["messages"][0]["content"]
    assert claim["citations"][0]["title"] in judge


def test_curated_reviews_are_used_even_with_ai_on(client, fake_claude):
    fake_claude.outputs["ClaimsOut"] = fc.ClaimsOut(claims=["Vaccines cause autism"])
    out = check(client, "Vaccines cause autism.")
    assert out["claims"][0]["verdict"] == "contradicted" and out["claims"][0]["method"] == "curated"
    assert all(c["output_format"].__name__ != "VerdictOut" for c in fake_claude.calls)


# --- Links, safety, limits -------------------------------------------------------------------------


def test_a_bare_link_asks_for_the_text(client):
    out = check(client, "https://example.com/miracle-cure")
    assert out["status"] == "needs_text"
    assert "doesn't open links" in out["message"]
    assert out["claims"] == []


def test_link_with_text_checks_the_text_and_says_the_link_was_not_opened(client):
    out = check(client, "Read this www.healthnews.example/x — Vaccines cause autism.")
    assert out["status"] == "checked"
    assert out["url_notice"] and "didn't open" in out["url_notice"]
    assert out["claims"][0]["verdict"] == "contradicted"


def test_emergency_in_the_text_comes_first(client):
    out = check(client, "My dad has crushing chest pain and is sweating. Garlic cures heart attacks, right?")
    assert out["safety"]["level"] == "emergency"
    assert "911" in out["safety"]["message"]


def test_text_limit(client):
    assert client.post("/api/factcheck/check", headers=MAYA, json={"text": "a" * 5001}).status_code == 422
    assert client.post("/api/factcheck/check", headers=MAYA, json={"text": "   "}).status_code == 422
    assert check(client, "Garlic cures high blood pressure. " + "x" * 4960)["status"] == "checked"


def test_no_claims(client):
    out = check(client, "Lovely weather today, see you at the park.")
    assert out["status"] == "no_claims"


# --- Sharing, logging, access -------------------------------------------------------------------------


def test_share_card_is_free_of_identifiers(client):
    out = check(client, "Maya Thornton (maya@example.com, 555-123-4567) says vaccines cause autism.")
    text = out["share"]["text"]
    assert "Maya" not in text and "maya@example.com" not in text and "555-123-4567" not in text
    assert "Contradicted" in text and "Cochrane" in text


def test_checks_are_logged_as_hash_and_verdicts_only(client):
    text = "Maya's friend said garlic cures high blood pressure."
    out = check(client, text)
    with psycopg.connect(DB) as conn:
        row = conn.execute("SELECT to_jsonb(f) FROM factcheck_checks f WHERE id = %s", (out["id"],)).fetchone()[0]
        audit = conn.execute(
            "SELECT detail, patient_id FROM audit_events WHERE action = 'factcheck_run' AND entity_id = %s",
            (out["id"],)).fetchone()
    assert row["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert row["verdicts"][0]["verdict"] == "misleading"
    dumped = json.dumps(row) + json.dumps(audit[0])
    assert "garlic" not in dumped.lower() and "Maya" not in dumped
    assert audit[1] is None


def test_every_role_can_check_and_only_admins_read_the_log(client):
    for headers in (MAYA, OKAFOR, ADMIN, STUDENT):
        assert check(client, "Walking lowers blood pressure.", headers)["claims"][0]["verdict"] == "supported"
    assert client.post("/api/factcheck/check", json={"text": "x"}).status_code == 401
    assert client.get("/api/factcheck/log", headers=MAYA).status_code == 403
    assert client.get("/api/factcheck/log", headers=STUDENT).status_code == 403
    log = client.get("/api/factcheck/log", headers=ADMIN).json()
    assert log["totals"]["supported"] == 4


def test_front_door_intents():
    def intent(text):
        return rules_triage([{"role": "user", "content": text}], {}).intent

    assert intent("My aunt forwarded this, is this true?") == "factcheck"
    assert intent("can you fact check a post for me") == "factcheck"
    assert intent("ask a cardiologist AI about statins") == "specialists"
    assert intent("I have chest pain since yesterday") not in ("factcheck", "specialists")
    assert intent("is this rash serious") != "factcheck"
    assert "factcheck" in intents.REGISTRY and "specialists" in intents.REGISTRY
