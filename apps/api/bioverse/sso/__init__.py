"""Single sign-on with OpenID Connect: Microsoft Entra ID, Okta and Google.

Flow (authorization code with PKCE, confidential client):

1. GET /api/auth/login/{provider}  -> state, nonce and PKCE verifier are stored server-side; the browser gets
   a short-lived state cookie and is redirected to the provider.
2. GET /api/auth/callback/{provider} -> the state must match the cookie and a stored request (single use);
   the code is exchanged at the token endpoint; the ID token's signature (provider JWKS), issuer, audience,
   expiry and nonce are checked.
3. The verified identity is linked to a Bioverse user (see link.py) and a server-side session starts:
   an opaque random cookie (HttpOnly, Secure, SameSite=Lax) whose hash is stored in auth_sessions.

The identity provider only proves who someone is. Role, team and organization stay in Bioverse.

Configuration (environment; client secrets from Secret Manager):

    BIOVERSE_AUTH_MODE            demo | sso | sso+demo   (default: sso when a provider is configured, else demo)
    BIOVERSE_PUBLIC_URL           https://... used for redirect URIs: {PUBLIC_URL}/api/auth/callback/{provider}

    BIOVERSE_ENTRA_TENANT_ID      directory (tenant) id, or "organizations" for multi-tenant
    BIOVERSE_ENTRA_CLIENT_ID / BIOVERSE_ENTRA_CLIENT_SECRET
    BIOVERSE_ENTRA_ALLOWED_TENANTS  required with "organizations": tenant ids allowed to sign in

    BIOVERSE_OKTA_ISSUER          https://{yourOktaDomain}/oauth2/default (or the org issuer)
    BIOVERSE_OKTA_CLIENT_ID / BIOVERSE_OKTA_CLIENT_SECRET

    BIOVERSE_GOOGLE_CLIENT_ID / BIOVERSE_GOOGLE_CLIENT_SECRET

    BIOVERSE_{ENTRA|OKTA|GOOGLE}_ALLOWED_DOMAINS   optional email domains allowed to sign in
    BIOVERSE_BOOTSTRAP_ADMINS     emails that become administrators on first sign-in (to set up the rest)
    BIOVERSE_SESSION_IDLE_MINUTES (default 60), BIOVERSE_SESSION_MAX_HOURS (default 12)

Patient invites and email codes (bioverse/routers/invites.py, routers/email_signin.py, sso/plugins/invites.py):
staff send an invite link ({PUBLIC_URL}/join/{token}); after confirming their date of birth the patient signs
in with a provider above (`/api/auth/login/google?invite={token}`), which creates their account, or with a
6-digit code sent by email. Email codes are for patients only; staff and clinicians always use single sign-on.

    BIOVERSE_EMAIL_SIGNIN         on | off. Unset: on whenever single sign-on is allowed. Email sign-in starts
                                  the same bv_session cookie, which the API honours only in sso or sso+demo mode.
    BIOVERSE_SELF_REGISTRATION    on lets people register at /register without an invite (default off).
    Codes and invites are emailed via bioverse.channels (BIOVERSE_SMTP_URL, BIOVERSE_OUTBOUND_ALLOWLIST).
    While demo sign-in is allowed, a copy lands in the dev outbox (GET /api/auth/dev-outbox?email=...).
"""
