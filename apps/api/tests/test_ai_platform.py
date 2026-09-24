"""AI Platform console: registry, activity and traceability, evaluations, monitoring, review matrix."""

import hashlib

import psycopg
from psycopg.rows import dict_row

from bioverse import evals
from bioverse.agents.triage import SYSTEM_PROMPT
from tests.conftest import ADMIN, DB, MAYA, OKAFOR


def _conn():
    return psycopg.connect(DB, row_factory=dict_row)


def test_registry_lists_agents_with_live_prompt_fingerprint(client):
    agents = {a["id"]: a for a in client.get("/api/ai/agents", headers=ADMIN).json()}
    for nine in ("patient-agent", "intake-agent", "care-navigator-agent", "scheduling-agent", "doctor-agent",
                 "evidence-agent", "results-agent", "follow-up-agent", "hospital-agent"):
        assert nine in agents
    assert {"orchestrator", "red-flag-rules"} <= set(agents)

    intake = agents["intake-agent"]
    assert intake["status"] == "active"
    assert intake["prompt"]["hash"] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    assert intake["prompt_versions"][0]["prompt_hash"] == intake["prompt"]["hash"]
    assert intake["live_model"] == "rules mode (AI is off)"
    assert agents["red-flag-rules"]["ruleset_version"]
    assert agents["evidence-agent"]["status"] == "planned"


def test_activity_log_and_trace(client):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": "I have an itchy rash on my arm"})

    items = client.get("/api/ai/activity?agent=intake-agent", headers=ADMIN).json()["items"]
    assert items and all(i["agent"].startswith("intake-agent") for i in items)
    triage = next(i for i in items if i["action"] == "triage" and i["entity_id"] == cid)
    assert triage["path"] == "rules" and triage["agent_id"] == "intake-agent"

    trace = client.get(f"/api/ai/activity/{triage['id']}/trace", headers=ADMIN).json()
    assert trace["agent"]["id"] == "intake-agent"
    assert [a["question"] for a in trace["answers"]][0] == "Which agent produced it?"
    assert trace["patient_saw"]["kind"] == "care_options"
    assert "deterministic" in trace["prompt"]["basis"]
    with _conn() as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM audit_events WHERE action = 'ai_trace_viewed' AND patient_id = %s",
            (trace["event"]["patient_id"],),
        ).fetchone()["n"] == 1


def test_trace_links_human_review(client):
    # The seeded results-agent draft for Maya was approved by Dr. Okafor.
    items = client.get("/api/ai/activity?agent=results-agent", headers=ADMIN).json()["items"]
    trace = client.get(f"/api/ai/activity/{items[0]['id']}/trace", headers=ADMIN).json()
    reviewers = {r.get("reviewer") for r in trace["reviews"]}
    assert "Dr. Adaeze Okafor" in reviewers
    assert trace["patient_saw"]["kind"] == "approved explanation"


def test_claude_trace_infers_prompt_version(client):
    items = client.get("/api/ai/activity?agent=intake-agent", headers=ADMIN).json()["items"]
    claude = next(i for i in items if i["path"] == "claude")
    trace = client.get(f"/api/ai/activity/{claude['id']}/trace", headers=ADMIN).json()
    # Seeded history predates the first fingerprint observation, so the prompt is honestly "not recorded".
    assert trace["prompt"]["basis"].startswith(("inferred", "not recorded"))
    assert trace["event"]["model"] == "claude-opus-5"


def test_red_flag_eval_runs_and_records(client):
    cases = client.get("/api/ai/evals/cases?suite=red_flags", headers=ADMIN).json()
    assert len(cases) >= 40
    assert {"emergency", "crisis", "screen", "routine", "negation", "tricky"} <= {c["category"] for c in cases}

    r = client.post("/api/ai/evals/run", headers=ADMIN, json={"suite": "red_flags"})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["total"] == len(cases)
    # Every failure is a known, documented gap: no regressions, and every non-gap emergency or crisis is caught.
    assert run["regressions"] == 0, run["failures"]
    assert run["sensitivity_gated"] == 1.0
    assert run["gate_passed"] is True
    assert run["known_gap_failures"] == sum(c["known_gap"] for c in cases)

    runs = client.get("/api/ai/evals/runs?suite=red_flags", headers=ADMIN).json()
    assert runs[0]["id"] == run["id"] and runs[0]["ruleset_version"] == run["ruleset_version"]


def test_red_flag_eval_detects_a_regression():
    rows = [{"id": "x", "text": "I can't breathe", "category": "emergency", "expected_level": "none",
             "expected_topic": None, "known_gap": False, "note": None}]
    summary = evals.evaluate("red_flags", rows)
    assert summary["regressions"] == 1 and summary["gate_passed"] is False


def test_intent_eval_runs(client):
    run = client.post("/api/ai/evals/run", headers=ADMIN, json={"suite": "intent_routing"}).json()
    assert run["total"] == len(evals.INTENT_CASES)
    assert run["pass_rate"] is not None and run["ruleset_version"].startswith("rules-triage/")


def test_monitoring_counts_paths_and_reviews(client):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": "I have an itchy rash on my arm"})
    cid2 = client.post("/api/conversations", headers=MAYA).json()["id"]
    client.post(f"/api/conversations/{cid2}/messages", headers=MAYA, json={"text": "I can't breathe"})

    m = client.get("/api/ai/monitoring?days=30", headers=ADMIN).json()
    assert len(m["daily"]) == 30
    t = m["totals"]
    assert t["rules"] >= 3  # two seeded + one now
    assert t["claude"] >= 3 and t["claude_fallback"] >= 1
    assert t["escalations"] >= 1
    assert t["safety_checks"] >= 2
    assert m["review"]["reviewed"] >= 1 and m["review"]["rejection_rate"] is not None
    assert m["refusals"]["recorded"] is False


def test_review_matrix_seeded_from_docs(client):
    rows = client.get("/api/ai/review-matrix", headers=ADMIN).json()
    assert len(rows) == 11
    abnormal = next(r for r in rows if r["output_type"] == "Explanation of abnormal results")
    assert abnormal["default_policy"] == "Clinician review required"


def test_ai_console_is_admin_only(client):
    for headers in (MAYA, OKAFOR):
        for path in ("/api/ai/agents", "/api/ai/activity", "/api/ai/monitoring", "/api/ai/review-matrix",
                     "/api/ai/evals/runs", "/api/ai/evals/cases"):
            assert client.get(path, headers=headers).status_code == 403, path
        assert client.post("/api/ai/evals/run", headers=headers, json={"suite": "red_flags"}).status_code == 403
