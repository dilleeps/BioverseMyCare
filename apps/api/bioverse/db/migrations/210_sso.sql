-- Single sign-on (OpenID Connect): Microsoft Entra ID, Okta and Google.
-- Identity providers prove who someone is; what they may do stays in `users` (role, team, organization).

-- A person's account at an identity provider, linked to one Bioverse user.
CREATE TABLE user_identities (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        text NOT NULL,                  -- entra | okta | google
    subject         text NOT NULL,                  -- the provider's stable user id (sub)
    tenant          text,                           -- Entra tenant id, Google hosted domain
    email           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz,
    UNIQUE (provider, subject)
);
CREATE INDEX user_identities_user_idx ON user_identities (user_id);

-- Signed-in browser sessions. Only a hash of the cookie value is stored.
CREATE TABLE auth_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash      text NOT NULL UNIQUE,
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        text NOT NULL,
    id_token_hint   text,                           -- for provider sign-out; never sent to the browser
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    user_agent      text
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions (user_id) WHERE revoked_at IS NULL;

-- In-flight sign-ins: state, nonce and PKCE verifier, single use, valid for ten minutes.
CREATE TABLE oidc_login_requests (
    state           text PRIMARY KEY,
    provider        text NOT NULL,
    nonce           text NOT NULL,
    code_verifier   text NOT NULL,
    next_path       text NOT NULL DEFAULT '/',
    created_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE users ADD COLUMN disabled boolean NOT NULL DEFAULT false;
