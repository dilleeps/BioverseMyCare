"""Authorization request, code exchange and ID token validation."""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any

import jwt

from bioverse.sso.providers import Provider, SSOError, discovery, signing_keys

ALLOWED_ALGS = ["RS256", "RS384", "RS512", "PS256", "ES256"]
LEEWAY_SECONDS = 60


def new_login_secrets() -> tuple[str, str, str]:
    """state, nonce, PKCE code verifier."""
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(p: Provider, *, redirect_uri: str, state: str, nonce: str, verifier: str,
                  login_hint: str | None = None) -> str:
    params = {
        "response_type": "code",
        "client_id": p.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(p.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
        **p.extra_auth_params,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return discovery(p)["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


def exchange_code(p: Provider, *, code: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
    from bioverse.sso import providers  # module attribute, so tests can replace the HTTP call

    tokens = providers.http_post_form(discovery(p)["token_endpoint"], {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": p.client_id,
        "client_secret": p.client_secret,
        "code_verifier": verifier,
    })
    if "id_token" not in tokens:
        raise SSOError("token_exchange_failed", f"no id_token from {p.key}")
    return tokens


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    tenant: str | None
    claims: dict[str, Any]


def _key_for(p: Provider, token: str):
    kid = jwt.get_unverified_header(token).get("kid")
    for refresh in (False, True):  # keys rotate: refetch once when the kid is unknown
        jwks = jwt.PyJWKSet.from_dict(signing_keys(p, refresh=refresh))
        for key in jwks.keys:
            if kid is None or key.key_id == kid:
                return key
    raise SSOError("invalid_token", f"no signing key {kid} for {p.key}")


def validate_id_token(p: Provider, token: str, *, nonce: str) -> VerifiedIdentity:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise SSOError("invalid_token", f"unreadable header: {exc}") from exc
    if header.get("alg") not in ALLOWED_ALGS:
        raise SSOError("invalid_token", f"algorithm {header.get('alg')} not allowed")
    key = _key_for(p, token)
    try:
        claims = jwt.decode(
            token, key=key, algorithms=ALLOWED_ALGS, audience=p.client_id, leeway=LEEWAY_SECONDS,
            options={"require": ["iss", "sub", "aud", "exp", "iat"], "verify_iss": False},
        )
    except jwt.PyJWTError as exc:
        raise SSOError("invalid_token", str(exc)) from exc

    # Issuer: exact match, or the Entra multi-tenant template filled with the token's own tenant.
    tenant = claims.get("tid")
    expected = p.issuer.replace("{tenantid}", tenant or "") if p.multi_tenant else p.issuer
    if claims["iss"].rstrip("/") != expected.rstrip("/"):
        raise SSOError("invalid_token", f"issuer {claims['iss']} is not {expected}")
    if p.multi_tenant and tenant not in p.allowed_tenants:
        raise SSOError("tenant_not_allowed", f"tenant {tenant}")
    if claims.get("nonce") != nonce:
        raise SSOError("invalid_token", "nonce mismatch")
    aud = claims["aud"]
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != p.client_id:
        raise SSOError("invalid_token", "authorized party mismatch")

    email, verified = _email(p, claims)
    return VerifiedIdentity(
        provider=p.key, subject=str(claims["sub"]), email=email, email_verified=verified,
        name=claims.get("name"), tenant=tenant or claims.get("hd"), claims=claims,
    )


def _email(p: Provider, claims: dict[str, Any]) -> tuple[str | None, bool]:
    """The account's email and whether Bioverse may trust it to link to an existing user."""
    if p.key == "entra":
        # Entra accounts are managed by their tenant's administrators. `email` is optional and may be
        # unverified in multi-tenant apps, so trust it only for this configured tenant or allowed tenants.
        email = claims.get("email") or claims.get("preferred_username")
        trusted = bool(email and "@" in email and (not p.multi_tenant or claims.get("tid") in p.allowed_tenants))
        return (email.lower() if email else None), trusted
    email = claims.get("email")
    return (email.lower() if email else None), claims.get("email_verified") in (True, "true")
