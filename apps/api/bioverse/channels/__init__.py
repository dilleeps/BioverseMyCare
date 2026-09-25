"""Delivery channels for notifications beyond the in-app inbox.

Each channel is a function `send(to, title, body, link) -> Result`. A channel that has no configuration
returns `skipped` instead of failing, so the app runs the same locally, in tests and in the cloud.

    email   BIOVERSE_SMTP_URL=smtp://user:password@host:587   BIOVERSE_EMAIL_FROM=care@example.org
    sms     TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    push    BIOVERSE_VAPID_PRIVATE_KEY (see bioverse/webpush.py). Web Push to every phone and browser the
            user turned push on for; the dispatch job calls webpush.deliver, which needs the database to
            find the user's devices. `send_push` below only stands in for callers without a user id.

Messages sent outside the app never contain clinical detail: only the title and a link back into
Bioverse One, where the user signs in to read the rest.

    BIOVERSE_OUTBOUND_ALLOWLIST=you@example.org,+15555550123

While the demo sign-in is in place, anyone can type any email address or phone number into a demo
account's preferences. When this variable is set, email and texts go only to the listed addresses and
numbers; everything else is recorded as skipped. Set it whenever real email or SMS credentials are
configured on a public demo.
"""

from __future__ import annotations

import base64
import json
import os
import smtplib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class Result:
    status: str          # sent | skipped | failed
    detail: str = ""


def _allowed(to: str) -> bool:
    raw = os.getenv("BIOVERSE_OUTBOUND_ALLOWLIST", "").strip()
    if not raw:
        return True
    allowed = {x.strip().lower().replace(" ", "") for x in raw.split(",") if x.strip()}
    return to.strip().lower().replace(" ", "") in allowed


def public_url(link: str | None) -> str:
    base = os.getenv("BIOVERSE_PUBLIC_URL", "").rstrip("/")
    if not link:
        return base or ""
    return f"{base}{link}" if base else link


def send_email(to: str | None, title: str, link: str | None) -> Result:
    url = os.getenv("BIOVERSE_SMTP_URL")
    if not url:
        return Result("skipped", "email not configured")
    if not to:
        return Result("skipped", "no email address")
    if not _allowed(to):
        return Result("skipped", "recipient not on the outbound allowlist")
    parts = urllib.parse.urlparse(url)
    msg = EmailMessage()
    msg["From"] = os.getenv("BIOVERSE_EMAIL_FROM", "no-reply@bioverse.example")
    msg["To"] = to
    msg["Subject"] = f"Bioverse One: {title}"
    msg.set_content(
        f"{title}\n\nOpen Bioverse One to see the details:\n{public_url(link)}\n\n"
        "You're receiving this because notifications are on in your Bioverse One settings."
    )
    try:
        cls = smtplib.SMTP_SSL if parts.scheme == "smtps" else smtplib.SMTP
        with cls(parts.hostname, parts.port or (465 if parts.scheme == "smtps" else 587), timeout=10) as s:
            if parts.scheme == "smtp":
                s.starttls()
            if parts.username:
                s.login(urllib.parse.unquote(parts.username), urllib.parse.unquote(parts.password or ""))
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - any delivery failure is recorded, never raised
        return Result("failed", type(exc).__name__)
    return Result("sent")


def send_sms(to: str | None, title: str, link: str | None) -> Result:
    sid, token, sender = (os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    if not (sid and token and sender):
        return Result("skipped", "sms not configured")
    if not to:
        return Result("skipped", "no phone number")
    if not _allowed(to):
        return Result("skipped", "recipient not on the outbound allowlist")
    body = f"Bioverse One: {title}. {public_url(link)}".strip()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=urllib.parse.urlencode({"To": to, "From": sender, "Body": body[:320]}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read() or b"{}")
    except Exception as exc:  # noqa: BLE001
        return Result("failed", type(exc).__name__)
    return Result("sent", data.get("sid", ""))


def send_push(_to: str | None, _title: str, _link: str | None) -> Result:
    return Result("skipped", "background push not configured")


SENDERS = {"email": send_email, "sms": send_sms, "push": send_push}
