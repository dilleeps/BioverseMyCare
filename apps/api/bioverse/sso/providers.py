"""Identity provider settings, discovery documents and signing keys."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

MULTI_TENANT = {"common", "organizations", "consumers"}


class SSOError(Exception):
    """A sign-in problem. `code` is safe to show to the user; details go to the log and audit."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    issuer: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    allowed_domains: tuple[str, ...] = ()
    extra_auth_params: dict[str, str] = field(default_factory=dict)
    # Entra multi-tenant: the issuer contains {tenantid}; only these tenants may sign in.
    allowed_tenants: tuple[str, ...] = ()

    @property
    def multi_tenant(self) -> bool:
        return "{tenantid}" in self.issuer

    @property
    def discovery_url(self) -> str:
        base = self.issuer.replace("{tenantid}", self._tenant_path())
        return base.rstrip("/") + "/.well-known/openid-configuration"

    def _tenant_path(self) -> str:
        return os.getenv("BIOVERSE_ENTRA_TENANT_ID", "organizations")


def _csv(name: str) -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip())


def configured() -> dict[str, Provider]:
    """Providers with a client id and secret, keyed by entra / okta / google."""
    out: dict[str, Provider] = {}
    tenant = os.getenv("BIOVERSE_ENTRA_TENANT_ID", "").strip()
    if tenant and os.getenv("BIOVERSE_ENTRA_CLIENT_ID") and os.getenv("BIOVERSE_ENTRA_CLIENT_SECRET"):
        issuer = ("https://login.microsoftonline.com/{tenantid}/v2.0" if tenant.lower() in MULTI_TENANT
                  else f"https://login.microsoftonline.com/{tenant}/v2.0")
        out["entra"] = Provider(
            "entra", "Microsoft", issuer, os.environ["BIOVERSE_ENTRA_CLIENT_ID"],
            os.environ["BIOVERSE_ENTRA_CLIENT_SECRET"], allowed_domains=_csv("BIOVERSE_ENTRA_ALLOWED_DOMAINS"),
            extra_auth_params={"prompt": "select_account"},
            allowed_tenants=_csv("BIOVERSE_ENTRA_ALLOWED_TENANTS"),
        )
    if os.getenv("BIOVERSE_OKTA_ISSUER") and os.getenv("BIOVERSE_OKTA_CLIENT_ID") and os.getenv("BIOVERSE_OKTA_CLIENT_SECRET"):
        out["okta"] = Provider(
            "okta", "Okta", os.environ["BIOVERSE_OKTA_ISSUER"].rstrip("/"), os.environ["BIOVERSE_OKTA_CLIENT_ID"],
            os.environ["BIOVERSE_OKTA_CLIENT_SECRET"], allowed_domains=_csv("BIOVERSE_OKTA_ALLOWED_DOMAINS"),
        )
    if os.getenv("BIOVERSE_GOOGLE_CLIENT_ID") and os.getenv("BIOVERSE_GOOGLE_CLIENT_SECRET"):
        out["google"] = Provider(
            "google", "Google", "https://accounts.google.com", os.environ["BIOVERSE_GOOGLE_CLIENT_ID"],
            os.environ["BIOVERSE_GOOGLE_CLIENT_SECRET"], allowed_domains=_csv("BIOVERSE_GOOGLE_ALLOWED_DOMAINS"),
            extra_auth_params={"prompt": "select_account"},
        )
    return out


def get(key: str) -> Provider:
    p = configured().get(key)
    if p is None:
        raise SSOError("unknown_provider", key)
    return p


def auth_mode() -> str:
    mode = os.getenv("BIOVERSE_AUTH_MODE", "").strip().lower()
    if mode in ("demo", "sso", "sso+demo"):
        return mode
    return "sso" if configured() else "demo"


def demo_allowed() -> bool:
    return "demo" in auth_mode()


def sso_allowed() -> bool:
    return "sso" in auth_mode()


# --- HTTP (module-level so tests can replace them) -------------------------------------------------------


def http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (OSError, ValueError) as exc:
        raise SSOError("provider_unreachable", f"GET {url}: {exc}") from exc


def http_post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()[:500].decode(errors="replace")
        raise SSOError("token_exchange_failed", f"{exc.code}: {body}") from exc
    except (OSError, ValueError) as exc:
        raise SSOError("provider_unreachable", f"POST {url}: {exc}") from exc


_discovery: dict[str, tuple[dict[str, Any], float]] = {}
_jwks: dict[str, tuple[dict[str, Any], float]] = {}
CACHE_SECONDS = 3600


def discovery(p: Provider) -> dict[str, Any]:
    hit = _discovery.get(p.discovery_url)
    if hit and hit[1] > time.time():
        return hit[0]
    doc = http_get_json(p.discovery_url)
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if key not in doc:
            raise SSOError("provider_misconfigured", f"discovery for {p.key} has no {key}")
    _discovery[p.discovery_url] = (doc, time.time() + CACHE_SECONDS)
    return doc


def signing_keys(p: Provider, *, refresh: bool = False) -> dict[str, Any]:
    uri = discovery(p)["jwks_uri"]
    hit = _jwks.get(uri)
    if hit and hit[1] > time.time() and not refresh:
        return hit[0]
    keys = http_get_json(uri)
    _jwks[uri] = (keys, time.time() + CACHE_SECONDS)
    return keys


def clear_caches() -> None:
    _discovery.clear()
    _jwks.clear()
