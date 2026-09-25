-- Directory group -> role mapping for single sign-on (bioverse/sso/plugins/group_mapping.py).
-- A rule matches a claim in the verified ID token (Entra/Okta `groups`, Entra app `roles`, Google `hd`)
-- and says which role, team and specialty a person gets. Patients are never created from a group.

CREATE TABLE sign_in_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider        text CHECK (provider IN ('entra', 'okta', 'google')),   -- NULL: any provider
    claim           text NOT NULL DEFAULT 'groups',
    match_value     text NOT NULL,
    role            text NOT NULL CHECK (role IN ('admin', 'staff', 'clinician', 'student')),
    team            text CHECK (team IN ('front_desk', 'pharmacy')),
    specialty       text,                                                   -- default for clinicians
    priority        integer NOT NULL DEFAULT 100,                           -- lower is checked first
    label           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (team IS NULL OR role = 'staff'),
    CHECK (role <> 'clinician' OR specialty IS NOT NULL)
);
CREATE INDEX sign_in_rules_org_idx ON sign_in_rules (organization_id, priority);

-- Per organization: create accounts on first sign-in (just in time) and keep staff/admin roles in sync.
-- Both off until an administrator turns them on.
CREATE TABLE sign_in_rule_settings (
    organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    jit_enabled     boolean NOT NULL DEFAULT false,
    sync_on_sign_in boolean NOT NULL DEFAULT false,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
