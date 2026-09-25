"""Web Push: RFC 8291 encryption checked by an independent receiver, VAPID, the endpoint guard, the device
API, and delivery from the notification dispatch job."""

import base64
import hashlib
import hmac
import json
import os
import time

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from bioverse import webpush
from bioverse.db.seed import U_MAYA, U_OKAFOR
from bioverse.jobs import run_job
from bioverse.notify import notify
from tests.conftest import DB, MAYA, OKAFOR

FCM = "https://fcm.googleapis.com/fcm/send/abc123:APA91bExample"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/gAAAAABexample"
APPLE = "https://web.push.apple.com/QExampleToken"


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------- an independent user agent (receiver side of RFC 8291) ----------

def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 with the standard library's HMAC, deliberately not the module's helper."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm, block, counter = b"", b"", 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


class Browser:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.auth = os.urandom(16)

    @property
    def keys(self) -> dict:
        return {"p256dh": b64u(self.public), "auth": b64u(self.auth)}

    def decrypt(self, body: bytes) -> bytes:
        salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        sender_public = body[21:21 + idlen]
        ciphertext = body[21 + idlen:]
        assert rs == 4096 and idlen == 65 and sender_public[0] == 4
        assert len(ciphertext) <= rs, "one record"
        sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_public)
        shared = self.key.exchange(ec.ECDH(), sender)
        ikm = hkdf(self.auth, shared, b"WebPush: info\x00" + self.public + sender_public, 32)
        cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        record = AESGCM(cek).decrypt(nonce, ciphertext, None)
        stripped = record.rstrip(b"\x00")
        assert stripped[-1:] == b"\x02", "last-record delimiter"
        return stripped[:-1]


@pytest.fixture
def vapid_env(monkeypatch):
    private, public = webpush.keygen()
    monkeypatch.setenv("BIOVERSE_VAPID_PRIVATE_KEY", private)
    monkeypatch.setenv("BIOVERSE_VAPID_SUBJECT", "mailto:care@example.org")
    return public


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    def fake_post(url, data, headers):
        sent.append({"url": url, "data": data, "headers": headers})
        return fake_post.status

    fake_post.status = 201
    monkeypatch.setattr(webpush, "_post", fake_post)
    return fake_post, sent


# ---------- encryption ----------

def test_encryption_round_trip_with_independent_receiver():
    ua = Browser()
    for payload in (b"", b'{"title":"hi"}', os.urandom(webpush.MAX_PAYLOAD)):
        body = webpush.encrypt(payload, ua.keys["p256dh"], ua.keys["auth"])
        assert ua.decrypt(body) == payload
    # Fresh salt and sender key every time.
    a, b = (webpush.encrypt(b"x", **{"p256dh_b64u": ua.keys["p256dh"], "auth_b64u": ua.keys["auth"]}) for _ in "ab")
    assert a[:16] != b[:16] and a[21:86] != b[21:86]
    with pytest.raises(ValueError):
        webpush.encrypt(b"x" * (webpush.MAX_PAYLOAD + 1), ua.keys["p256dh"], ua.keys["auth"])


def test_encryption_matches_rfc8291_example():
    # RFC 8291 section 5.
    sender = ec.derive_private_key(
        int.from_bytes(unb64u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = webpush.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=unb64u("DGv6ra1nlYgDCS1FRnbzlw"),
        sender_key=sender,
    )
    assert b64u(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


# ---------- VAPID ----------

def test_vapid_jwt(vapid_env):
    key = webpush.vapid()
    assert key.public_key == vapid_env and key.subject == "mailto:care@example.org"
    now = time.time()
    auth = webpush.vapid_authorization(FCM, key, now=now)
    assert auth.startswith("vapid t=")
    token, k = auth[len("vapid t="):].split(", k=")
    assert k == vapid_env
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(k))
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == "mailto:care@example.org"
    assert int(now) + 12 * 3600 - 5 <= claims["exp"] <= int(now) + 12 * 3600 + 5
    assert jwt.get_unverified_header(token)["alg"] == "ES256"
    # Signed by the configured key, not some other one.
    other = ec.generate_private_key(ec.SECP256R1()).public_key()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other, algorithms=["ES256"], audience="https://fcm.googleapis.com")


def test_vapid_key_formats(monkeypatch):
    monkeypatch.delenv("BIOVERSE_VAPID_PRIVATE_KEY", raising=False)
    assert webpush.vapid() is None
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("BIOVERSE_VAPID_PRIVATE_KEY", pem)
    monkeypatch.delenv("BIOVERSE_VAPID_SUBJECT", raising=False)
    monkeypatch.setenv("BIOVERSE_EMAIL_FROM", "care@example.org")
    v = webpush.vapid()
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert v.public_key == b64u(raw) and len(raw) == 65
    assert v.subject == "mailto:care@example.org"
    monkeypatch.setenv("BIOVERSE_VAPID_PRIVATE_KEY", "not-a-key")
    assert webpush.vapid() is None


# ---------- endpoint guard ----------

@pytest.mark.parametrize("url", [FCM, MOZ, APPLE, "https://android.googleapis.com/gcm/send/x",
                                 "https://wns2-par02p.notify.windows.com/w/?token=abc",
                                 "https://api.push.apple.com/3/device/x"])
def test_known_push_services_allowed(url):
    assert webpush.check_endpoint(url) == url


@pytest.mark.parametrize("url", [
    "http://fcm.googleapis.com/fcm/send/x",               # not https
    "https://evil.example.com/fcm/send/x",                # unknown host
    "https://fcm.googleapis.com.evil.example/fcm/send/x",  # suffix trick
    "https://storage.googleapis.com/bucket/object",       # Google host, not a push path
    "https://127.0.0.1/fcm/send/x",                       # IP literals
    "https://[::1]/x",
    "https://169.254.169.254/computeMetadata/v1/",
    "https://fcm.googleapis.com:8443/fcm/send/x",         # odd port
    "https://user:pw@fcm.googleapis.com/fcm/send/x",       # credentials
    "file:///etc/passwd",
    "https://metadata.google.internal/",
])
def test_ssrf_guard_rejects(url):
    with pytest.raises(ValueError):
        webpush.check_endpoint(url)


# ---------- device API ----------

def test_config(client, vapid_env, monkeypatch):
    assert client.get("/api/push/config").status_code == 401
    assert client.get("/api/push/config", headers=MAYA).json() == {"enabled": True, "public_key": vapid_env}
    monkeypatch.delenv("BIOVERSE_VAPID_PRIVATE_KEY")
    assert client.get("/api/push/config", headers=MAYA).json() == {"enabled": False, "public_key": None}


def test_subscribe_list_delete_own_only(client, vapid_env):
    ua = Browser()
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1"
    r = client.post("/api/push/subscriptions", headers={**MAYA, "User-Agent": iphone},
                    json={"endpoint": APPLE, "keys": ua.keys})
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    # Validation: bad host, bad keys.
    assert client.post("/api/push/subscriptions", headers=MAYA,
                       json={"endpoint": "https://10.0.0.1/x", "keys": ua.keys}).status_code == 422
    assert client.post("/api/push/subscriptions", headers=MAYA,
                       json={"endpoint": FCM, "keys": {"p256dh": "AAAA", "auth": ua.keys["auth"]}}).status_code == 422
    assert client.post("/api/push/subscriptions", headers=MAYA,
                       json={"endpoint": FCM, "keys": {"p256dh": ua.keys["p256dh"], "auth": "AAAA"}}).status_code == 422

    items = client.get("/api/push/subscriptions", headers=MAYA).json()["items"]
    assert len(items) == 1
    assert items[0]["device"] == "Safari on iPhone" and items[0]["service"] == "Apple"
    assert items[0]["fingerprint"] == hashlib.sha256(APPLE.encode()).hexdigest()[:16]
    assert "endpoint" not in items[0]
    assert client.get("/api/push/subscriptions", headers=OKAFOR).json()["items"] == []

    # Someone else can't remove Maya's device.
    assert client.request("DELETE", "/api/push/subscriptions", headers=OKAFOR, json={"endpoint": APPLE}).status_code == 404
    assert client.delete(f"/api/push/subscriptions/{items[0]['id']}", headers=OKAFOR).status_code == 404
    assert len(client.get("/api/push/subscriptions", headers=MAYA).json()["items"]) == 1

    # The same device re-subscribed by another person moves to them.
    again = client.post("/api/push/subscriptions", headers=OKAFOR, json={"endpoint": APPLE, "keys": Browser().keys})
    assert again.json()["created"] is False
    assert client.get("/api/push/subscriptions", headers=MAYA).json()["items"] == []
    assert len(client.get("/api/push/subscriptions", headers=OKAFOR).json()["items"]) == 1

    assert client.request("DELETE", "/api/push/subscriptions", headers=OKAFOR, json={"endpoint": APPLE}).json() == {"removed": 1}
    assert client.get("/api/push/subscriptions", headers=OKAFOR).json()["items"] == []
    with db() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_events WHERE action LIKE 'push.%' ORDER BY occurred_at, id")]
    assert actions.count("push.subscribe") == 2 and actions.count("push.unsubscribe") == 1


def test_send_test_endpoint(client, vapid_env, pushes, monkeypatch):
    fake, sent = pushes
    ua = Browser()
    client.post("/api/push/subscriptions", headers=MAYA, json={"endpoint": FCM, "keys": ua.keys})
    r = client.post("/api/push/test", headers=MAYA).json()
    assert r == {"devices": 1, "sent": 1, "failed": 0, "removed": 0}
    msg = json.loads(ua.decrypt(sent[0]["data"]))
    assert msg["title"] == "Test notification" and msg["link"] == "/notifications"
    assert client.post("/api/push/test", headers=OKAFOR).json()["devices"] == 0
    monkeypatch.delenv("BIOVERSE_VAPID_PRIVATE_KEY")
    assert client.post("/api/push/test", headers=MAYA).status_code == 409


# ---------- delivery from the dispatch job ----------

def _subscribe(client, headers, endpoint=FCM):
    ua = Browser()
    assert client.post("/api/push/subscriptions", headers=headers,
                       json={"endpoint": endpoint, "keys": ua.keys}).status_code == 200
    return ua


def test_dispatch_delivers_push_without_clinical_detail(client, vapid_env, pushes):
    _, sent = pushes
    phone = _subscribe(client, MAYA, FCM)
    laptop = _subscribe(client, MAYA, MOZ)
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="results_ready", title="New results are ready",
               body="Potassium 6.1 mmol/L, flagged high", link="/results", channels=["in_app", "push"],
               priority="urgent", dedupe_key="p1")
    with db() as conn:
        assert run_job(conn, "dispatch_notifications")["status"] == "succeeded"
        row = conn.execute("SELECT id::text, delivery FROM notifications WHERE dedupe_key = 'p1'").fetchone()
        subs = conn.execute("SELECT last_success_at FROM push_subscriptions WHERE user_id = %s", (U_MAYA,)).fetchall()
    assert row["delivery"]["push"]["status"] == "sent"
    assert row["delivery"]["push"]["detail"] == "2 of 2 devices"
    assert all(s["last_success_at"] for s in subs)
    assert {s["url"] for s in sent} == {FCM, MOZ}
    # The seed also has pending pharmacy-order pushes for Maya; pick out this notification's messages.
    ours = []
    for s in sent:
        plain = (phone if s["url"] == FCM else laptop).decrypt(s["data"])
        if json.loads(plain)["tag"] == row["id"]:
            ours.append((s, plain))
    assert sorted(s["url"] for s, _ in ours) == sorted([FCM, MOZ])
    for s, plain in ours:
        h = s["headers"]
        assert h["Content-Encoding"] == "aes128gcm" and h["TTL"] == "86400" and h["Urgency"] == "high"
        assert h["Authorization"].startswith("vapid t=") and h["Authorization"].endswith(f"k={vapid_env}")
        msg = json.loads(plain)
        assert msg == {"title": "New results are ready", "body": webpush.SAFE_BODY, "link": "/results",
                       "tag": row["id"]}
        assert b"Potassium" not in plain and b"6.1" not in plain


def test_dispatch_normal_urgency_and_gone_subscription_removed(client, vapid_env, pushes):
    fake, sent = pushes
    fake.status = 410
    _subscribe(client, MAYA)
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="test", title="Hello", channels=["in_app", "push"], dedupe_key="p2")
    with db() as conn:
        run_job(conn, "dispatch_notifications")
        row = conn.execute("SELECT delivery FROM notifications WHERE dedupe_key = 'p2'").fetchone()
        left = conn.execute("SELECT count(*) AS n FROM push_subscriptions").fetchone()["n"]
    assert sent[0]["headers"]["Urgency"] == "normal"
    assert left == 0
    assert row["delivery"]["push"]["status"] == "skipped"


def test_dispatch_counts_failures(client, vapid_env, pushes):
    fake, sent = pushes
    fake.status = 500
    _subscribe(client, MAYA)
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="test", title="Hello", channels=["in_app", "push"], dedupe_key="p3")
    with db() as conn:
        result = run_job(conn, "dispatch_notifications")
        row = conn.execute("SELECT delivery FROM notifications WHERE dedupe_key = 'p3'").fetchone()
        sub = conn.execute("SELECT failure_count FROM push_subscriptions").fetchone()
    assert row["delivery"]["push"]["status"] == "failed"
    assert result["detail"]["failed"] >= 1
    assert sub["failure_count"] == len(sent) >= 1      # one per failed attempt (the seed has pushes too)


def test_dispatch_push_skipped_without_key_or_devices(client, monkeypatch, pushes):
    _, sent = pushes
    monkeypatch.delenv("BIOVERSE_VAPID_PRIVATE_KEY", raising=False)
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="test", title="A", channels=["in_app", "push"], dedupe_key="s1")
        run_job(conn, "dispatch_notifications")
        row = conn.execute("SELECT delivery FROM notifications WHERE dedupe_key = 's1'").fetchone()
    assert row["delivery"]["push"] == {**row["delivery"]["push"], "status": "skipped", "detail": "push not configured"}
    private, _ = webpush.keygen()
    monkeypatch.setenv("BIOVERSE_VAPID_PRIVATE_KEY", private)
    with db() as conn:
        notify(conn, user_id=U_OKAFOR, kind="test", title="B", channels=["in_app", "push"], dedupe_key="s2")
        run_job(conn, "dispatch_notifications")
        row = conn.execute("SELECT delivery FROM notifications WHERE dedupe_key = 's2'").fetchone()
    assert row["delivery"]["push"]["detail"] == "no devices"
    assert sent == []


def test_endpoint_rechecked_at_send_time(client, vapid_env, pushes):
    _, sent = pushes
    _subscribe(client, MAYA)
    with db() as conn:
        conn.execute("UPDATE push_subscriptions SET endpoint = 'https://169.254.169.254/latest'")
    with db() as conn:
        counts = webpush.send_to_user(conn, U_MAYA, "Hi", "/x")
    assert counts["removed"] == 1 and sent == []


def test_message_link_is_same_origin_path():
    for bad in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)", None, "/\\evil"):
        assert json.loads(webpush.message("T", bad))["link"] == "/notifications"
    assert json.loads(webpush.message("T", "/results/1"))["link"] == "/results/1"


def test_keygen_cli(capsys):
    assert webpush._main(["keygen"]) == 0
    out = capsys.readouterr().out
    private = out.split("BIOVERSE_VAPID_PRIVATE_KEY=")[1].split()[0]
    public = out.split("public key")[1].split(": ")[1].split()[0]
    assert webpush._parse(private)[1] == public and len(unb64u(public)) == 65


# ---------- the installable app is served ----------

def test_manifest_and_service_worker_served(client):
    from bioverse import main

    if not (main.WEB_DIST / "sw.js").is_file():
        pytest.skip("web app not built (npx vite build)")
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    manifest = r.json()
    assert manifest["start_url"] == "/" and manifest["display"] == "standalone"
    for icon in manifest["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert client.get("/offline.html").status_code == 200
