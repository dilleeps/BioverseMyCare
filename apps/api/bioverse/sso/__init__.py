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
"""
