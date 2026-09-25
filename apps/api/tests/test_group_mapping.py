"""Directory group -> role mapping: rules API, just-in-time accounts and keeping roles in sync on sign-in."""

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.db.seeds.ids import U_ADMIN, U_FRONTDESK, U_OKAFOR
from tests.conftest import ADMIN, DB, as_user
from tests.test_sso import ENTRA_TENANT, error_of, idp, sign_in  # noqa: F401  (idp is a fixture)

PHARMACY_GROUP = "6f1d2c3b-0a9e-4e5f-8a7b-1c2d3e4f5a6b"      # an Entra group object id


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def email_of(user_id):
    with db() as conn:
        return conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()["email"]


@pytest.fixture
def sso(idp, monkeypatch):
    """The fake identity provider, with the demo header still accepted for the admin's own calls."""
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    return idp


def add_rule(client, **body):
    client.cookies.clear()                   # admin calls use the demo header, not a signed-in cookie
    r = client.post("/api/admin/sign-in-rules", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def settings(client, **body):
    client.cookies.clear()
    r = client.put("/api/admin/sign-in-rules/settings", headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def me(client):
    return client.get("/api/me").json()


def test_jit_is_off_by_default(client, sso):
    add_rule(client, provider="entra", claim="groups", match_value=PHARMACY_GROUP, role="staff", team="pharmacy")
    r, _ = sign_in(client, sso, "entra", email="new.rx@hospital.example", tid=ENTRA_TENANT, sub="e-1",
                   groups=[PHARMACY_GROUP])
    assert error_of(r) == "not_registered"


def test_jit_creates_a_pharmacist_from_an_entra_group(client, sso):
    add_rule(client, provider="entra", claim="groups", match_value=PHARMACY_GROUP.upper(), role="staff",
             team="pharmacy")
    assert settings(client, jit_enabled=True) == {"jit_enabled": True, "sync_on_sign_in": False}
    r, _ = sign_in(client, sso, "entra", email="new.rx@hospital.example", tid=ENTRA_TENANT, sub="e-1",
                   name="Rene Rx", groups=["another-group", PHARMACY_GROUP])
    assert r.headers["location"] == "/vitals"
    who = me(client)
    assert who["role"] == "staff" and who["team"] == "pharmacy" and who["display_name"] == "Rene Rx"
    assert client.get("/api/pharmacy-orders/staff/queue", headers=as_user(who["id"])).status_code == 200
    with db() as conn:
        ev = conn.execute("SELECT detail FROM audit_events WHERE action = 'access.user_create' AND entity_id = %s",
                          (who["id"],)).fetchone()
        assert ev["detail"]["source"] == "sso_group" and ev["detail"]["provider"] == "entra"
        assert conn.execute("SELECT provider FROM user_identities WHERE user_id = %s", (who["id"],)).fetchone()


def test_jit_clinician_from_okta_group_gets_practitioner_rows_and_starts_unverified(client, sso):
    add_rule(client, provider="okta", claim="groups", match_value="Bioverse Cardiology", role="clinician",
             specialty="Cardiology")
    settings(client, jit_enabled=True)
    r, _ = sign_in(client, sso, "okta", email="heart.doc@hospital.example", sub="o-1", name="Dr. Heart",
                   groups=["Everyone", "bioverse cardiology"])
    assert r.headers["location"] == "/vitals"
    who = me(client)
    assert who["role"] == "clinician"
    with db() as conn:
        row = conn.execute(
            "SELECT p.specialty, cp.fee_cents FROM practitioners p JOIN consult_profiles cp ON cp.practitioner_id = p.id "
            "WHERE p.user_id = %s", (who["id"],)).fetchone()
    assert row == {"specialty": "Cardiology", "fee_cents": 0}


def test_google_hosted_domain_rule_and_provider_filter(client, sso):
    add_rule(client, provider="google", claim="hd", match_value="school.example", role="student")
    settings(client, jit_enabled=True)
    # The same domain through Okta doesn't match a Google-only rule.
    r, _ = sign_in(client, sso, "okta", email="learner@school.example", sub="o-2", hd="school.example")
    assert error_of(r) == "not_registered"
    r, _ = sign_in(client, sso, "google", email="learner@school.example", sub="g-2", hd="school.example")
    assert r.headers["location"] == "/vitals" and me(client)["role"] == "student"


def test_lowest_priority_number_wins(client, sso):
    add_rule(client, claim="groups", match_value="all-staff", role="staff", team="front_desk", priority=50)
    add_rule(client, claim="groups", match_value="it-admins", role="admin", priority=10)
    settings(client, jit_enabled=True)
    sign_in(client, sso, "okta", email="boss@hospital.example", sub="o-3", groups=["all-staff", "it-admins"])
    assert me(client)["role"] == "admin"


def test_sync_on_sign_in_changes_team_only_when_turned_on(client, sso):
    add_rule(client, provider="okta", claim="groups", match_value="Pharmacists", role="staff", team="pharmacy")
    desk = email_of(U_FRONTDESK)
    sign_in(client, sso, "okta", email=desk, sub="o-desk", groups=["Pharmacists"])
    assert me(client)["team"] == "front_desk"                  # sync is off
    settings(client, sync_on_sign_in=True)
    client.cookies.clear()
    sign_in(client, sso, "okta", email=desk, sub="o-desk", groups=["Pharmacists"])
    assert me(client)["team"] == "pharmacy"
    assert client.get("/api/pharmacy-orders/staff/queue", headers=as_user(U_FRONTDESK)).status_code == 200
    with db() as conn:
        ev = conn.execute("SELECT detail FROM audit_events WHERE action = 'access.group_sync'").fetchone()
    assert ev["detail"]["from_team"] == "front_desk" and ev["detail"]["to_team"] == "pharmacy"
    # Someone who matches no rule keeps what they have.
    client.cookies.clear()
    sign_in(client, sso, "okta", email=desk, sub="o-desk", groups=[])
    assert me(client)["team"] == "pharmacy"


def test_sync_never_demotes_the_last_admin_or_touches_clinicians(client, sso):
    add_rule(client, claim="groups", match_value="desk", role="staff", team="front_desk")
    add_rule(client, claim="groups", match_value="admins", role="admin", priority=200)
    settings(client, sync_on_sign_in=True)
    sign_in(client, sso, "okta", email=email_of(U_ADMIN), sub="o-admin", groups=["desk"])
    assert me(client)["role"] == "admin"
    with db() as conn:
        assert conn.execute("SELECT detail->>'blocked' AS b FROM audit_events WHERE action = 'access.group_sync'"
                            ).fetchone()["b"] == "last_admin"
    client.cookies.clear()
    sign_in(client, sso, "okta", email=email_of(U_OKAFOR), sub="o-okafor", groups=["admins"])
    assert me(client)["role"] == "clinician"
    # With a second administrator the first one can be moved to staff by the directory.
    client.cookies.clear()
    sign_in(client, sso, "okta", email=email_of(U_FRONTDESK), sub="o-desk", groups=["admins"])
    assert me(client)["role"] == "admin"
    client.cookies.clear()
    sign_in(client, sso, "okta", email=email_of(U_ADMIN), sub="o-admin", groups=["desk"])
    assert me(client)["role"] == "staff" and me(client)["team"] == "front_desk"


def test_rules_api_validates_and_is_admin_only(client):
    staff = as_user(U_FRONTDESK)
    assert client.get("/api/admin/sign-in-rules", headers=staff).status_code == 403
    assert client.post("/api/admin/sign-in-rules", headers=staff,
                       json={"match_value": "x", "role": "staff"}).status_code == 403
    assert client.post("/api/admin/sign-in-rules/test", headers=staff, json={"claims": {}}).status_code == 403
    bad = client.post("/api/admin/sign-in-rules", headers=ADMIN, json={"match_value": "docs", "role": "clinician"})
    assert bad.status_code == 422
    assert client.post("/api/admin/sign-in-rules", headers=ADMIN,
                       json={"match_value": "pts", "role": "patient"}).status_code == 422
    rule = add_rule(client, match_value="  Nurses ", role="student", team="pharmacy")
    assert rule["match_value"] == "Nurses" and rule["team"] is None and rule["claim"] == "groups"
    listing = client.get("/api/admin/sign-in-rules", headers=ADMIN).json()
    assert [r["id"] for r in listing["rules"]] == [rule["id"]]
    assert listing["settings"] == {"jit_enabled": False, "sync_on_sign_in": False}
    r = client.patch(f"/api/admin/sign-in-rules/{rule['id']}", headers=ADMIN, json={"role": "staff", "team": "pharmacy"})
    assert r.status_code == 200 and r.json()["team"] == "pharmacy"
    r = client.patch(f"/api/admin/sign-in-rules/{rule['id']}", headers=ADMIN, json={"role": "clinician"})
    assert r.status_code == 422 and "specialty" in r.json()["detail"]
    assert client.delete(f"/api/admin/sign-in-rules/{rule['id']}", headers=ADMIN).status_code == 200
    assert client.get("/api/admin/sign-in-rules", headers=ADMIN).json()["rules"] == []


def test_try_rules_with_sample_claims(client):
    add_rule(client, provider="entra", claim="groups", match_value=PHARMACY_GROUP, role="staff", team="pharmacy")
    claims = {"iss": f"https://login.microsoftonline.com/{ENTRA_TENANT}/v2.0", "preferred_username": "Someone@Hospital.example",
              "groups": [PHARMACY_GROUP]}
    out = client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"claims": claims}).json()
    assert out["provider"] == "entra" and out["email"] == "someone@hospital.example"
    assert out["outcome"] == "not_registered" and "off" in out["summary"]
    settings(client, jit_enabled=True)
    out = client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"claims": claims}).json()
    assert out["outcome"] == "create" and out["role"] == "staff" and out["team"] == "pharmacy"
    # An ID token pasted as is works too (only its payload is read).
    import jwt
    token = jwt.encode(claims, "signature-is-not-checked-by-the-tool", algorithm="HS256")
    assert client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"token": token}).json()["outcome"] == "create"
    # An existing staff member: shows the team change, applied only when sync is on.
    desk = {"iss": claims["iss"], "email": email_of(U_FRONTDESK), "groups": [PHARMACY_GROUP]}
    out = client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"claims": desk}).json()
    assert out["outcome"] == "sign_in" and out["change"]["to_team"] == "pharmacy" and "sync is off" in out["summary"]
    settings(client, sync_on_sign_in=True)
    out = client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"claims": desk}).json()
    assert out["outcome"] == "sync"
    # Entra's group overage: the groups are left out of the token.
    overage = {"email": "x@hospital.example", "_claim_names": {"groups": "src1"}}
    out = client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"claims": overage, "provider": "entra"}).json()
    assert any("too many groups" in w for w in out["warnings"])
    assert out["outcome"] == "not_registered"
    assert client.post("/api/admin/sign-in-rules/test", headers=ADMIN, json={"token": "nope"}).status_code == 422
