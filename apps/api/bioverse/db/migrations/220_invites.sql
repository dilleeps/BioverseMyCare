-- Patient invites, email one-time codes and a development outbox.
-- A clinic invites a patient by email; the patient opens the link, confirms their date of birth and signs in
-- with Google (or another configured provider) or a code sent by email. Only hashes of tokens and codes are stored.

CREATE TABLE patient_invites (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    token_hash          text NOT NULL UNIQUE,               -- SHA-256 of the link token; the token is never stored
    email               text NOT NULL,                      -- where the invite was sent
    name                text NOT NULL,
    birth_date          date NOT NULL,                      -- the identity check on the join page
    mrn                 text,                               -- optional medical record number
    mrn_system          text,
    message             text,                               -- personal note from the inviter (no clinical detail)
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    expires_at          timestamptz NOT NULL,
    invited_by          uuid REFERENCES users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    sent_at             timestamptz,
    send_count          integer NOT NULL DEFAULT 0,
    delivery            jsonb NOT NULL DEFAULT '{}'::jsonb, -- last email attempt: {"status": ..., "detail": ...}
    dob_attempts        integer NOT NULL DEFAULT 0,         -- wrong dates of birth since the last (re)send
    locked_at           timestamptz,                        -- set after too many wrong dates of birth
    dob_confirmed_at    timestamptz,                        -- the date of birth matched; sign-in must follow soon
    terms_accepted_at   timestamptz,
    accepted_at         timestamptz,
    accepted_user_id    uuid REFERENCES users(id),
    accepted_patient_id uuid REFERENCES patients(id),
    accepted_email      text,                               -- the verified email they signed in with
    accepted_via        text,                               -- google | entra | okta | email
    revoked_at          timestamptz,
    revoked_by          uuid REFERENCES users(id)
);
CREATE INDEX patient_invites_org_idx ON patient_invites (organization_id, created_at DESC);
CREATE INDEX patient_invites_email_idx ON patient_invites (lower(email)) WHERE status = 'pending';

-- One-time sign-in codes sent by email. Single use, short-lived, a few tries each.
CREATE TABLE email_signin_codes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL,                          -- lower-cased
    salt            text NOT NULL,
    code_hash       text NOT NULL,                          -- SHA-256 of salt + code
    purpose         text NOT NULL DEFAULT 'sign_in' CHECK (purpose IN ('sign_in', 'invite', 'register')),
    invite_id       uuid REFERENCES patient_invites(id) ON DELETE CASCADE,
    registration    jsonb,                                  -- self-registration: name and date of birth
    delivered       boolean NOT NULL DEFAULT false,         -- false: nobody can sign in with this email
    attempts        integer NOT NULL DEFAULT 0,
    requested_ip    text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    used_at         timestamptz
);
CREATE INDEX email_signin_codes_email_idx ON email_signin_codes (email, created_at DESC);
CREATE INDEX email_signin_codes_ip_idx ON email_signin_codes (requested_ip, created_at DESC);

-- Email that a demo or development deployment would have sent. Written only while demo sign-in is allowed,
-- so people can try invites and email codes without a mail server. Never written in production (sso) mode.
CREATE TABLE dev_outbox (
    id          bigserial PRIMARY KEY,
    channel     text NOT NULL DEFAULT 'email',
    to_address  text NOT NULL,
    subject     text NOT NULL,
    body        text NOT NULL,
    link        text,
    status      text NOT NULL,                              -- the real channel's result: sent | skipped | failed
    detail      text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dev_outbox_to_idx ON dev_outbox (lower(to_address), created_at DESC);
