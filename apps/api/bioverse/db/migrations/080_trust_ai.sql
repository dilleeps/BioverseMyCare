-- Trust and Safety (module 21) and AI Platform governance (module 24).
-- Additive only: new tables, plus indexes on audit_events for compliance search.

-- ---------------------------------------------------------------------------------------------
-- Tamper evidence for the audit trail.
-- audit_events is append-only (trigger), so the chain lives beside it: one row per chained event,
-- hash = sha256(prev_hash || canonical event row). `seq` is the chain order (the order events were
-- chained), which is independent of id order so an event that commits late is still chained.
-- The chain itself is append-only as well.
CREATE TABLE audit_chain (
    seq         bigserial PRIMARY KEY,
    event_id    bigint NOT NULL UNIQUE REFERENCES audit_events(id),
    prev_hash   text NOT NULL,
    hash        text NOT NULL,
    chained_at  timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION audit_chain_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_chain is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_chain_no_update
    BEFORE UPDATE OR DELETE ON audit_chain
    FOR EACH ROW EXECUTE FUNCTION audit_chain_immutable();

-- Compliance search: time-ordered scans, AI-only views, action filters.
CREATE INDEX audit_events_occurred_idx ON audit_events (occurred_at DESC);
CREATE INDEX audit_events_agent_idx ON audit_events (agent, id DESC) WHERE agent IS NOT NULL;
CREATE INDEX audit_events_action_idx ON audit_events (action, id DESC);
CREATE INDEX audit_events_actor_idx ON audit_events (actor_user_id, id DESC);

-- ---------------------------------------------------------------------------------------------
-- Break-glass access: a clinician opens a patient's record outside their normal relationship,
-- with a stated reason. Short-lived; every grant is audited as a `break_glass` event.
CREATE TABLE break_glass_grants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    user_id     uuid NOT NULL REFERENCES users(id),
    reason      text NOT NULL CHECK (length(btrim(reason)) >= 15),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX break_glass_active_idx ON break_glass_grants (user_id, patient_id, expires_at);

-- ---------------------------------------------------------------------------------------------
-- Retention policy per organization and data category. This version only reports what a purge
-- WOULD remove (dry run); nothing is ever deleted by Bioverse yet.
CREATE TABLE retention_policies (
    organization_id uuid NOT NULL REFERENCES organizations(id),
    category        text NOT NULL CHECK (category IN ('conversations', 'messages', 'audit_events', 'documents')),
    retention_days  integer NOT NULL CHECK (retention_days BETWEEN 30 AND 36500),
    notes           text NOT NULL DEFAULT '',
    updated_at      timestamptz NOT NULL DEFAULT now(),
    updated_by      uuid REFERENCES users(id),
    PRIMARY KEY (organization_id, category)
);

-- ---------------------------------------------------------------------------------------------
-- Safety and privacy incidents (maps to FHIR AdverseEvent for AI safety incidents).
CREATE TABLE safety_incidents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    reported_by         uuid NOT NULL REFERENCES users(id),
    category            text NOT NULL CHECK (category IN ('ai_safety', 'privacy', 'security', 'clinical_safety')),
    severity            text NOT NULL CHECK (severity IN ('low', 'moderate', 'high', 'critical')),
    title               text NOT NULL,
    description         text NOT NULL,
    patient_id          uuid REFERENCES patients(id),
    linked_entity_type  text,
    linked_entity_id    text,
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'investigating', 'resolved')),
    assigned_to         uuid REFERENCES users(id),
    resolution          text,
    history             jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    resolved_at         timestamptz
);
CREATE INDEX safety_incidents_open_idx ON safety_incidents (organization_id, status, created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- AI Platform: agent registry (docs/03 "Agent governance"). The prompt version is not stored as
-- the truth: it is fingerprinted live from the prompt text. `ai_prompt_versions` records each
-- fingerprint the first time the platform observes it, so an event can be matched to the prompt
-- that was live at the time.
CREATE TABLE ai_agents (
    id                  text PRIMARY KEY,           -- slug, e.g. 'intake-agent'
    name                text NOT NULL,
    purpose             text NOT NULL,
    owner               text NOT NULL,
    model               text NOT NULL,              -- 'configured' model or 'none (deterministic)'
    status              text NOT NULL CHECK (status IN ('active', 'planned', 'retired')),
    permitted_tools     text[] NOT NULL DEFAULT '{}',
    human_review        text NOT NULL,
    prompt_refs         text[] NOT NULL DEFAULT '{}',  -- 'python.module:ATTRIBUTE' candidates
    audit_agents        text[] NOT NULL DEFAULT '{}',  -- audit_events.agent prefixes this agent writes
    position            integer NOT NULL DEFAULT 100,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_prompt_versions (
    agent_id        text NOT NULL REFERENCES ai_agents(id),
    prompt_hash     text NOT NULL,
    prompt_ref      text NOT NULL,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, prompt_hash)
);

-- Labelled evaluation cases and recorded runs.
CREATE TABLE eval_cases (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    suite               text NOT NULL CHECK (suite IN ('red_flags', 'intent_routing')),
    text                text NOT NULL,
    category            text NOT NULL,
    expected_level      text,
    expected_topic      text,
    expected_intent     text,
    expected_specialty  text,
    known_gap           boolean NOT NULL DEFAULT false,
    note                text,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_cases_suite_idx ON eval_cases (suite) WHERE active;

CREATE TABLE eval_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    suite               text NOT NULL,
    ruleset_version     text NOT NULL,
    total               integer NOT NULL,
    passed              integer NOT NULL,
    pass_rate           numeric(5, 4),
    regressions         integer NOT NULL,
    known_gap_failures  integer NOT NULL,
    sensitivity         numeric(5, 4),
    sensitivity_gated   numeric(5, 4),
    gate_passed         boolean NOT NULL,
    failures            jsonb NOT NULL DEFAULT '{}'::jsonb,
    run_by              uuid REFERENCES users(id),
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_runs_suite_idx ON eval_runs (suite, created_at DESC);

-- The clinical review matrix from docs/04, as data. Read-only in this version.
CREATE TABLE review_policies (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    position        integer NOT NULL,
    output_type     text NOT NULL UNIQUE,
    review_level    text NOT NULL CHECK (review_level IN ('none', 'staff', 'clinician', 'clinician_edit', 'escalate', 'configurable', 'tiered')),
    default_policy  text NOT NULL,
    rationale       text NOT NULL
);
