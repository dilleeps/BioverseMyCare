"""Patient invites, the date-of-birth check, email one-time codes and open self-registration."""

import hashlib
import re
import time
import urllib.parse

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.db.seed import ORG, U_ADMIN, U_FRONTDESK, U_MAYA, U_OKAFOR, U_PARK
from bioverse.sso.plugins import invites as invite_core
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, as_user
from tests.test_sso import CLIENT_IDS, ISSUERS, idp  # noqa: F401  (idp is a fixture)

WEB = {"X-Bioverse-Client": "web"}
DESK = as_user(U_FRONTDESK)
DOB = "1988-04-12"


@pytest.fixture(autouse=True)
def sso_plus_demo(monkeypatch):
    """Demo headers for staff, plus the session cookie that email sign-in starts."""
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    monkeypatch.setenv("BIOVERSE_PUBLIC_URL", "http://testserver")      # plain-http cookies for the test client
    for k in ("BIOVERSE_EMAIL_SIGNIN", "BIOVERSE_SELF_REGISTRATION", "BIOVERSE_SMTP_URL"):
        monkeypatch.delenv(k, raising=False)


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def email_of(user_id):
    with db() as conn:
        return conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()["email"]


def invite(client, headers=ADMIN, **over):
    body = {"email": "sam.rivera@example.org", "name": "Sam Rivera", "birth_date": DOB, "mrn": "MRN-00417",
            "message": "Looking forward to seeing you on Tuesday."} | over
    r = client.post("/api/invites", headers=headers, json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    return data, data["link"].rsplit("/join/", 1)[1]


def confirm(client, token, dob=DOB, **kw):
    return client.post(f"/api/join/{token}/confirm", headers=WEB, json={"birth_date": dob, "accept_terms": True} | kw)


def outbox(client, email):
    return client.get("/api/auth/dev-outbox", params={"email": email}).json()["messages"]


def latest_code(client, email):
    msgs = outbox(client, email)
    assert msgs, f"nothing sent to {email}"
    return re.search(r"\b(\d{6})\b", msgs[0]["subject"]).group(1)


def start(client, email, **kw):
    return client.post("/api/auth/email/start", headers=WEB, json={"email": email} | kw)


def verify(client, email, code, **kw):
    return client.post("/api/auth/email/verify", headers=WEB, json={"email": email, "code": code} | kw)


def invite_row(invite_id):
    with db() as conn:
        return conn.execute("SELECT * FROM patient_invites WHERE id = %s", (invite_id,)).fetchone()


# --- Staff side ------------------------------------------------------------------------------------------------


def test_admin_front_desk_and_clinicians_invite_but_patients_and_pharmacy_cannot(client):
    for i, who in enumerate((ADMIN, DESK, OKAFOR)):
        data, token = invite(client, who, email=f"p{i}@example.org")
        assert data["link"] == f"http://testserver/join/{token}" and data["status"] == "pending"
    assert client.post("/api/invites", headers=MAYA, json={
        "email": "x@example.org", "name": "X Person", "birth_date": DOB}).status_code == 403
    with db() as conn:
        pharmacist = conn.execute("SELECT id::text FROM users WHERE team = 'pharmacy' LIMIT 1").fetchone()["id"]
    assert client.post("/api/invites", headers=as_user(pharmacist), json={
        "email": "x@example.org", "name": "X Person", "birth_date": DOB}).status_code == 403
    assert client.get("/api/invites", headers=MAYA).status_code == 403
    listing = client.get("/api/invites", headers=DESK).json()["invites"]
    assert len(listing) == 3 and all("link" not in i for i in listing)     # links are shown once, at send time


def test_token_is_hashed_at_rest_and_the_link_is_emailed(client):
    data, token = invite(client)
    with db() as conn:
        row = conn.execute("SELECT * FROM patient_invites WHERE id = %s", (data["id"],)).fetchone()
        dump = str(conn.execute("SELECT row_to_json(i)::text AS j FROM patient_invites i").fetchall())
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in dump
    assert row["expires_at"].timestamp() - time.time() > 13.9 * 86400
    # No mail server in tests: the email channel skips, and the demo outbox keeps a copy with the link.
    assert data["delivery"]["status"] == "skipped"
    msg = outbox(client, "sam.rivera@example.org")[0]
    assert msg["link"].endswith(f"/join/{token}") and "Northside" in msg["subject"]


def test_duplicate_invites_and_existing_accounts_are_refused(client):
    invite(client)
    assert client.post("/api/invites", headers=ADMIN, json={
        "email": "Sam.Rivera@example.org", "name": "Sam Rivera", "birth_date": DOB}).status_code == 409
    assert client.post("/api/invites", headers=ADMIN, json={
        "email": email_of(U_MAYA), "name": "Maya", "birth_date": DOB}).status_code == 409
    assert client.post("/api/invites", headers=ADMIN, json={
        "email": "not-an-email", "name": "Nobody", "birth_date": DOB}).status_code == 422


def test_resend_rotates_the_link_and_revoke_stops_it(client):
    data, old = invite(client)
    r = client.post(f"/api/invites/{data['id']}/resend", headers=DESK)
    assert r.status_code == 200
    new = r.json()["link"].rsplit("/join/", 1)[1]
    assert new != old and r.json()["send_count"] == 2
    assert client.get(f"/api/join/{old}").status_code == 404
    assert client.get(f"/api/join/{new}").json()["status"] == "pending"
    assert client.post(f"/api/invites/{data['id']}/revoke", headers=OKAFOR).json()["status"] == "revoked"
    assert client.get(f"/api/join/{new}").json() == {"status": "revoked", "clinic": "Northside Health"}
    assert confirm(client, new).status_code == 410
    assert client.post(f"/api/invites/{data['id']}/resend", headers=ADMIN).status_code == 409
    # Another organization's staff can't see or touch it.
    with db() as conn:
        other = conn.execute("INSERT INTO organizations (name) VALUES ('Elsewhere') RETURNING id::text").fetchone()["id"]
        stranger = conn.execute(
            "INSERT INTO users (role, display_name, email, organization_id) VALUES ('admin', 'Other', 'o@else.example', %s)"
            " RETURNING id::text", (other,)).fetchone()["id"]
    assert client.post(f"/api/invites/{data['id']}/revoke", headers=as_user(stranger)).status_code == 404
    assert client.get("/api/invites", headers=as_user(stranger)).json()["invites"] == []


# --- Join page: date-of-birth check ------------------------------------------------------------------------------


def test_join_page_is_public_and_reveals_little(client):
    _, token = invite(client, OKAFOR)
    info = client.get(f"/api/join/{token}").json()
    assert info["status"] == "pending" and info["clinic"] == "Northside Health"
    assert info["first_name"] == "Sam" and "Okafor" in info["invited_by"]
    assert info["email_hint"].startswith("s") and "sam.rivera" not in info["email_hint"]
    assert "birth_date" not in info and "mrn" not in str(info).lower()
    assert info["dob_confirmed"] is False and info["sign_in"]["email"] is True
    assert client.get("/api/join/not-a-real-token").status_code == 404


def test_date_of_birth_check_locks_after_five_wrong_tries(client):
    data, token = invite(client)
    assert client.post(f"/api/join/{token}/confirm", json={"birth_date": DOB, "accept_terms": True}).status_code == 403
    assert confirm(client, token, accept_terms=False).status_code == 422
    for left in (4, 3, 2, 1):
        r = confirm(client, token, "1988-12-04")
        assert r.status_code == 400 and r.json()["detail"]["attempts_left"] == left
    assert confirm(client, token, "1990-01-01").status_code == 423
    assert confirm(client, token).status_code == 423                 # even the right date, once locked
    assert client.get(f"/api/join/{token}").json()["status"] == "locked"
    listed = next(i for i in client.get("/api/invites", headers=ADMIN).json()["invites"] if i["id"] == data["id"])
    assert listed["locked"] is True
    # Resending unlocks with a new link.
    new = client.post(f"/api/invites/{data['id']}/resend", headers=ADMIN).json()["link"].rsplit("/", 1)[1]
    assert confirm(client, new).status_code == 200
    assert client.get(f"/api/join/{new}").json()["dob_confirmed"] is True


def test_expired_invites_are_rejected(client):
    data, token = invite(client)
    with db() as conn:
        conn.execute("UPDATE patient_invites SET expires_at = now() - interval '1 minute' WHERE id = %s", (data["id"],))
    assert client.get(f"/api/join/{token}").json()["status"] == "expired"
    assert confirm(client, token).status_code == 410
    assert next(i for i in client.get("/api/invites", headers=ADMIN).json()["invites"])["status"] == "expired"
    # Resend brings an expired invite back.
    r = client.post(f"/api/invites/{data['id']}/resend", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "pending"


# --- Accepting with Google -----------------------------------------------------------------------------------------


def google_sign_in(client, idp, token, email, sub="g-sam"):
    r = client.get("/api/auth/login/google", params={"invite": token, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query))
    now = int(time.time())
    idp.claims = {"iss": ISSUERS["google"], "aud": CLIENT_IDS["google"], "sub": sub, "iat": now, "exp": now + 600,
                  "nonce": q["nonce"], "email": email, "email_verified": True, "name": "Sam R"}
    return client.get("/api/auth/callback/google", params={"code": "abc", "state": q["state"]}, follow_redirects=False)


def error_of(r):
    assert r.status_code == 303
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query)).get("error")


def test_accept_with_google_creates_the_patient(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    calls = []
    real = invite_core.register_patient
    monkeypatch.setattr(invite_core, "register_patient", lambda conn, **kw: calls.append(kw) or real(conn, **kw))
    data, token = invite(client)

    # Before the date-of-birth check the invite can't be used.
    assert error_of(google_sign_in(client, idp, token, "sam.personal@gmail.com")) == "invite_unconfirmed"
    assert confirm(client, token).status_code == 200
    r = google_sign_in(client, idp, token, "sam.personal@gmail.com")
    assert r.status_code == 303 and r.headers["location"] == "/", r.headers["location"]
    me = client.get("/api/me").json()
    assert me["role"] == "patient" and me["patient_id"] and me["display_name"] == "Sam Rivera" and me["auth"] == "sso"

    row = invite_row(data["id"])
    assert row["status"] == "accepted" and row["accepted_via"] == "google"
    assert row["email"] == "sam.rivera@example.org" and row["accepted_email"] == "sam.personal@gmail.com"
    assert str(row["accepted_patient_id"]) == me["patient_id"]
    assert calls[0]["source"] == "invite" and calls[0]["email"] == "sam.personal@gmail.com"
    assert calls[0]["identifiers"] == [{"system": f"urn:bioverse:org:{ORG}:mrn", "value": "MRN-00417"}]
    assert str(calls[0]["birth_date"]) == DOB and calls[0]["organization_id"] == ORG
    with db() as conn:
        audit = conn.execute("SELECT detail FROM audit_events WHERE action = 'invite.accept'").fetchone()["detail"]
    assert audit["signed_in_email"] == "sam.personal@gmail.com" and audit["invited_email"] == "sam.rivera@example.org"

    # The same link can't create a second account.
    client.cookies.clear()
    assert error_of(google_sign_in(client, idp, token, "someone.else@gmail.com", sub="g-2")) == "invite_invalid"
    # Signing in again later works without the invite (linked identity).
    r = google_sign_in(client, idp, "", "sam.personal@gmail.com")
    assert r.headers["location"] == "/"


def test_date_of_birth_confirmation_is_short_lived(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    data, token = invite(client)
    confirm(client, token)
    with db() as conn:
        conn.execute("UPDATE patient_invites SET dob_confirmed_at = now() - interval '31 minutes' WHERE id = %s",
                     (data["id"],))
    assert error_of(google_sign_in(client, idp, token, "sam.personal@gmail.com")) == "invite_unconfirmed"


def test_revoked_after_confirming_is_rejected(client, idp, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso+demo")
    data, token = invite(client)
    confirm(client, token)
    client.post(f"/api/invites/{data['id']}/revoke", headers=ADMIN)
    assert error_of(google_sign_in(client, idp, token, "sam.personal@gmail.com")) == "invite_invalid"


# --- Accepting with an email code ------------------------------------------------------------------------------


def test_accept_with_an_email_code(client):
    data, token = invite(client)
    assert confirm(client, token).status_code == 200
    r = start(client, "sam.home@example.net", invite=token)
    assert r.status_code == 200 and r.json()["sent"] is True
    code = latest_code(client, "sam.home@example.net")
    r = verify(client, "sam.home@example.net", code, invite=token, next="/app")
    assert r.status_code == 200 and r.json()["next"] == "/app"
    assert "httponly" in r.headers["set-cookie"].lower()
    me = client.get("/api/me").json()
    assert me["role"] == "patient" and me["display_name"] == "Sam Rivera" and me["auth"] == "sso"
    row = invite_row(data["id"])
    assert row["status"] == "accepted" and row["accepted_via"] == "email"
    assert row["accepted_email"] == "sam.home@example.net"
    # Codes are single use.
    client.cookies.clear()
    assert verify(client, "sam.home@example.net", code).status_code == 400
    # Next time, an ordinary code signs the new patient in.
    start(client, "sam.home@example.net")
    assert verify(client, "sam.home@example.net", latest_code(client, "sam.home@example.net")).status_code == 200


@pytest.mark.parametrize("spoil", ["unconfirmed", "revoked", "used", "expired"])
def test_email_code_with_an_unusable_invite_is_never_sent(client, spoil):
    data, token = invite(client)
    if spoil != "unconfirmed":
        confirm(client, token)
    with db() as conn:
        conn.execute({
            "unconfirmed": "SELECT %s",
            "revoked": "UPDATE patient_invites SET status = 'revoked' WHERE id = %s",
            "used": "UPDATE patient_invites SET status = 'accepted' WHERE id = %s",
            "expired": "UPDATE patient_invites SET expires_at = now() - interval '1 second' WHERE id = %s",
        }[spoil], (data["id"],))
    r = start(client, "new.person@example.net", invite=token)
    assert r.status_code == 200 and r.json()["sent"] is True          # same answer as always
    assert outbox(client, "new.person@example.net") == []
    assert verify(client, "new.person@example.net", "000000", invite=token).status_code == 400


def test_invite_revoked_between_code_and_verify(client):
    data, token = invite(client)
    confirm(client, token)
    start(client, "sam.home@example.net", invite=token)
    code = latest_code(client, "sam.home@example.net")
    client.post(f"/api/invites/{data['id']}/revoke", headers=ADMIN)
    assert verify(client, "sam.home@example.net", code, invite=token).status_code == 410
    assert client.get("/api/me").status_code == 401


# --- Email codes: existing patients, limits and enumeration -------------------------------------------------------


def test_existing_patient_signs_in_with_a_code_and_signs_out(client):
    maya = email_of(U_MAYA)
    start(client, maya.upper())
    r = verify(client, maya, latest_code(client, maya))
    assert r.status_code == 200 and r.json()["next"] == "/"
    me = client.get("/api/me").json()
    assert me["id"] == U_MAYA and me["auth"] == "sso"
    with db() as conn:
        s = conn.execute("SELECT provider, id_token_hint FROM auth_sessions WHERE user_id = %s", (U_MAYA,)).fetchone()
    assert s == {"provider": "email", "id_token_hint": None}
    out = client.post("/api/auth/logout", headers=WEB)
    assert out.status_code == 200 and out.json()["redirect"] == "/signin"
    assert client.get("/api/me").status_code == 401


def test_no_account_enumeration(client):
    maya, okafor = email_of(U_MAYA), email_of(U_OKAFOR)
    answers = [start(client, e).json() for e in (maya, "nobody@example.org", okafor, email_of(U_ADMIN))]
    assert all(a == answers[0] for a in answers)
    # Only the patient got a code: staff and clinicians use single sign-on.
    assert outbox(client, maya) and not outbox(client, "nobody@example.org") and not outbox(client, okafor)
    wrong = [verify(client, e, "123456") for e in (maya, "nobody@example.org", okafor, "never-asked@example.org")]
    assert {r.status_code for r in wrong} == {400}
    assert len({r.json()["detail"] for r in wrong}) == 1


def test_code_attempt_limit(client):
    park = email_of(U_PARK)
    start(client, park)
    code = latest_code(client, park)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert verify(client, park, wrong).status_code == 400
    assert verify(client, park, wrong).status_code == 429
    assert verify(client, park, code).status_code == 429               # the right code is dead too
    assert client.get("/api/me").status_code == 401


def test_expired_code_is_rejected(client):
    park = email_of(U_PARK)
    start(client, park)
    code = latest_code(client, park)
    with db() as conn:
        conn.execute("UPDATE email_signin_codes SET expires_at = now() - interval '1 second'")
    assert verify(client, park, code).status_code == 400


def test_codes_are_rate_limited_per_email(client):
    maya = email_of(U_MAYA)
    for _ in range(5):
        assert start(client, maya).status_code == 200
    assert start(client, maya).status_code == 429
    assert start(client, "nobody@example.org").status_code == 200    # per address
    # Only the newest code works.
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM email_signin_codes WHERE email = %s AND used_at IS NULL",
                            (maya,)).fetchone()["n"] == 1


def test_codes_are_stored_hashed(client):
    maya = email_of(U_MAYA)
    start(client, maya)
    code = latest_code(client, maya)
    with db() as conn:
        dump = str(conn.execute("SELECT row_to_json(c)::text AS j FROM email_signin_codes c").fetchall())
    assert code not in dump


def test_public_writes_need_the_web_client_header(client):
    assert client.post("/api/auth/email/start", json={"email": email_of(U_MAYA)}).status_code == 403
    assert client.post("/api/auth/email/verify", json={"email": email_of(U_MAYA), "code": "1"}).status_code == 403


def test_disabled_patient_cannot_use_a_code(client):
    maya = email_of(U_MAYA)
    start(client, maya)
    code = latest_code(client, maya)
    with db() as conn:
        conn.execute("UPDATE users SET disabled = true WHERE id = %s", (U_MAYA,))
    assert verify(client, maya, code).status_code == 400


# --- Configuration -------------------------------------------------------------------------------------------------


def test_email_sign_in_follows_sso_and_its_flag(client, monkeypatch):
    assert client.get("/api/auth/config").json()["email"] is True             # sso+demo
    monkeypatch.setenv("BIOVERSE_EMAIL_SIGNIN", "off")
    assert client.get("/api/auth/config").json()["email"] is False
    assert start(client, email_of(U_MAYA)).status_code == 404
    monkeypatch.delenv("BIOVERSE_EMAIL_SIGNIN")
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "demo")
    assert client.get("/api/auth/config").json()["email"] is False
    assert start(client, email_of(U_MAYA)).status_code == 404
    monkeypatch.setenv("BIOVERSE_EMAIL_SIGNIN", "on")
    assert client.get("/api/auth/config").json()["email"] is True


def test_production_mode_never_exposes_codes(client, monkeypatch):
    monkeypatch.setenv("BIOVERSE_AUTH_MODE", "sso")
    maya = email_of(U_MAYA)
    r = start(client, maya)
    assert r.status_code == 200 and r.json()["dev_outbox"] is False
    assert not re.search(r"\d{6}", r.text)
    assert client.get("/api/auth/dev-outbox", params={"email": maya}).status_code == 404
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM dev_outbox").fetchone()["n"] == 0


def test_self_registration_is_off_by_default(client):
    assert client.get("/api/auth/register").status_code == 404
    assert client.post("/api/auth/register", headers=WEB, json={
        "name": "Walk In", "birth_date": DOB, "email": "walk.in@example.net", "accept_terms": True}).status_code == 404


def test_self_registration_when_on(client, monkeypatch):
    monkeypatch.setenv("BIOVERSE_SELF_REGISTRATION", "on")
    assert client.get("/api/auth/register").json() == {"enabled": True}
    body = {"name": "Walk In", "birth_date": DOB, "email": "walk.in@example.net", "accept_terms": True}
    r = client.post("/api/auth/register", headers=WEB, json=body)
    assert r.status_code == 200 and r.json()["sent"] is True
    r = verify(client, "walk.in@example.net", latest_code(client, "walk.in@example.net"))
    assert r.status_code == 200
    me = client.get("/api/me").json()
    assert me["role"] == "patient" and me["display_name"] == "Walk In" and me["patient_id"]
    with db() as conn:
        p = conn.execute("SELECT birth_date::text, organization_id::text FROM patients WHERE id = %s",
                         (me["patient_id"],)).fetchone()
    assert p == {"birth_date": DOB, "organization_id": ORG}
    # Registering an address that already has an account creates nothing new.
    client.cookies.clear()
    r = client.post("/api/auth/register", headers=WEB, json=body | {"email": email_of(U_OKAFOR)})
    assert r.status_code == 200 and outbox(client, email_of(U_OKAFOR)) == []
