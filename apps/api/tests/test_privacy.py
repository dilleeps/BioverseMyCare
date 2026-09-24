"""Patient Privacy Center: consents, access log, privacy export."""

import psycopg
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.agents.intents import REGISTRY
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK


def _conn():
    return psycopg.connect(DB, row_factory=dict_row)


def _maya_report(client):
    return client.get(f"/api/patients/{P_MAYA}/reports", headers=MAYA).json()[0]["id"]


def test_consents_list_defaults_with_explanations(client):
    body = client.get("/api/privacy/consents", headers=MAYA).json()
    by_scope = {c["scope"]: c for c in body["choices"]}
    assert by_scope["ai_processing"]["granted"] is True and by_scope["ai_processing"]["is_default"]
    assert by_scope["research_matching"]["granted"] is False
    assert "rules" in by_scope["ai_processing"]["when_off"].lower()
    assert body["ai_allowed"] is True


def test_ai_opt_out_updates_consents_and_ai_allowed(client):
    r = client.put("/api/privacy/consents/ai_processing", headers=MAYA, json={"granted": False})
    assert r.status_code == 200, r.text
    assert r.json()["ai_allowed"] is False
    with _conn() as conn:
        row = conn.execute(
            "SELECT status, updated_by::text FROM consents WHERE patient_id = %s AND scope = 'ai_processing'", (P_MAYA,)
        ).fetchone()
        assert row["status"] == "denied"
        assert consent.ai_allowed(conn, P_MAYA) is False
        event = conn.execute(
            "SELECT action, patient_id::text FROM audit_events WHERE entity_type = 'consent' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert event == {"action": "consent_denied", "patient_id": P_MAYA}

    r = client.put("/api/privacy/consents/ai_processing", headers=MAYA, json={"granted": True})
    assert r.json()["ai_allowed"] is True
    r = client.put("/api/privacy/consents/research_matching", headers=MAYA, json={"granted": True})
    assert {c["scope"]: c["granted"] for c in r.json()["choices"]}["research_matching"] is True


def test_caregiver_and_unknown_scopes_are_not_self_service(client):
    assert client.put("/api/privacy/consents/caregiver_access", headers=MAYA, json={"granted": True}).status_code == 422
    assert client.put("/api/privacy/consents/anything", headers=MAYA, json={"granted": True}).status_code == 422


def test_caregiver_grants_listed_read_only(client):
    from bioverse.db.seed import U_PARK

    with _conn() as conn:
        consent.set_status(conn, patient_id=P_MAYA, scope="caregiver_access", status="granted", actor=None,
                           grantee=U_PARK, detail={"permissions": ["appointments"]})
        conn.commit()
    caregivers = client.get("/api/privacy/consents", headers=MAYA).json()["caregivers"]
    assert caregivers[0]["name"] == "Jun Park"
    assert caregivers[0]["permissions"] == ["appointments"]


def test_access_log_shows_clinician_view_and_excludes_others(client):
    report_id = _maya_report(client)
    seeded = [i["id"] for i in client.get("/api/privacy/access-log", headers=MAYA).json()["items"]]
    assert client.get(f"/api/reports/{report_id}", headers=OKAFOR).status_code == 200
    # Maya viewing her own report is her own action; Park's activity is another patient's.
    client.get(f"/api/reports/{report_id}", headers=MAYA)
    client.post("/api/conversations", headers=PARK)

    log = client.get("/api/privacy/access-log", headers=MAYA).json()["items"]
    viewed = [i for i in log if i["action"] == "report_viewed" and i["id"] not in seeded]
    assert len(viewed) == 1
    assert viewed[0]["who"] == "Dr. Adaeze Okafor" and viewed[0]["role"] == "Clinician"
    assert viewed[0]["what"] == "Opened one of your lab reports"
    assert not any(i["is_me"] for i in log)

    with _conn() as conn:
        park_ids = {r["id"] for r in conn.execute("SELECT id FROM audit_events WHERE patient_id = %s", (P_PARK,))}
    assert park_ids and not park_ids & {i["id"] for i in log}

    mine = client.get("/api/privacy/access-log?include_mine=true", headers=MAYA).json()["items"]
    assert any(i["is_me"] and i["action"] == "report_viewed" for i in mine)


def test_access_log_keyset_pagination(client):
    first = client.get("/api/privacy/access-log?include_mine=true&limit=2", headers=MAYA).json()
    assert len(first["items"]) == 2 and first["next_before_id"]
    second = client.get(f"/api/privacy/access-log?include_mine=true&limit=2&before_id={first['next_before_id']}",
                        headers=MAYA).json()
    assert all(i["id"] < first["items"][-1]["id"] for i in second["items"])


def test_privacy_export_is_json_and_audited(client):
    r = client.get("/api/privacy/export", headers=MAYA)
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["patient_id"] == P_MAYA
    assert {c["scope"] for c in body["consents"]["choices"]} == {"ai_processing", "research_matching"}
    assert isinstance(body["access_log"], list)
    with _conn() as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM audit_events WHERE action = 'privacy_export' AND patient_id = %s", (P_MAYA,)
        ).fetchone()["n"] == 1


def test_privacy_center_is_patients_only(client):
    for headers in (OKAFOR, ADMIN):
        assert client.get("/api/privacy/consents", headers=headers).status_code == 403
        assert client.get("/api/privacy/access-log", headers=headers).status_code == 403
        assert client.put("/api/privacy/consents/ai_processing", headers=headers, json={"granted": False}).status_code == 403
    assert client.get("/api/privacy/consents").status_code == 401


def test_privacy_intent_routes_from_front_door(client):
    assert REGISTRY["privacy"].to == "/privacy"
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    convo = client.post(f"/api/conversations/{cid}/messages", headers=MAYA,
                        json={"text": "Who has accessed my record?"}).json()
    assert convo["messages"][-1]["payload"] == {"kind": "link", "to": "/privacy", "label": "Open my privacy center"}
