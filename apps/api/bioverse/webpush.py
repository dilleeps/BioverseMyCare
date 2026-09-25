"""Background Web Push to phones and browsers, with no third-party push library.

Messages are encrypted for each device with RFC 8291 (aes128gcm) and signed with a VAPID key (RFC 8292),
then POSTed to the device's push service. The service worker (apps/web/public/sw.js) shows them.

    BIOVERSE_VAPID_PRIVATE_KEY   the P-256 private key: base64url of the raw 32-byte scalar, or a PEM.
                                 Without it push is off and deliveries are recorded as skipped.
    BIOVERSE_VAPID_SUBJECT       contact for the push services, "mailto:..." or "https://...".
                                 Default: mailto: + BIOVERSE_EMAIL_FROM.

    python -m bioverse.webpush keygen      # print a new private key and its public key

Changing the key invalidates every existing subscription; devices subscribe again the next time the
app is opened.

Like email and SMS (bioverse/channels), a push carries no clinical detail: only the notification's title,
a fixed "open the app" line and a link back into Bioverse One.

Only the push services of the major browsers are ever contacted (see `check_endpoint`), so a subscription
cannot be used to make the server call an arbitrary address.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from psycopg import Connection

from bioverse.channels import Result

log = logging.getLogger("bioverse.webpush")

TTL_SECONDS = 86400
RECORD_SIZE = 4096
TIMEOUT_SECONDS = 10
# Push services accept at least 4096 bytes of body: 86 bytes of header, the payload, a delimiter and a tag.
MAX_PAYLOAD = RECORD_SIZE - 86 - 1 - 16
SAFE_BODY = "Open Bioverse One to see the details"
DEFAULT_LINK = "/notifications"

# Push services of Chrome/Edge/Android (Google), Firefox (Mozilla), Safari/iOS (Apple) and Windows (WNS).
_EXACT_HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
_SUFFIXES = (".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")
_GOOGLE_PUSH_PATHS = ("/fcm/", "/wp/", "/gcm/")


# ---------- helpers ----------

def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------- keys ----------

@dataclass(frozen=True)
class Vapid:
    private_key: ec.EllipticCurvePrivateKey
    public_key: str          # base64url of the 65-byte uncompressed point: the browser's applicationServerKey
    subject: str


def load_private_key(raw: str) -> ec.EllipticCurvePrivateKey:
    raw = raw.strip()
    if raw.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(raw.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("VAPID key must be a P-256 (prime256v1) EC key")
        return key
    scalar = b64u_decode(raw)
    if len(scalar) != 32:
        raise ValueError("VAPID private key must be 32 bytes, base64url encoded")
    return ec.derive_private_key(int.from_bytes(scalar, "big"), ec.SECP256R1())


def default_subject() -> str:
    sub = os.getenv("BIOVERSE_VAPID_SUBJECT", "").strip()
    if not sub:
        sub = os.getenv("BIOVERSE_EMAIL_FROM", "").strip() or "no-reply@bioverse.example"
    if not sub.startswith(("mailto:", "https://")):
        sub = f"mailto:{sub}"
    return sub


@lru_cache(maxsize=4)
def _parse(raw: str) -> tuple[ec.EllipticCurvePrivateKey, str]:
    key = load_private_key(raw)
    return key, b64u_encode(_public_bytes(key.public_key()))


def vapid() -> Vapid | None:
    """The configured key, or None when push is off (or the key can't be read)."""
    raw = os.getenv("BIOVERSE_VAPID_PRIVATE_KEY", "").strip()
    if not raw:
        return None
    try:
        key, public = _parse(raw)
    except Exception:  # noqa: BLE001 - a bad key turns push off; never crash the app or a job
        log.warning("BIOVERSE_VAPID_PRIVATE_KEY is set but could not be read; push is off")
        return None
    return Vapid(key, public, default_subject())


def keygen() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64u_encode(key.private_numbers().private_value.to_bytes(32, "big"))
    return private, b64u_encode(_public_bytes(key.public_key()))


# ---------- endpoint guard ----------

def check_endpoint(url: str) -> str:
    """Return the endpoint if it is an https URL on a known push service; raise ValueError otherwise."""
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Push endpoint is too long")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("Push endpoint must use https")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("Push endpoint must not carry credentials")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError("Push endpoint has no host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Push endpoint must be a push service, not an IP address")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("Push endpoint has an invalid port") from None
    if port not in (None, 443):
        raise ValueError("Push endpoint must use the standard https port")
    if host.endswith(".googleapis.com") or host == "googleapis.com":
        if not parts.path.startswith(_GOOGLE_PUSH_PATHS):
            raise ValueError("Not a Google push endpoint")
        return url
    if host in _EXACT_HOSTS or host.endswith(_SUFFIXES):
        return url
    raise ValueError("Push endpoint is not a known push service")


def validate_keys(p256dh: str, auth: str) -> None:
    try:
        point = b64u_decode(p256dh)
        secret = b64u_decode(auth)
    except Exception:  # noqa: BLE001
        raise ValueError("Push keys must be base64url") from None
    if len(point) != 65 or point[0] != 4:
        raise ValueError("p256dh must be an uncompressed P-256 public key")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise ValueError("p256dh is not a valid P-256 public key") from None
    if len(secret) != 16:
        raise ValueError("auth must be 16 bytes")


def service_name(endpoint: str) -> str:
    host = (urllib.parse.urlsplit(endpoint).hostname or "").lower()
    if host.endswith("googleapis.com"):
        return "Google"
    if host.endswith("mozilla.com"):
        return "Mozilla"
    if host.endswith("apple.com"):
        return "Apple"
    if host.endswith("windows.com"):
        return "Microsoft"
    return host


# ---------- RFC 8291 message encryption ----------

def encrypt(payload: bytes, p256dh_b64u: str, auth_b64u: str, *, salt: bytes | None = None,
            sender_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Encrypt `payload` for one browser subscription. Returns the full aes128gcm request body.

    `salt` and `sender_key` are for tests; normally both are fresh for every message.
    """
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Push payload is larger than {MAX_PAYLOAD} bytes")
    ua_public = b64u_decode(p256dh_b64u)
    auth_secret = b64u_decode(auth_b64u)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(as_key.public_key())
    salt = salt or os.urandom(16)

    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)   # one record, last-record delimiter
    header = salt + struct.pack("!I", RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + ciphertext


# ---------- RFC 8292 VAPID ----------

def vapid_authorization(endpoint: str, key: Vapid, now: float | None = None) -> str:
    parts = urllib.parse.urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(now if now is not None else time.time()) + 12 * 3600,
        "sub": key.subject,
    }
    token = jwt.encode(claims, key.private_key, algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={key.public_key}"


# ---------- HTTP ----------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A push service never redirects; following one would let it point us somewhere else."""

    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _post(url: str, data: bytes, headers: dict[str, str]) -> int:
    """POST to a push service and return the HTTP status (0 when the service can't be reached)."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with _opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001 - recorded as a failure, never raised
        log.info("push service unreachable: %s", type(exc).__name__)
        return 0


# ---------- delivery ----------

def safe_link(link: str | None) -> str:
    """Only paths inside the app; anything else opens the notification inbox."""
    if not link or not link.startswith("/") or link.startswith("//") or "\\" in link:
        return DEFAULT_LINK
    return link


def message(title: str, link: str | None, tag: str | None = None) -> bytes:
    """The JSON the service worker receives. Never includes the notification body."""
    return json.dumps(
        {"title": title[:120], "body": SAFE_BODY, "link": safe_link(link), "tag": tag or "bioverse"},
        separators=(",", ":"),
    ).encode()


def send_to_user(conn: Connection, user_id: str, title: str, link: str | None, *, urgent: bool = False,
                 tag: str | None = None, key: Vapid | None = None) -> dict:
    """Send to every device the user has turned push on for. Returns counts."""
    counts = {"devices": 0, "sent": 0, "failed": 0, "removed": 0}
    key = key or vapid()
    if key is None:
        return counts
    subs = conn.execute(
        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s ORDER BY created_at",
        (user_id,),
    ).fetchall()
    counts["devices"] = len(subs)
    body = message(title, link, tag)
    for s in subs:
        try:
            check_endpoint(s["endpoint"])
        except ValueError:
            conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (s["id"],))
            counts["removed"] += 1
            continue
        try:
            data = encrypt(body, s["p256dh"], s["auth"])
            headers = {
                "Authorization": vapid_authorization(s["endpoint"], key),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "high" if urgent else "normal",
            }
        except Exception:  # noqa: BLE001 - a malformed stored key fails this device only
            status = -1
        else:
            status = _post(s["endpoint"], data, headers)
        if 200 <= status < 300:
            conn.execute(
                "UPDATE push_subscriptions SET last_success_at = now(), failure_count = 0 WHERE id = %s",
                (s["id"],),
            )
            counts["sent"] += 1
        elif status in (404, 410):
            # The browser unsubscribed or the app was removed: the push service will never accept it again.
            conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (s["id"],))
            counts["removed"] += 1
        else:
            conn.execute(
                "UPDATE push_subscriptions SET failure_count = failure_count + 1 WHERE id = %s", (s["id"],)
            )
            counts["failed"] += 1
    return counts


def deliver(conn: Connection, user_id: str, title: str, link: str | None, priority: str = "normal",
            tag: str | None = None) -> Result:
    """The push channel for the notification dispatch job."""
    key = vapid()
    if key is None:
        return Result("skipped", "push not configured")
    c = send_to_user(conn, user_id, title, link, urgent=priority == "urgent", tag=tag, key=key)
    if c["devices"] == 0:
        return Result("skipped", "no devices")
    detail = f"{c['sent']} of {c['devices']} devices"
    if c["removed"]:
        detail += f", {c['removed']} removed"
    if c["sent"]:
        return Result("sent", detail)
    if c["failed"] == 0:
        return Result("skipped", f"no devices ({c['removed']} expired and removed)")
    return Result("failed", detail)


def _main(argv: list[str]) -> int:
    if argv[:1] != ["keygen"]:
        print("Usage: python -m bioverse.webpush keygen", file=sys.stderr)
        return 2
    private, public = keygen()
    print(f"BIOVERSE_VAPID_PRIVATE_KEY={private}")
    print(f"# public key (served to browsers by /api/push/config): {public}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
