"""Single sign-on against a fake OpenID provider that signs real RS256 ID tokens."""

import time
import urllib.parse

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg.rows import dict_row

from bioverse.sso import providers
from tests.conftest import ADMIN, DB, MAYA
from bioverse.db.seed import U_ADMIN, U_MAYA

ENTRA_TENANT = "11111111-2222-3333-4444-555555555555"
ISSUERS = {
    "google": "https://accounts.google.com",
    "okta": "https://example.okta.com/oauth2/default",
    "entra": f"https://login.microsoftonline.com/{ENTRA_TENANT}/v2.0",
}
CLIENT_IDS = {"google": "google-client", "okta": "okta-client", "entra": "entra-client"}


def _key(kid):
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key(), as_dict=True) | {"kid": kid, "use": "sig", "alg": "RS256"}
    return k, jwk


class FakeIdP:
    def __init__(self):
        self.key, jwk = _key("k1")
        self.jwks = {"keys": [jwk]}
        self.claims = {}          # next ID token's claims, filled per test
        self.kid = "k1"
        self.token_requests = []

    def discovery(self, issuer_base):
        return {
            "issuer": issuer_base, "authorization_endpoint": f"{issuer_base}/authorize",
            "token_endpoint": f"{issuer_base}/token", "jwks_uri": f"{issuer_base}/keys",
            "end_session_endpoint": f"{issuer_base}/logout",
        }

    def get(self, url):
        if url.endswith("/.well-known/openid-configuration"):
            return self.discovery(url.removesuffix("/.well-known/openid-configuration"))
        if url.endswith("/keys"):
            return self.jwks
        raise AssertionError(url)

    def post(self, url, form):
        self.token_requests.append(form)
        token = jwt.encode(self.claims, self.key, algorithm="RS256", headers={"kid": self.kid})
        return {"id_token": token, "access_token": "at", "token_type": "Bearer"}


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdP()
    monkeypatch.setattr(providers, "http_get_json", fake.get)
    monkeypatch.setattr(providers, "http_post_form", fake.post)
    for k, v in {
        "BIOVERSE_PUBLIC_URL": "http://testserver",
        "BIOVERSE_GOOGLE_CLIENT_ID": CLIENT_IDS["google"], "BIOVERSE_GOOGLE_CLIENT_SECRET": "gs",
        "BIOVERSE_OKTA_ISSUER": ISSUERS["okta"], "BIOVERSE_OKTA_CLIENT_ID": CLIENT_IDS["okta"],
        "BIOVERSE_OKTA_CLIENT_SECRET": "os",
        "BIOVERSE_ENTRA_TENANT_ID": ENTRA_TENANT, "BIOVERSE_ENTRA_CLIENT_ID": CLIENT_IDS["entra"],
        "BIOVERSE_ENTRA_CLIENT_SECRET": "es",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BIOVERSE_AUTH_MODE", raising=False)
    providers.clear_caches()
    yield fake
    providers.clear_caches()


def maya_email():
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        return conn.execute("SELECT email FROM users WHERE id = %s", (U_MAYA,)).fetchone()["email"]


def sign_in(client, idp, provider="google", *, next_path="/vitals", tamper=None, **claims):
    r = client.get(f"/api/auth/login/{provider}", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query))
    now = int(time.time())
    idp.claims = {"iss": ISSUERS[provider], "aud": CLIENT_IDS[provider], "sub": "sub-1", "iat": now,
                  "exp": now + 600, "nonce": q["nonce"], "email": maya_email(), "email_verified": True,
                  "name": "Maya T"} | claims
    if tamper:
        tamper(idp.claims)
    return client.get(f"/api/auth/callback/{provider}", params={"code": "abc", "state": q["state"]},
                      follow_redirects=False), q


def error_of(r):
    assert r.status_code == 303
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query)).get("error")


def test_config_lists_providers_and_turns_demo_off(client, idp):
    cfg = client.get("/api/auth/config").json()
    assert cfg["mode"] == "sso" and not cfg["demo"]
    assert {p["key"] for p in cfg["providers"]} == {"entra", "okta", "google"}
    assert client.get("/api/session/demo-users").json() == []
    assert client.get("/api/me", headers=MAYA).status_code == 401      # the demo header no longer works


def test_authorization_request_uses_pkce_and_state_cookie(client, idp):
    r = client.get("/api/auth/login/okta", follow_redirects=False)
    url = urllib.parse.urlparse(r.headers["location"])
    q = dict(urllib.parse.parse_qsl(url.query))
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUERS['okta']}/authorize"
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256" and len(q["code_challenge"]) >= 43
    assert q["redirect_uri"] == "http://testserver/api/auth/callback/okta"
    assert set(q["scope"].split()) == {"openid", "email", "profile"}
    assert client.cookies.get("bv_oidc_state") == q["state"]


def test_google_sign_in_links_by_verified_email_and_starts_a_session(client, idp):
    r, q = sign_in(client, idp)
    assert r.status_code == 303 and r.headers["location"] == "/vitals"
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    me = client.get("/api/me").json()
    assert me["id"] == U_MAYA and me["auth"] == "sso"
    # PKCE verifier sent with the code, and the stored request is single use.
    assert idp.token_requests[-1]["code_verifier"] and idp.token_requests[-1]["grant_type"] == "authorization_code"
    replay = client.get("/api/auth/callback/google", params={"code": "abc", "state": q["state"]}, follow_redirects=False)
    assert error_of(replay) == "invalid_state"
    # Next time the linked identity is used even if the email changed at the provider.
    client.cookies.clear()
    r, _ = sign_in(client, idp, email="new-address@example.org")
    assert r.headers["location"] == "/vitals" and client.get("/api/me").json()["id"] == U_MAYA


@pytest.mark.parametrize("tamper,code", [
    (lambda c: c.update(nonce="wrong"), "invalid_token"),
    (lambda c: c.update(aud="someone-else"), "invalid_token"),
    (lambda c: c.update(exp=int(time.time()) - 3600), "invalid_token"),
    (lambda c: c.update(iss="https://evil.example"), "invalid_token"),
    (lambda c: c.update(email_verified=False), "email_unverified"),
    (lambda c: c.update(email="nobody@example.org"), "not_registered"),
])
def test_rejected_sign_ins(client, idp, tamper, code):
    r, _ = sign_in(client, idp, tamper=tamper)
    assert error_of(r) == code
    assert client.get("/api/me").status_code == 401


def test_token_signed_by_another_key_is_rejected(client, idp):
    idp.key, _ = _key("k1")          # same kid, different key: signature fails
    r, _ = sign_in(client, idp)
    assert error_of(r) == "invalid_token"


def test_key_rotation_refetches_jwks(client, idp):
    sign_in(client, idp)             # caches k1
    new_key, jwk = _key("k2")
    idp.jwks = {"keys": idp.jwks["keys"] + [jwk]}
    idp.key, idp.kid = new_key, "k2"
    client.cookies.clear()
    r, _ = sign_in(client, idp)
    assert r.headers["location"] == "/vitals"


def test_state_must_match_this_browser(client, idp):
    r = client.get("/api/auth/login/google", follow_redirects=False)
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query))["state"]
    client.cookies.set("bv_oidc_state", "something-else", path="/api/auth")
    bad = client.get("/api/auth/callback/google", params={"code": "c", "state": state}, follow_redirects=False)
    assert error_of(bad) == "invalid_state"


def test_next_path_stays_on_site(client, idp):
    r, _ = sign_in(client, idp, next_path="//evil.example/steal")
    assert r.headers["location"] == "/"


def test_entra_and_okta(client, idp):
    r, _ = sign_in(client, idp, "entra", email=None, preferred_username=maya_email(), tid=ENTRA_TENANT,
                   email_verified=None)
    assert r.headers["location"] == "/vitals" and client.get("/api/me").json()["id"] == U_MAYA
    client.cookies.clear()
    r, _ = sign_in(client, idp, "okta", sub="okta-9")
    assert client.get("/api/me").json()["id"] == U_MAYA


def test_entra_multi_tenant_needs_an_allowed_tenant(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_ENTRA_TENANT_ID", "organizations")
    monkeypatch.setenv("BIOVERSE_ENTRA_ALLOWED_TENANTS", ENTRA_TENANT)
    providers.clear_caches()
    other = "99999999-0000-0000-0000-000000000000"
    r, _ = sign_in(client, idp, "entra", tid=other, iss=f"https://login.microsoftonline.com/{other}/v2.0")
    assert error_of(r) == "tenant_not_allowed"
    r, _ = sign_in(client, idp, "entra", tid=ENTRA_TENANT, iss=ISSUERS["entra"])
    assert r.headers["location"] == "/vitals"


def test_bootstrap_admin(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_BOOTSTRAP_ADMINS", "Owner@Hospital.example")
    r, _ = sign_in(client, idp, email="owner@hospital.example", sub="owner")
    assert r.headers["location"] == "/vitals"
    assert client.get("/api/me").json()["role"] == "admin"


def test_cookie_requests_need_the_client_header_for_writes(client, idp):
    sign_in(client, idp)
    assert client.post("/api/notifications/read-all").status_code == 403
    assert client.post("/api/notifications/read-all", headers={"X-Bioverse-Client": "web"}).status_code == 200


def test_logout_revokes_and_returns_provider_sign_out(client, idp):
    sign_in(client, idp, "okta")
    r = client.post("/api/auth/logout", headers={"X-Bioverse-Client": "web"}).json()
    assert r["redirect"].startswith(f"{ISSUERS['okta']}/logout?") and "id_token_hint" in r["redirect"]
    assert client.get("/api/me").status_code == 401


def test_idle_timeout_and_disabled_accounts(client, idp):
    sign_in(client, idp)
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE auth_sessions SET last_seen_at = now() - interval '3 hours'")
    assert client.get("/api/me").status_code == 401
    client.cookies.clear()
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE users SET disabled = true WHERE id = %s", (U_MAYA,))
    r, _ = sign_in(client, idp)
    assert error_of(r) == "account_disabled"


def test_sso_plus_demo_mode_accepts_both(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    assert client.get("/api/me", headers=MAYA).json()["auth"] == "demo"
    assert client.get("/api/auth/config").json()["demo"] is True


def test_admin_manages_people_and_linked_accounts(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    sign_in(client, idp)                 # links a Google identity to Maya
    client.cookies.clear()
    listing = client.get("/api/admin/users", headers=ADMIN).json()
    maya = next(u for u in listing["users"] if u["id"] == U_MAYA)
    assert maya["identities"][0]["provider"] == "google" and maya["active_sessions"] == 1
    assert client.get("/api/admin/users", headers=MAYA).status_code == 403

    new = client.post("/api/admin/users", headers=ADMIN, json={
        "display_name": "Dr. New Person", "email": "New.Person@Hospital.example", "role": "clinician",
        "specialty": "Cardiology"})
    assert new.status_code == 201
    assert client.post("/api/admin/users", headers=ADMIN, json={
        "display_name": "Dup", "email": "new.person@hospital.example", "role": "staff"}).status_code == 409
    assert client.post("/api/admin/users", headers=ADMIN, json={
        "display_name": "No dob", "email": "p@hospital.example", "role": "patient"}).status_code == 422

    assert client.patch(f"/api/admin/users/{U_ADMIN}", headers=ADMIN, json={"disabled": True}).status_code == 409
    assert client.patch(f"/api/admin/users/{U_MAYA}", headers=ADMIN, json={"email": "maya@real.example"}).status_code == 200

    ident = maya["identities"][0]["id"]
    assert client.delete(f"/api/admin/users/{U_MAYA}/identities/{ident}", headers=ADMIN).status_code == 200
    assert next(u for u in client.get("/api/admin/users", headers=ADMIN).json()["users"]
                if u["id"] == U_MAYA)["active_sessions"] == 0
