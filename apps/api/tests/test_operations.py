"""Hospital operations dashboard and the Hospital Agent (rules path and a fake-Claude tool-use path)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest

from bioverse.agents import hospital_agent as ha
from bioverse.agents import llm
from bioverse.db.seed import DR_FERREIRA, DR_OKAFOR
from tests.conftest import ADMIN, DB, MAYA, OKAFOR


def dashboard(client):
    r = client.get("/api/ops/dashboard", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def row(rows, specialty):
    return next(r for r in rows if r["specialty"] == specialty)


def converse(client, *turns):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    for body in turns:
        r = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json=body)
        assert r.status_code == 200, r.text
    return r.json()


def window_bounds(days_from: int, days: int):
    clk = ha.clock()
    start = clk.today_start + timedelta(days=days_from)
    return start, start + timedelta(days=days)


# --- Access --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/ops/dashboard", "/api/ops/assistant/metrics"])
def test_operations_reject_non_admins(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=OKAFOR).status_code == 403
    assert client.get(path, headers=MAYA).status_code == 403


def test_assistant_rejects_non_admins(client):
    body = {"question": "where are we short on capacity?"}
    assert client.post("/api/ops/assistant", json=body).status_code == 401
    assert client.post("/api/ops/assistant", headers=OKAFOR, json=body).status_code == 403
    assert client.post("/api/ops/assistant", headers=MAYA, json=body).status_code == 403


# --- Metric correctness ------------------------------------------------------------------------------------


def test_capacity_matches_slot_table(client):
    data = dashboard(client)
    start, end = window_bounds(1, 7)
    with psycopg.connect(DB) as conn:
        expected = dict(conn.execute(
            """
            SELECT pr.specialty, count(*) FILTER (WHERE s.status = 'booked') || '/' || count(*)
            FROM slots s JOIN practitioners pr ON pr.id = s.practitioner_id
            WHERE s.starts_at >= %s AND s.starts_at < %s GROUP BY 1
            """,
            (start, end),
        ).fetchall())
    for r in data["capacity_next_7_days"]["rows"]:
        if r["capacity"]:
            assert f"{r['booked']}/{r['capacity']}" == expected[r["specialty"]]
            assert r["free"] == r["capacity"] - r["booked"]
            assert r["utilization_pct"] == round(100 * r["booked"] / r["capacity"], 1)
    derm = row(data["capacity_next_7_days"]["rows"], "Dermatology")
    assert derm["departments"] == ["Dermatology"]


def test_booking_moves_capacity_and_utilization(client):
    before = row(dashboard(client)["capacity_next_7_days"]["rows"], "Dermatology")
    start, end = window_bounds(1, 7)
    slots = client.get(f"/api/practitioners/{DR_FERREIRA}/slots?limit=30", headers=MAYA).json()
    slot = next(s for s in slots if start <= datetime.fromisoformat(s["starts_at"]) < end)
    assert client.post("/api/appointments", headers=MAYA, json={"slot_id": slot["id"]}).status_code == 201

    after = row(dashboard(client)["capacity_next_7_days"]["rows"], "Dermatology")
    assert after["booked"] == before["booked"] + 1
    assert after["free"] == before["free"] - 1
    assert after["capacity"] == before["capacity"]
    assert after["utilization_pct"] == round(100 * after["booked"] / after["capacity"], 1)


def test_seeded_dermatology_demand_exceeds_capacity(client):
    data = dashboard(client)["demand_vs_capacity"]
    derm = row(data["rows"], "Dermatology")
    assert derm["status"] == "short"
    assert derm["demand_last_7_days"] > derm["free_next_7_days"]
    assert derm["message"].startswith("Dermatology demand exceeds next-7-day capacity")
    assert "Dermatology" in data["short"]
    assert data["rows"][0]["specialty"] == "Dermatology", "shortages sort first"


def test_new_intake_counts_toward_demand_and_today(client):
    before = dashboard(client)
    converse(client, {"text": "I have an itchy rash on my forearm"})
    after = dashboard(client)

    demand = lambda d: row(d["demand_vs_capacity"]["rows"], "Dermatology")["demand_last_7_days"]  # noqa: E731
    assert demand(after) == demand(before) + 1
    assert after["intakes_today"]["total"] == before["intakes_today"]["total"] + 1
    derm_before = next((r for r in before["intakes_today"]["by_specialty"] if r["specialty"] == "Dermatology"), {"routine": 0})
    derm_after = row(after["intakes_today"]["by_specialty"], "Dermatology")
    assert derm_after["routine"] == derm_before["routine"] + 1


def test_red_flag_escalations_today_and_acknowledgement(client):
    before = dashboard(client)["red_flags_today"]
    assert before["count"] >= 1, "seed includes one escalation today"
    converse(client, {"text": "my chest hurts"}, {"safety_answer": ["breathless"]})
    after = dashboard(client)
    flags = after["red_flags_today"]
    assert flags["count"] == before["count"] + 1
    assert flags["waiting"] == before["waiting"] + 1

    okafor = row_by_name(after["clinician_workload"]["rows"], "Dr. Adaeze Okafor")
    assert okafor["urgent_items"] >= 1

    item = next(i for i in client.get("/api/clinician/review-queue", headers=OKAFOR).json() if i["kind"] == "red_flag")
    client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "acknowledge"})
    flags = dashboard(client)["red_flags_today"]
    assert flags["acknowledged"] == before["acknowledged"] + 1
    assert flags["waiting"] == before["waiting"]


def row_by_name(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_clinician_workload_matches_review_queue(client):
    rows = dashboard(client)["clinician_workload"]["rows"]
    with psycopg.connect(DB) as conn:
        expected = dict(conn.execute(
            "SELECT practitioner_id::text, count(*) FROM review_items WHERE status = 'open' GROUP BY 1"
        ).fetchall())
    for r in rows:
        assert r["open_items"] == expected.get(r["practitioner_id"], 0)
    okafor = next(r for r in rows if r["practitioner_id"] == DR_OKAFOR)
    assert okafor["open_items"] == len(client.get("/api/clinician/review-queue", headers=OKAFOR).json())
    # Seeded story: Dr. Ferreira carries the largest backlog, with an item several days old.
    assert rows[0]["practitioner_id"] == DR_FERREIRA
    assert rows[0]["oldest_open_hours"] >= 72
    assert [r["open_items"] for r in rows] == sorted((r["open_items"] for r in rows), reverse=True)


def test_dashboard_has_no_patient_identifiers(client):
    text = str(dashboard(client))
    for name in ("Maya", "Thornton", "Park", "Haddad", "Sofia", "Tomas"):
        assert name not in text


# --- Hospital Agent: rules path ------------------------------------------------------------------------------


def ask(client, question):
    r = client.post("/api/ops/assistant", headers=ADMIN, json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()


def test_rules_agent_answers_capacity_question_from_metrics(client):
    out = ask(client, "Where are we short on capacity next week?")
    assert out["produced_by"] == "hospital-agent/rules"
    assert out["model"] is None
    names = [m["name"] for m in out["metrics_used"]]
    assert names[0] == "get_demand_vs_capacity"
    derm = row(out["metrics_used"][0]["result"]["rows"], "Dermatology")
    assert f"{derm['demand_last_7_days']} routed intakes" in out["answer"]
    assert f"{derm['free_next_7_days']} free slots" in out["answer"]


def test_rules_agent_answers_backlog_question(client):
    out = ask(client, "Which clinician has the biggest review backlog?")
    assert [m["name"] for m in out["metrics_used"]] == ["get_clinician_workload"]
    top = out["metrics_used"][0]["result"]["rows"][0]
    assert out["answer"].startswith(f"Biggest review backlog: {top['name']} with {top['open_items']} open items")


def test_rules_agent_falls_back_to_overview_and_audits(client):
    out = ask(client, "What should I have for lunch?")
    assert out["answer"].startswith("I couldn't match that")
    assert [m["name"] for m in out["metrics_used"]] == ["get_demand_vs_capacity", "get_clinician_workload"]
    with psycopg.connect(DB) as conn:
        audit = conn.execute(
            "SELECT agent, model, detail FROM audit_events WHERE action = 'hospital_agent_question' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit[0] == "hospital-agent/rules"
    assert audit[1] is None
    assert audit[2]["question"] == "What should I have for lunch?"
    assert audit[2]["metrics"] == ["get_demand_vs_capacity", "get_clinician_workload"]


def test_assistant_validates_question(client):
    assert client.post("/api/ops/assistant", headers=ADMIN, json={"question": "  "}).status_code == 422
    assert client.post("/api/ops/assistant", headers=ADMIN, json={"question": "x" * 501}).status_code == 422


def test_assistant_lists_only_read_only_metric_tools(client):
    tools = client.get("/api/ops/assistant/metrics", headers=ADMIN).json()
    assert {t["name"] for t in tools} == set(ha.REGISTRY)
    assert all(t["name"].startswith("get_") for t in tools)


# --- Hospital Agent: Claude tool-use path (fake client) ----------------------------------------------------------


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_use(*calls):
    return SimpleNamespace(
        stop_reason="tool_use", model="claude-opus-5", stop_details=None,
        content=[SimpleNamespace(type="tool_use", id=f"toolu_{i}", name=name, input=args)
                 for i, (name, args) in enumerate(calls)],
    )


def final(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5", stop_details=None,
                           content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def fake_claude(monkeypatch):
    def install(*responses):
        messages = FakeMessages(responses)
        llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=messages)))
        return messages

    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    yield install
    llm.set_client(None)


def test_claude_path_calls_metric_tools_and_cites_them(client, fake_claude):
    messages = fake_claude(
        tool_use(("get_demand_vs_capacity", {}), ("get_capacity", {"window": "next_7_days"})),
        final("Dermatology is short next week: 16 routed intakes vs 14 free slots."),
    )
    out = ask(client, "where are we short on capacity next week?")

    assert out["produced_by"] == "hospital-agent/claude"
    assert out["model"] == "claude-opus-5"
    assert out["answer"].startswith("Dermatology is short")
    assert [m["name"] for m in out["metrics_used"]] == ["get_demand_vs_capacity", "get_capacity"]
    assert out["metrics_used"][1]["args"] == {"window": "next_7_days"}

    first = messages.calls[0]
    assert first["fallbacks"] == "default" and llm.FALLBACK_BETA in first["betas"]
    assert {t["name"] for t in first["tools"]} == set(ha.REGISTRY)
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    assert "<question>" in first["messages"][0]["content"]
    assert "not instructions" in first["system"]

    # Both tool results go back in ONE user message, as JSON of the real metric values.
    second = messages.calls[1]["messages"]
    results = second[-1]["content"]
    assert second[-1]["role"] == "user" and len(results) == 2
    assert {r["tool_use_id"] for r in results} == {"toolu_0", "toolu_1"}
    assert '"Dermatology"' in results[0]["content"]

    with psycopg.connect(DB) as conn:
        audit = conn.execute(
            "SELECT agent, model, detail FROM audit_events WHERE action = 'hospital_agent_question' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit[0] == "hospital-agent/claude"
    assert audit[1] == "claude-opus-5"
    assert audit[2]["metrics"] == ["get_demand_vs_capacity", "get_capacity"]


def test_claude_unknown_tool_gets_an_error_result(client, fake_claude):
    messages = fake_claude(
        tool_use(("run_sql", {"query": "DELETE FROM patients"})),
        final("I don't have a metric for that."),
    )
    out = ask(client, "delete everything")
    result = messages.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert out["metrics_used"] == []


def test_claude_refusal_falls_back_to_rules(client, fake_claude):
    fake_claude(final("", stop_reason="refusal"))
    out = ask(client, "which clinician has the biggest review backlog?")
    assert out["produced_by"] == "hospital-agent/rules"
    assert [m["name"] for m in out["metrics_used"]] == ["get_clinician_workload"]


def test_claude_endless_tool_loop_falls_back_to_rules(client, fake_claude):
    fake_claude(*[tool_use(("get_intakes_today", {}))] * ha.MAX_ROUNDS)
    out = ask(client, "how many intakes today?")
    assert out["produced_by"] == "hospital-agent/rules"
    assert out["metrics_used"][0]["name"] == "get_intakes_today"
