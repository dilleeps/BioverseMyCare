"""Cross-module platform behavior: staff teams, and defaults for clinicians who joined later."""

from bioverse.db.seeds.ids import U_FRONTDESK
from bioverse.db.seeds.s120_consultations import U_BENALI
from bioverse.db.seeds.s160_pharmacy_orders import U_PHARMACIST
from tests.conftest import MAYA, as_user


def test_me_reports_staff_team(client):
    assert client.get("/api/me", headers=as_user(U_FRONTDESK)).json()["team"] == "front_desk"
    assert client.get("/api/me", headers=as_user(U_PHARMACIST)).json()["team"] == "pharmacy"
    assert client.get("/api/me", headers=MAYA).json()["team"] is None
    users = {u["id"]: u for u in client.get("/api/session/demo-users").json()}
    assert users[U_PHARMACIST]["team"] == "pharmacy"


def test_new_clinician_gets_a_default_agent_config(client):
    benali = as_user(U_BENALI)
    r = client.get("/api/clinician/agent-config", headers=benali)
    assert r.status_code == 200, r.text
    rules = {x["id"]: x for x in r.json()["escalation_rules"]}
    assert rules["red_flag"]["locked"] and rules["red_flag"]["action"] == "emergency_guidance"
    # Saving it back works like for any other clinician.
    body = {k: r.json()[k] for k in ("active", "previsit_questions", "followup_protocol",
                                     "escalation_rules", "approval_requirements")}
    assert client.put("/api/clinician/agent-config", headers=benali, json=body).status_code == 200
