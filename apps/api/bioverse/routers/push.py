"""Web Push: the devices a user has turned push on for, and a test message. Delivery is in bioverse/webpush.py."""

from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from bioverse import audit, webpush
from bioverse.auth import CurrentUser
from bioverse.db import DbConn

router = APIRouter(prefix="/api/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class Subscription(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: Keys


class Endpoint(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


def fingerprint(endpoint: str) -> str:
    """Lets the app recognise its own device in the list without the server handing endpoints back."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


def device_label(user_agent: str | None) -> str:
    ua = user_agent or ""
    browser = next((name for pattern, name in (
        (r"EdgA?/", "Edge"), (r"SamsungBrowser/", "Samsung Internet"), (r"Firefox/|FxiOS/", "Firefox"),
        (r"CriOS/|Chrome/", "Chrome"), (r"Safari/", "Safari"),
    ) if re.search(pattern, ua)), "Browser")
    system = next((name for pattern, name in (
        (r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"Android", "Android"), (r"Windows", "Windows"),
        (r"Macintosh|Mac OS X", "Mac"), (r"CrOS", "Chromebook"), (r"Linux", "Linux"),
    ) if re.search(pattern, ua)), None)
    return f"{browser} on {system}" if system else browser


@router.get("/config")
def config(_: CurrentUser) -> dict:
    key = webpush.vapid()
    return {"enabled": key is not None, "public_key": key.public_key if key else None}


@router.get("/subscriptions")
def list_subscriptions(conn: DbConn, user: CurrentUser) -> dict:
    rows = conn.execute(
        """
        SELECT id::text, endpoint, user_agent, created_at, last_success_at, failure_count
        FROM push_subscriptions WHERE user_id = %s ORDER BY created_at DESC
        """,
        (user.id,),
    ).fetchall()
    return {"items": [
        {"id": r["id"], "device": device_label(r["user_agent"]), "service": webpush.service_name(r["endpoint"]),
         "fingerprint": fingerprint(r["endpoint"]), "created_at": r["created_at"],
         "last_success_at": r["last_success_at"], "failure_count": r["failure_count"]}
        for r in rows
    ]}


@router.post("/subscriptions")
def subscribe(body: Subscription, request: Request, conn: DbConn, user: CurrentUser) -> dict:
    try:
        webpush.check_endpoint(body.endpoint)
        webpush.validate_keys(body.keys.p256dh, body.keys.auth)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = conn.execute(
        """
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh,
            auth = excluded.auth, user_agent = excluded.user_agent, failure_count = 0
        RETURNING id::text, (xmax = 0) AS created
        """,
        (user.id, body.endpoint, body.keys.p256dh, body.keys.auth, (request.headers.get("user-agent") or "")[:300]),
    ).fetchone()
    audit.record(conn, action="push.subscribe", entity_type="push_subscription", entity_id=row["id"], actor=user,
                 patient_id=user.patient_id, detail={"service": webpush.service_name(body.endpoint)})
    return {"id": row["id"], "created": row["created"], "fingerprint": fingerprint(body.endpoint)}


def _remove(conn, user, where: str, value: str) -> dict:
    row = conn.execute(
        f"DELETE FROM push_subscriptions WHERE {where} = %s AND user_id = %s RETURNING id::text, endpoint",
        (value, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Device not found")
    audit.record(conn, action="push.unsubscribe", entity_type="push_subscription", entity_id=row["id"],
                 actor=user, patient_id=user.patient_id, detail={"service": webpush.service_name(row["endpoint"])})
    return {"removed": 1}


@router.delete("/subscriptions")
def unsubscribe(body: Endpoint, conn: DbConn, user: CurrentUser) -> dict:
    return _remove(conn, user, "endpoint", body.endpoint)


@router.delete("/subscriptions/{subscription_id}")
def remove_device(subscription_id: str, conn: DbConn, user: CurrentUser) -> dict:
    return _remove(conn, user, "id::text", subscription_id)


@router.post("/test")
def send_test(conn: DbConn, user: CurrentUser) -> dict:
    key = webpush.vapid()
    if key is None:
        raise HTTPException(409, "Push isn't turned on for this server")
    counts = webpush.send_to_user(conn, user.id, "Test notification", "/notifications", tag="bioverse-test", key=key)
    audit.record(conn, action="push.test", entity_type="user", entity_id=user.id, actor=user,
                 patient_id=user.patient_id, detail=counts)
    return counts
