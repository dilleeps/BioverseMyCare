"""Sign-in with Microsoft Entra ID, Okta and Google (OpenID Connect), and sign-out."""

from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from psycopg import Connection

from bioverse import audit
from bioverse.db import DbConn
from bioverse.sso import link, oidc, providers, sessions
from bioverse.sso.providers import SSOError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["sign-in"])

LOGIN_REQUEST_TTL = timedelta(minutes=10)

# Messages the sign-in page shows for each error code. Details stay in the log and the audit trail.
ERRORS = {
    "not_registered": "Your account isn't set up in Bioverse One yet. Ask your administrator to add your email.",
    "email_unverified": "Your identity provider didn't confirm your email address, so we can't match your account.",
    "domain_not_allowed": "Accounts from that email domain can't sign in here.",
    "tenant_not_allowed": "Your organization's directory isn't allowed to sign in here.",
    "account_disabled": "This account has been turned off. Contact your administrator.",
    "invalid_state": "The sign-in expired or was started in another window. Please try again.",
    "access_denied": "Sign-in was cancelled.",
}


def _public_base(request: Request) -> str:
    return (os.getenv("BIOVERSE_PUBLIC_URL") or str(request.base_url)).rstrip("/")


def redirect_uri(request: Request, provider: str) -> str:
    return f"{_public_base(request)}/api/auth/callback/{provider}"


def _safe_next(path: str | None) -> str:
    """Only same-site paths: "/app", never "//evil.example" or "https://...""."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


def _fail(request: Request, conn: Connection, provider: str, exc: SSOError) -> RedirectResponse:
    log.warning("sign-in failed via %s: %s (%s)", provider, exc.code, exc.detail)
    audit.record(conn, action="auth.sign_in_failed", entity_type="auth", agent=f"sso/{provider}",
                 detail={"provider": provider, "code": exc.code})
    resp = RedirectResponse(f"/signin?error={urllib.parse.quote(exc.code)}", status_code=303)
    resp.delete_cookie(sessions.STATE_COOKIE, path="/api/auth")
    return resp


@router.get("/config")
def config() -> dict:
    """What the sign-in page offers. Public."""
    return {
        "mode": providers.auth_mode(),
        "demo": providers.demo_allowed(),
        "providers": [{"key": p.key, "label": p.label} for p in providers.configured().values()]
        if providers.sso_allowed() else [],
        "errors": ERRORS,
    }


@router.get("/login/{provider}")
def login(provider: str, request: Request, conn: DbConn, next: str | None = None,
          login_hint: str | None = None) -> RedirectResponse:
    if not providers.sso_allowed():
        raise HTTPException(404, "Single sign-on is off")
    try:
        p = providers.get(provider)
        state, nonce, verifier = oidc.new_login_secrets()
        url = oidc.authorize_url(p, redirect_uri=redirect_uri(request, provider), state=state, nonce=nonce,
                                 verifier=verifier, login_hint=login_hint)
    except SSOError as exc:
        return _fail(request, conn, provider, exc)
    conn.execute("DELETE FROM oidc_login_requests WHERE created_at < now() - %s", (LOGIN_REQUEST_TTL,))
    conn.execute(
        "INSERT INTO oidc_login_requests (state, provider, nonce, code_verifier, next_path) VALUES (%s, %s, %s, %s, %s)",
        (state, provider, nonce, verifier, _safe_next(next)),
    )
    resp = RedirectResponse(url, status_code=303)
    # Binds the sign-in to this browser: the callback must present the same state.
    resp.set_cookie(sessions.STATE_COOKIE, state, max_age=int(LOGIN_REQUEST_TTL.total_seconds()), httponly=True,
                    secure=sessions.cookie_secure(), samesite="lax", path="/api/auth")
    return resp


@router.get("/callback/{provider}")
def callback(provider: str, request: Request, conn: DbConn, code: str | None = None, state: str | None = None,
             error: str | None = None) -> RedirectResponse:
    if error:
        return _fail(request, conn, provider, SSOError("access_denied" if error == "access_denied" else "provider_error", error))
    try:
        cookie_state = request.cookies.get(sessions.STATE_COOKIE)
        if not state or not code or cookie_state != state:
            raise SSOError("invalid_state", "state missing or does not match this browser")
        req = conn.execute(
            """
            DELETE FROM oidc_login_requests WHERE state = %s AND provider = %s AND created_at > now() - %s
            RETURNING nonce, code_verifier, next_path
            """,
            (state, provider, LOGIN_REQUEST_TTL),
        ).fetchone()
        if req is None:
            raise SSOError("invalid_state", "unknown, used or expired state")
        p = providers.get(provider)
        tokens = oidc.exchange_code(p, code=code, redirect_uri=redirect_uri(request, provider),
                                    verifier=req["code_verifier"])
        ident = oidc.validate_id_token(p, tokens["id_token"], nonce=req["nonce"])
        user_id, how = link.resolve_user(conn, p, ident)
    except SSOError as exc:
        return _fail(request, conn, provider, exc)

    token = sessions.create(conn, user_id=user_id, provider=provider, id_token=tokens["id_token"],
                            user_agent=request.headers.get("user-agent"))
    audit.record(conn, action="auth.sign_in", entity_type="user", entity_id=user_id, agent=f"sso/{provider}",
                 detail={"provider": provider, "how": how, "tenant": ident.tenant})
    resp = RedirectResponse(req["next_path"], status_code=303)
    resp.set_cookie(sessions.SESSION_COOKIE, token, max_age=sessions.max_hours() * 3600, httponly=True,
                    secure=sessions.cookie_secure(), samesite="lax", path="/")
    resp.delete_cookie(sessions.STATE_COOKIE, path="/api/auth")
    return resp


@router.post("/logout")
def logout(request: Request, conn: DbConn) -> JSONResponse:
    """Ends the Bioverse session. Returns the provider's sign-out URL when it has one."""
    token = request.cookies.get(sessions.SESSION_COOKIE)
    redirect = "/signin"
    if token:
        row = sessions.revoke(conn, token)
        if row:
            audit.record(conn, action="auth.sign_out", entity_type="user", entity_id=row["user_id"],
                         agent=f"sso/{row['provider']}")
            try:
                p = providers.get(row["provider"])
                end = providers.discovery(p).get("end_session_endpoint")
                if end:
                    q = {"post_logout_redirect_uri": f"{_public_base(request)}/signin", "client_id": p.client_id}
                    if row["id_token_hint"]:
                        q["id_token_hint"] = row["id_token_hint"]
                    redirect = end + "?" + urllib.parse.urlencode(q)
            except SSOError:
                pass
    resp = JSONResponse({"redirect": redirect})
    resp.delete_cookie(sessions.SESSION_COOKIE, path="/")
    return resp
