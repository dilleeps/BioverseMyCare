"""Signed, expiring tokens for the digital insurance card's QR code.

Format: "BVC1." + base64url(payload || HMAC-SHA256(payload)), where payload is 29 bytes:
    version (1) | coverage id (16, UUID bytes) | issued at (4, unix seconds) | expires at (4) | nonce (4)
The whole token is under 90 characters, which keeps the QR code small enough to scan from a phone.

The key is BIOVERSE_CARD_SECRET. Without it a development default is used and a warning is logged;
`using_default_secret()` lets the admin screen say so. Tokens prove the card was issued by this server
and is recent; they are not a credential for anything else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
import time
import uuid
from dataclasses import dataclass

log = logging.getLogger(__name__)

PREFIX = "BVC1."
VERSION = 1
TTL_SECONDS = 15 * 60
CLOCK_SKEW = 60
DEV_SECRET = "bioverse-dev-card-secret-change-me"
_PAYLOAD = struct.Struct(">B16sIII")
_warned = False


class TokenError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CardClaims:
    coverage_id: str
    issued_at: int
    expires_at: int


def using_default_secret() -> bool:
    return not os.getenv("BIOVERSE_CARD_SECRET")


def _key() -> bytes:
    global _warned
    value = os.getenv("BIOVERSE_CARD_SECRET")
    if not value:
        if not _warned:
            log.warning("BIOVERSE_CARD_SECRET is not set: insurance card codes are signed with the development "
                        "default. Set a long random secret before any real use.")
            _warned = True
        value = DEV_SECRET
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(coverage_id: str, *, now: float | None = None, ttl: int = TTL_SECONDS) -> tuple[str, int]:
    """A token for this coverage and when it expires (unix seconds)."""
    issued = int(now if now is not None else time.time())
    expires = issued + ttl
    payload = _PAYLOAD.pack(VERSION, uuid.UUID(coverage_id).bytes, issued, expires, secrets.randbits(32))
    mac = hmac.new(_key(), payload, hashlib.sha256).digest()
    return PREFIX + _b64(payload + mac), expires


def verify(token: str, *, now: float | None = None) -> CardClaims:
    token = (token or "").strip()
    if not token.startswith(PREFIX):
        raise TokenError("malformed", "This isn't a Bioverse insurance card code.")
    try:
        raw = _unb64(token[len(PREFIX):])
    except (ValueError, TypeError):
        raise TokenError("malformed", "This card code is damaged. Ask the patient to show the card again.") from None
    if len(raw) != _PAYLOAD.size + 32:
        raise TokenError("malformed", "This card code is damaged. Ask the patient to show the card again.")
    payload, mac = raw[:_PAYLOAD.size], raw[_PAYLOAD.size:]
    expected = hmac.new(_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise TokenError("bad_signature", "This card code was not issued by Bioverse, or it was altered.")
    version, cov, issued, expires, _nonce = _PAYLOAD.unpack(payload)
    if version != VERSION:
        raise TokenError("malformed", "This card code uses a version this server doesn't read.")
    current = int(now if now is not None else time.time())
    if issued > current + CLOCK_SKEW:
        raise TokenError("bad_signature", "This card code claims to be issued in the future.")
    if current >= expires:
        raise TokenError("expired", "This card code has expired. Ask the patient to refresh the card on their phone.")
    return CardClaims(coverage_id=str(uuid.UUID(bytes=cov)), issued_at=issued, expires_at=expires)
