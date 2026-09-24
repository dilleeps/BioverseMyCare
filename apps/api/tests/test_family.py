"""Family and caregivers. Caregiver access is the core risk, so every denied path is tested."""

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.agents.triage import rules_triage
from bioverse.db.seed import ORG, U_MAYA
from bioverse.db.seeds.s060_wellness_family import P_DAVID, P_ELEANOR, U_DAVID, U_ELEANOR
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK, as_user

DAVID = as_user(U_DAVID)
ELEANOR = as_user(U_ELEANOR)


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def audit_rows(action: str, patient_id: str) -> list[dict]:
    with db() as conn:
        return conn.execute(
            "SELECT actor_user_id::text AS actor, patient_id::text AS patient, detail FROM audit_events "
            "WHERE action = %s AND patient_id = %s",
            (action, patient_id),
        ).fetchall()


# --- Seeded relationships --------------------------------------------------------------------------------


def test_seeded_family(client):
    maya = client.get("/api/family/me", headers=MAYA).json()
    [eleanor] = maya["caring_for"]
    assert eleanor["name"] == "Eleanor Thornton" and eleanor["proxy"] is True and eleanor["age"] >= 80
    [david] = maya["me"]["caregivers"]
    assert david["name"] == "David Thornton"
    assert david["permissions"] == ["view_appointments", "view_care_plan"]
    assert david["relationship"] == "spouse" and david["status"] == "active"

    david_view = client.get("/api/family/me", headers=DAVID).json()
    assert [p["name"] for p in david_view["caring_for"]] == ["Maya Thornton"]
    users = client.get("/api/session/demo-users").json()
    assert any(u["display_name"] == "David Thornton" and u["subtitle"] == "Caregiver" for u in users)


def test_permitted_reads_are_audited_with_the_dependent(client):
    appts = client.get(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=MAYA)
    assert appts.status_code == 200 and len(appts.json()) == 2
    plan = client.get(f"/api/family/dependents/{P_ELEANOR}/care-plan", headers=MAYA).json()
    assert plan["hidden_medication_tasks"] == 0
    assert sum(1 for t in plan["tasks"] if t["kind"] == "medication") == 2
    meds = client.get(f"/api/family/dependents/{P_ELEANOR}/medications", headers=MAYA).json()
    assert len(meds) == 2
    [row] = audit_rows("caregiver_viewed_appointments", P_ELEANOR)
    assert row["actor"] == U_MAYA


# --- Denied paths --------------------------------------------------------------------------------------------


def test_no_grant_is_denied(client):
    for path in ("", "/appointments", "/care-plan", "/results", "/medications", "/slots"):
        assert client.get(f"/api/family/dependents/{P_MAYA}{path}", headers=PARK).status_code == 403, path
        assert client.get(f"/api/family/dependents/{P_ELEANOR}{path}", headers=DAVID).status_code == 403, path
    assert client.post(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=DAVID, json={"slot_id": "x"}).status_code == 403


def test_missing_permission_is_denied(client):
    # David may see Maya's appointments and care plan, nothing else.
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID).status_code == 200
    plan = client.get(f"/api/family/dependents/{P_MAYA}/care-plan", headers=DAVID).json()
    assert plan["hidden_medication_tasks"] == 1, "medicine tasks need view_medications"
    assert all(t["kind"] != "medication" for t in plan["tasks"])
    assert client.get(f"/api/family/dependents/{P_MAYA}/results", headers=DAVID).status_code == 403
    assert client.get(f"/api/family/dependents/{P_MAYA}/medications", headers=DAVID).status_code == 403
    assert client.get(f"/api/family/dependents/{P_MAYA}/slots", headers=DAVID).status_code == 403
    assert client.post(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID, json={"slot_id": "x"}).status_code == 403


def test_revoked_grant_is_denied(client):
    r = client.delete(f"/api/family/patients/{P_MAYA}/caregivers/{U_DAVID}", headers=MAYA)
    assert r.status_code == 200
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID).status_code == 403
    assert client.get(f"/api/family/dependents/{P_MAYA}/care-plan", headers=DAVID).status_code == 403
    assert client.get("/api/family/me", headers=DAVID).json()["caring_for"] == []
    [david] = client.get("/api/family/me", headers=MAYA).json()["me"]["caregivers"]
    assert david["status"] == "revoked"
    revokes = audit_rows("consent_revoked", P_MAYA)
    assert revokes and revokes[0]["actor"] == U_MAYA


def test_expired_grant_is_denied(client):
    with db() as conn:
        conn.execute(
            "UPDATE consents SET expires_at = now() - interval '1 minute' WHERE patient_id = %s AND grantee = %s",
            (P_MAYA, U_DAVID),
        )
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID).status_code == 403
    [david] = client.get("/api/family/me", headers=MAYA).json()["me"]["caregivers"]
    assert david["status"] == "expired"


def test_grant_with_future_expiry_then_past_expiry_rejected(client):
    soon = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    ok = client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                    json={"user_id": U_DAVID, "relationship": "spouse", "permissions": ["view_appointments"], "expires_at": soon})
    assert ok.status_code == 200
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID).status_code == 200
    assert client.get(f"/api/family/dependents/{P_MAYA}/care-plan", headers=DAVID).status_code == 403, "permissions replaced"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    bad = client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                     json={"user_id": U_DAVID, "relationship": "spouse", "permissions": ["view_appointments"], "expires_at": past})
    assert bad.status_code == 422


def test_patient_cannot_use_caregiver_endpoints_on_self(client):
    assert client.get(f"/api/family/dependents/{P_MAYA}", headers=MAYA).status_code == 403
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=MAYA).status_code == 403


def test_unknown_or_other_org_patient_is_not_found(client):
    assert client.get("/api/family/dependents/not-a-uuid/appointments", headers=MAYA).status_code == 404
    assert client.get(f"/api/family/dependents/{ORG}/appointments", headers=MAYA).status_code == 404


# --- Results: only approved explanations -------------------------------------------------------------------


def test_caregiver_never_sees_unapproved_result_drafts(client):
    r = client.get(f"/api/family/dependents/{P_ELEANOR}/results", headers=MAYA)
    assert r.status_code == 200
    by_name = {x["name"]: x for x in r.json()}
    assert by_name["Kidney function"]["status"] == "reviewed"
    assert by_name["Kidney function"]["explanation"].startswith("Your kidney function")
    assert len(by_name["Kidney function"]["observations"]) == 2
    vit_d = by_name["Vitamin D"]
    assert vit_d["status"] == "awaiting_review"
    assert "explanation" not in vit_d and "observations" not in vit_d
    assert "DRAFT" not in r.text and "supplement" not in r.text


def test_granting_results_shows_only_approved(client):
    grant = client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                       json={"email": "david@example.com", "relationship": "spouse",
                             "permissions": ["view_appointments", "view_results"]})
    assert grant.status_code == 200
    results = client.get(f"/api/family/dependents/{P_MAYA}/results", headers=DAVID).json()
    assert len(results) == 3 and all(x["status"] == "reviewed" for x in results)
    grants = audit_rows("caregiver_access_granted", P_MAYA)
    assert grants[-1]["detail"]["permissions"] == ["view_appointments", "view_results"]
    assert grants[-1]["actor"] == U_MAYA


# --- Adolescent privacy ---------------------------------------------------------------------------------------

U_TEEN, P_TEEN = "00000000-0000-0000-0000-000000006901", "00000000-0000-0000-0000-000000006902"
TEEN = as_user(U_TEEN)


@pytest.fixture
def teen(client):
    """A 15-year-old whose parent David is full proxy (set up directly, as a registration desk would)."""
    birth = date.today().replace(year=date.today().year - 15) - timedelta(days=10)
    with db() as conn:
        conn.execute("INSERT INTO users (id, role, display_name, email, organization_id) VALUES (%s, 'patient', 'Sam Thornton', 'sam@example.com', %s)",
                     (U_TEEN, ORG))
        conn.execute("INSERT INTO patients (id, user_id, organization_id, name, birth_date) VALUES (%s, %s, %s, 'Sam Thornton', %s)",
                     (P_TEEN, U_TEEN, ORG, birth))
        report = conn.execute("INSERT INTO diagnostic_reports (patient_id, name, lab_name, collected_at) VALUES (%s, 'Blood count', 'Northside Lab', now()) RETURNING id",
                              (P_TEEN,)).fetchone()["id"]
        conn.execute("INSERT INTO result_explanations (report_id, draft_text, final_text, status, produced_by) VALUES (%s, 'ok', 'All normal.', 'approved', 'test')",
                     (report,))
        conn.execute("INSERT INTO related_persons (patient_id, user_id, relationship) VALUES (%s, %s, 'parent')", (P_TEEN, U_DAVID))
        consent.set_status(conn, patient_id=P_TEEN, scope="caregiver_access", status="granted", actor=None, grantee=U_DAVID,
                           detail={"permissions": [], "proxy": True, "relationship": "parent"})
    return client


def test_adolescent_results_need_the_teens_own_grant(teen):
    client = teen
    assert client.get(f"/api/family/dependents/{P_TEEN}/appointments", headers=DAVID).status_code == 200
    assert client.get(f"/api/family/dependents/{P_TEEN}/results", headers=DAVID).status_code == 403
    summary = client.get(f"/api/family/dependents/{P_TEEN}", headers=DAVID).json()
    assert "view_results" not in summary["permissions"] and summary["results_need_own_consent"] is True

    # The teen shares results with their parent. Only the teen can make this choice.
    assert client.put(f"/api/family/patients/{P_TEEN}/results-sharing/{U_DAVID}", headers=DAVID, json={"share": True}).status_code == 403
    assert client.put(f"/api/family/patients/{P_TEEN}/results-sharing/{U_DAVID}", headers=TEEN, json={"share": True}).status_code == 200
    assert client.get(f"/api/family/dependents/{P_TEEN}/results", headers=DAVID).status_code == 200
    assert client.put(f"/api/family/patients/{P_TEEN}/results-sharing/{U_DAVID}", headers=TEEN, json={"share": False}).status_code == 200
    assert client.get(f"/api/family/dependents/{P_TEEN}/results", headers=DAVID).status_code == 403

    # A parent-proxy granting view_results to someone else is not enough either.
    r = client.put(f"/api/family/patients/{P_TEEN}/caregivers", headers=DAVID,
                   json={"user_id": U_MAYA, "relationship": "other", "permissions": ["view_results", "view_appointments"]})
    assert r.status_code == 200
    assert client.get(f"/api/family/dependents/{P_TEEN}/results", headers=MAYA).status_code == 403
    assert client.get(f"/api/family/dependents/{P_TEEN}/appointments", headers=MAYA).status_code == 200

    # When the teen grants results themselves, that grant counts as their own consent.
    r = client.put(f"/api/family/patients/{P_TEEN}/caregivers", headers=TEEN,
                   json={"user_id": U_MAYA, "relationship": "other", "permissions": ["view_results"]})
    assert r.status_code == 200
    assert client.get(f"/api/family/dependents/{P_TEEN}/results", headers=MAYA).status_code == 200
    # Adults have no separate results choice.
    assert client.put(f"/api/family/patients/{P_MAYA}/results-sharing/{U_DAVID}", headers=MAYA, json={"share": True}).status_code == 409


# --- Who may grant --------------------------------------------------------------------------------------------


def test_grant_validation_and_authority(client):
    body = {"user_id": U_DAVID, "relationship": "spouse", "permissions": ["view_results"]}
    # A non-proxy caregiver can't change access; neither can an unrelated patient.
    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=DAVID, json=body).status_code == 403
    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=PARK, json=body).status_code == 403
    assert client.delete(f"/api/family/patients/{P_MAYA}/caregivers/{U_DAVID}", headers=PARK).status_code == 403
    assert client.get(f"/api/family/patients/{P_MAYA}/caregivers", headers=DAVID).status_code == 403

    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                      json={**body, "user_id": None, "email": "nobody@example.com"}).status_code == 404
    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                      json={**body, "user_id": U_MAYA}).status_code == 422
    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                      json={**body, "permissions": []}).status_code == 422
    assert client.put(f"/api/family/patients/{P_MAYA}/caregivers", headers=MAYA,
                      json={**body, "permissions": ["delete_everything"]}).status_code == 422


def test_proxy_limits_for_an_adult_dependent(client):
    # Maya is Eleanor's full proxy: she can let David see Eleanor's appointments...
    r = client.put(f"/api/family/patients/{P_ELEANOR}/caregivers", headers=MAYA,
                   json={"user_id": U_DAVID, "relationship": "other", "permissions": ["view_appointments"]})
    assert r.status_code == 200
    assert client.get(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=DAVID).status_code == 200
    [row] = [g for g in audit_rows("caregiver_access_granted", P_ELEANOR)]
    assert row["actor"] == U_MAYA and row["detail"]["granted_by"] == "proxy"
    # ...but only Eleanor can create another full proxy, and Maya can't edit her own grant.
    assert client.put(f"/api/family/patients/{P_ELEANOR}/caregivers", headers=MAYA,
                      json={"user_id": U_DAVID, "relationship": "other", "proxy": True}).status_code == 403
    assert client.put(f"/api/family/patients/{P_ELEANOR}/caregivers", headers=MAYA,
                      json={"user_id": U_MAYA, "relationship": "child", "permissions": ["view_results"]}).status_code == 403
    # Eleanor can revoke Maya; Maya's proxy powers end with it.
    assert client.delete(f"/api/family/patients/{P_ELEANOR}/caregivers/{U_MAYA}", headers=ELEANOR).status_code == 200
    assert client.get(f"/api/family/dependents/{P_ELEANOR}/results", headers=MAYA).status_code == 403
    assert client.put(f"/api/family/patients/{P_ELEANOR}/caregivers", headers=MAYA,
                      json={"user_id": U_DAVID, "relationship": "other", "permissions": ["view_results"]}).status_code == 403


def test_caregiver_can_step_back(client):
    assert client.delete(f"/api/family/patients/{P_MAYA}/caregivers/{U_DAVID}", headers=DAVID).status_code == 200
    assert client.get(f"/api/family/dependents/{P_MAYA}/appointments", headers=DAVID).status_code == 403


# --- Booking on behalf ------------------------------------------------------------------------------------------


def test_book_on_behalf_of_dependent(client):
    slots = client.get(f"/api/family/dependents/{P_ELEANOR}/slots?specialty=Primary care", headers=MAYA).json()
    assert slots
    r = client.post(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=MAYA,
                    json={"slot_id": slots[0]["id"], "reason": "Blood pressure check"})
    assert r.status_code == 201
    assert r.json()["specialty"] == "Primary care"
    again = client.post(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=MAYA, json={"slot_id": slots[0]["id"]})
    assert again.status_code == 409
    with db() as conn:
        appt = conn.execute("SELECT patient_id::text FROM appointments WHERE id = %s", (r.json()["id"],)).fetchone()
        assert appt["patient_id"] == P_ELEANOR
        event = conn.execute("SELECT actor_user_id::text AS actor, patient_id::text AS patient FROM audit_events "
                             "WHERE action = 'appointment_booked' AND entity_id = %s", (r.json()["id"],)).fetchone()
    assert event == {"actor": U_MAYA, "patient": P_ELEANOR}
    assert len(client.get(f"/api/family/dependents/{P_ELEANOR}/appointments", headers=MAYA).json()) == 3
    # Maya's own appointments are untouched.
    assert client.get(f"/api/patients/{P_MAYA}/appointments", headers=MAYA).json() == []


# --- Emergency contacts ----------------------------------------------------------------------------------------


def test_emergency_contacts(client):
    r = client.post(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=MAYA,
                    json={"name": "Ana Ruiz", "relationship": "Sister", "phone": "+1 555 0100"})
    assert r.status_code == 201
    contacts = client.get(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=MAYA).json()
    assert [c["name"] for c in contacts] == ["David Thornton", "Ana Ruiz"]
    assert client.get(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=PARK).status_code == 403
    assert client.get(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=DAVID).status_code == 403
    assert client.post(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=DAVID,
                       json={"name": "X Y", "relationship": "Friend", "phone": "5550100"}).status_code == 403
    assert client.post(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=OKAFOR,
                       json={"name": "X Y", "relationship": "Friend", "phone": "5550100"}).status_code == 403
    assert client.post(f"/api/family/patients/{P_MAYA}/emergency-contacts", headers=MAYA,
                       json={"name": "X Y", "relationship": "Friend", "phone": "call me"}).status_code == 422
    # Proxy manages the dependent's contacts.
    assert client.post(f"/api/family/patients/{P_ELEANOR}/emergency-contacts", headers=MAYA,
                       json={"name": "David Thornton", "relationship": "Son-in-law", "phone": "555-0142"}).status_code == 201
    removed = client.delete(f"/api/family/patients/{P_MAYA}/emergency-contacts/{r.json()['id']}", headers=MAYA)
    assert removed.status_code == 200
    assert client.delete(f"/api/family/patients/{P_PARK}/emergency-contacts/{r.json()['id']}", headers=MAYA).status_code == 403


def test_david_is_a_normal_patient(client):
    assert client.get(f"/api/patients/{P_DAVID}/care-plan", headers=DAVID).status_code == 200
    assert client.get(f"/api/patients/{P_MAYA}/care-plan", headers=DAVID).status_code == 403, \
        "caregiver access goes through /api/family only"


# --- Front door -----------------------------------------------------------------------------------------------

PATIENT = {"age": 54, "allergies": []}


@pytest.mark.parametrize("text", [
    "I need to book something for my mother", "Can I manage my daughter's appointments?",
    "add a caregiver", "on behalf of my father",
])
def test_family_intent(text):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent == "family"


@pytest.mark.parametrize("text", ["my son has a rash on his arm", "my mother fell and hurt her hip"])
def test_family_intent_does_not_steal_symptoms(text):
    assert rules_triage([{"role": "user", "content": text}], PATIENT).intent != "family"
