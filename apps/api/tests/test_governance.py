"""Compliance audit, hash chain, break-glass, retention dry run, incidents."""

import copy

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.routers.governance import GENESIS, load_chain, verify_rows
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK


def _conn():
    return psycopg.connect(DB, row_factory=dict_row)


def _event_count():
    with _conn() as conn:
        return conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"]


# --- Audit search ---------------------------------------------------------------------------------


def test_audit_search_filters(client):
    report = client.get(f"/api/patients/{P_MAYA}/reports", headers=MAYA).json()[0]["id"]
    client.get(f"/api/reports/{report}", headers=OKAFOR)

    from bioverse.db.seed import U_OKAFOR

    by_actor = client.get(f"/api/governance/audit?actor={U_OKAFOR}&action=report_viewed", headers=ADMIN).json()
    assert by_actor["items"] and all(i["actor_name"] == "Dr. Adaeze Okafor" for i in by_actor["items"])

    park = client.get(f"/api/governance/audit?patient={P_PARK}", headers=ADMIN).json()["items"]
    assert park and all(i["patient_id"] == P_PARK for i in park)

    ai = client.get("/api/governance/audit?agent_only=true&limit=200", headers=ADMIN).json()["items"]
    assert ai and all(i["agent"] for i in ai)

    by_type = client.get("/api/governance/audit?entity_type=diagnostic_report", headers=ADMIN).json()["items"]
    assert by_type and {i["entity_type"] for i in by_type} == {"diagnostic_report"}

    text = client.get("/api/governance/audit?q=okafor", headers=ADMIN).json()["items"]
    assert text

    future = client.get("/api/governance/audit?date_from=2999-01-01", headers=ADMIN).json()["items"]
    assert future == []
    past = client.get("/api/governance/audit?date_to=2000-01-01", headers=ADMIN).json()["items"]
    assert past == []

    assert client.get("/api/governance/audit?patient=not-an-id", headers=ADMIN).status_code == 422


def test_audit_keyset_pagination_covers_everything_once(client):
    total = _event_count()
    seen, before = [], None
    while True:
        url = "/api/governance/audit?limit=5" + (f"&before_id={before}" if before else "")
        page = client.get(url, headers=ADMIN).json()
        seen += [i["id"] for i in page["items"]]
        before = page["next_before_id"]
        if not before:
            break
    assert len(seen) == len(set(seen)) == total
    assert seen == sorted(seen, reverse=True)


def test_audit_csv_export(client):
    r = client.get(f"/api/governance/audit/export.csv?patient={P_MAYA}", headers=ADMIN)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,occurred_at,actor_name")
    assert len(lines) > 1
    with _conn() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'audit_exported'").fetchone()["n"] == 1


def test_audit_screens_are_admin_only(client):
    for headers in (MAYA, OKAFOR):
        assert client.get("/api/governance/audit", headers=headers).status_code == 403
        assert client.get("/api/governance/audit/export.csv", headers=headers).status_code == 403
        assert client.post("/api/governance/audit/verify", headers=headers).status_code == 403
        assert client.get("/api/governance/retention", headers=headers).status_code == 403
        assert client.post("/api/governance/retention/dry-run", headers=headers).status_code == 403
        assert client.get("/api/governance/break-glass", headers=headers).status_code == 403


# --- Hash chain -----------------------------------------------------------------------------------


def test_hash_chain_builds_extends_and_verifies(client):
    first = client.post("/api/governance/audit/verify", headers=ADMIN).json()
    assert first["ok"] is True and first["first_mismatch"] is None
    assert first["appended"] == first["chain_length"] > 0

    client.post("/api/conversations", headers=MAYA)
    second = client.post("/api/governance/audit/verify", headers=ADMIN).json()
    assert second["ok"] is True
    assert second["checked"] == first["chain_length"]
    # The new conversation event and the first verification's own audit event.
    assert second["appended"] == 2

    status = client.get("/api/governance/audit/chain", headers=ADMIN).json()
    assert status["chained"] == second["chain_length"]
    assert status["head_hash"] == second["head_hash"]


def test_hash_chain_detects_tampered_copy(client):
    client.post("/api/governance/audit/verify", headers=ADMIN)
    with _conn() as conn:
        events, chain = load_chain(conn)
    assert verify_rows(events, chain)["ok"] is True
    assert chain[0]["prev_hash"] == GENESIS

    # audit_events cannot be updated, so tamper with a copy of the rows and check against the stored chain.
    target = chain[len(chain) // 2]["event_id"]
    tampered = copy.deepcopy(events)
    for e in tampered:
        if e["id"] == target:
            e["action"] = "nothing_to_see_here"
    result = verify_rows(tampered, chain)
    assert result["ok"] is False
    assert result["first_mismatch"]["event_id"] == target
    assert "contents" in result["first_mismatch"]["reason"]

    # A detail change is caught too, and so is a removed event and a re-linked chain.
    tampered = copy.deepcopy(events)
    tampered[0]["detail"] = {**(tampered[0]["detail"] or {}), "extra": 1}
    assert verify_rows(tampered, chain)["ok"] is False
    missing = [e for e in events if e["id"] != target]
    assert verify_rows(missing, chain)["first_mismatch"]["reason"].startswith("event missing")
    relinked = copy.deepcopy(chain)
    del relinked[1]
    assert "link broken" in verify_rows(events, relinked)["first_mismatch"]["reason"]


def test_audit_chain_is_append_only(client):
    client.post("/api/governance/audit/verify", headers=ADMIN)
    with _conn() as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE audit_chain SET hash = 'x'")


# --- Break-glass ----------------------------------------------------------------------------------


def test_break_glass_requires_reason_and_is_audited(client):
    r = client.post("/api/governance/break-glass", headers=OKAFOR, json={"patient_id": P_PARK, "reason": "need"})
    assert r.status_code == 422
    r = client.post("/api/governance/break-glass", headers=OKAFOR, json={"patient_id": P_PARK, "reason": "   " * 10})
    assert r.status_code == 422

    reason = "Patient arrived unconscious in the emergency department"
    r = client.post("/api/governance/break-glass", headers=OKAFOR,
                    json={"patient_id": P_PARK, "reason": reason, "minutes": 30})
    assert r.status_code == 201, r.text
    grant = r.json()
    assert grant["active"] is True and grant["patient_name"] == "Jun Park"

    with _conn() as conn:
        event = conn.execute(
            "SELECT patient_id::text, detail FROM audit_events WHERE action = 'break_glass' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert event["patient_id"] == P_PARK and event["detail"]["reason"] == reason

    flagged = client.get("/api/governance/audit?break_glass_only=true", headers=ADMIN).json()["items"]
    assert flagged and all(i["break_glass"] for i in flagged)
    assert client.get("/api/governance/break-glass", headers=ADMIN).json()[0]["reason"] == reason

    # The patient sees it in their access log, flagged as emergency access. (Park is the patient here.)
    from tests.conftest import PARK

    log = client.get("/api/privacy/access-log", headers=PARK).json()["items"]
    assert any(i["emergency_access"] and i["reason"] == reason for i in log)


def test_break_glass_expires_and_can_end_early(client):
    from bioverse.routers.governance import has_active_grant
    from bioverse.db.seed import U_OKAFOR

    grant = client.post("/api/governance/break-glass", headers=OKAFOR,
                        json={"patient_id": P_PARK, "reason": "Covering on-call, patient phoned with chest pain"}).json()
    with _conn() as conn:
        assert has_active_grant(conn, U_OKAFOR, P_PARK)
        # Simulate the passage of time: move the grant's window into the past.
        conn.execute("UPDATE break_glass_grants SET created_at = now() - interval '2 hours', "
                     "expires_at = now() - interval '1 hour' WHERE id = %s", (grant["id"],))
        conn.commit()
        assert not has_active_grant(conn, U_OKAFOR, P_PARK)
    mine = client.get("/api/governance/break-glass/mine", headers=OKAFOR).json()
    assert mine[0]["active"] is False
    assert client.post(f"/api/governance/break-glass/{grant['id']}/end", headers=OKAFOR).status_code == 404

    second = client.post("/api/governance/break-glass", headers=OKAFOR,
                         json={"patient_id": P_PARK, "reason": "Reviewing a transferred patient overnight"}).json()
    assert client.post(f"/api/governance/break-glass/{second['id']}/end", headers=OKAFOR).json()["active"] is False
    with _conn() as conn:
        assert not has_active_grant(conn, U_OKAFOR, P_PARK)


def test_break_glass_role_denials(client):
    body = {"patient_id": P_PARK, "reason": "Patient arrived unconscious in the ED"}
    assert client.post("/api/governance/break-glass", headers=MAYA, json=body).status_code == 403
    assert client.post("/api/governance/break-glass", headers=ADMIN, json=body).status_code == 403
    assert client.post("/api/governance/break-glass", headers=OKAFOR,
                       json={**body, "patient_id": "00000000-0000-0000-0000-000000009999"}).status_code == 404
    assert client.post("/api/governance/break-glass", headers=OKAFOR, json={**body, "minutes": 600}).status_code == 422


# --- Retention ------------------------------------------------------------------------------------


def test_retention_dry_run_counts_without_deleting(client):
    policies = client.get("/api/governance/retention", headers=ADMIN).json()
    assert policies["deletion_enabled"] is False
    assert {p["category"] for p in policies["policies"]} == {"conversations", "messages", "audit_events", "documents"}

    r = client.put("/api/governance/retention/documents", headers=ADMIN, json={"retention_days": 365, "notes": "One year"})
    assert r.status_code == 200
    assert client.put("/api/governance/retention/audit_events", headers=ADMIN,
                      json={"retention_days": 90}).status_code == 422
    assert client.put("/api/governance/retention/nope", headers=ADMIN, json={"retention_days": 90}).status_code == 404

    with _conn() as conn:
        before = conn.execute("SELECT count(*) AS n FROM diagnostic_reports").fetchone()["n"]
    dry = client.post("/api/governance/retention/dry-run", headers=ADMIN).json()
    assert dry["dry_run"] is True and dry["deleted"] == 0
    docs = next(c for c in dry["categories"] if c["category"] == "documents")
    # Maya's lipid panels from 560 and 367 days ago are older than a year.
    assert docs["would_purge"] == 2
    assert docs["total"] == before
    with _conn() as conn:
        assert conn.execute("SELECT count(*) AS n FROM diagnostic_reports").fetchone()["n"] == before
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'retention_dry_run'").fetchone()["n"] == 1


# --- Incidents ------------------------------------------------------------------------------------


def test_incident_report_and_triage_workflow(client):
    body = {"category": "ai_safety", "severity": "high", "title": "Routine reply to chest pain",
            "description": "The assistant replied with routine booking to a message about chest pain.",
            "patient_id": P_MAYA, "linked_entity_type": "conversation"}
    r = client.post("/api/governance/incidents", headers=OKAFOR, json=body)
    assert r.status_code == 201, r.text
    incident = r.json()
    assert incident["status"] == "open" and incident["patient_name"] == "Maya Thornton"

    # Reporters see their own; patients cannot report; clinicians cannot triage.
    assert any(i["id"] == incident["id"] for i in client.get("/api/governance/incidents", headers=OKAFOR).json())
    assert client.post("/api/governance/incidents", headers=MAYA, json=body).status_code == 403
    assert client.post(f"/api/governance/incidents/{incident['id']}/transition", headers=OKAFOR,
                       json={"status": "investigating"}).status_code == 403

    url = f"/api/governance/incidents/{incident['id']}/transition"
    assert client.post(url, headers=ADMIN, json={"status": "investigating", "note": "Looking"}).json()["status"] == "investigating"
    assert client.post(url, headers=ADMIN, json={"status": "resolved"}).status_code == 422
    done = client.post(url, headers=ADMIN, json={"status": "resolved", "note": "Rule added"}).json()
    assert done["status"] == "resolved" and done["resolution"] == "Rule added"
    assert [h["status"] for h in done["history"]] == ["open", "investigating", "resolved"]
    assert client.post(url, headers=ADMIN, json={"status": "open"}).status_code == 409

    with _conn() as conn:
        events = conn.execute(
            "SELECT action FROM audit_events WHERE entity_id = %s AND patient_id = %s ORDER BY id",
            (incident["id"], P_MAYA),
        ).fetchall()
    assert [e["action"] for e in events] == ["incident_reported", "incident_updated", "incident_updated"]

    admin_list = client.get("/api/governance/incidents", headers=ADMIN).json()
    assert len(admin_list) >= 3  # includes the two seeded demo incidents
