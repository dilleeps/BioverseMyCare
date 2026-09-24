-- Bioverse initial schema.
-- Table names follow the FHIR resource each one models (see docs/01-architecture.md).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Organization (FHIR Organization)
CREATE TABLE organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Everyone who signs in. Role drives access control.
CREATE TABLE users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role            text NOT NULL CHECK (role IN ('patient', 'clinician', 'staff')),
    display_name    text NOT NULL,
    email           text NOT NULL UNIQUE,
    organization_id uuid REFERENCES organizations(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Practitioner + PractitionerRole, flattened.
CREATE TABLE practitioners (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid UNIQUE REFERENCES users(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    name                text NOT NULL,
    specialty           text NOT NULL,
    location_name       text NOT NULL,
    distance_km         numeric(5, 1) NOT NULL DEFAULT 0,
    languages           text[] NOT NULL DEFAULT '{English}',
    accessibility       text[] NOT NULL DEFAULT '{}',
    accepted_plans      text[] NOT NULL DEFAULT '{}',
    offers_telehealth   boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX practitioners_specialty_idx ON practitioners (lower(specialty));

-- Patient
CREATE TABLE patients (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid UNIQUE REFERENCES users(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    name                text NOT NULL,
    birth_date          date NOT NULL,
    pronouns            text,
    preferred_language  text NOT NULL DEFAULT 'English',
    insurance_plan      text,
    allergies           text[] NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Slot (bookable availability)
CREATE TABLE slots (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    starts_at       timestamptz NOT NULL,
    duration_min    integer NOT NULL DEFAULT 20,
    mode            text NOT NULL DEFAULT 'in_person' CHECK (mode IN ('in_person', 'video')),
    status          text NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'booked')),
    UNIQUE (practitioner_id, starts_at)
);
CREATE INDEX slots_free_idx ON slots (practitioner_id, starts_at) WHERE status = 'free';

-- Conversation with the front door, and its messages (Communication)
CREATE TABLE conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'escalated', 'closed')),
    -- Tracks where the orchestrator is: awaiting a safety-check answer, or free conversation.
    state       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Messages written in one transaction share now(); seq is the true conversation order.
    seq             bigserial NOT NULL UNIQUE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL CHECK (role IN ('user', 'assistant')),
    content         text NOT NULL,
    -- Structured hybrid-UI payload rendered inline (safety check, care options, emergency card).
    payload         jsonb,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, seq);

-- Intake (QuestionnaireResponse + Condition summary)
CREATE TABLE intakes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     uuid REFERENCES conversations(id),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    chief_complaint     text NOT NULL,
    urgency             text NOT NULL CHECK (urgency IN ('emergency', 'urgent', 'routine', 'self_care')),
    red_flags           text[] NOT NULL DEFAULT '{}',
    specialty           text,
    patient_summary     text NOT NULL,
    clinician_summary   text NOT NULL,
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'routed', 'escalated', 'closed')),
    produced_by         text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Appointment
CREATE TABLE appointments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    slot_id         uuid NOT NULL UNIQUE REFERENCES slots(id),
    intake_id       uuid REFERENCES intakes(id),
    reason          text,
    status          text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled', 'fulfilled')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Encounter (past visits)
CREATE TABLE encounters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid REFERENCES practitioners(id),
    occurred_at     timestamptz NOT NULL,
    kind            text NOT NULL,
    summary         text NOT NULL
);

-- Immunization
CREATE TABLE immunizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    vaccine     text NOT NULL,
    location    text,
    occurred_at timestamptz NOT NULL
);

-- DiagnosticReport and its Observations (coded with LOINC)
CREATE TABLE diagnostic_reports (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    name                text NOT NULL,
    lab_name            text NOT NULL,
    collected_at        timestamptz NOT NULL,
    responsible_practitioner_id uuid REFERENCES practitioners(id)
);

CREATE TABLE observations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    report_id       uuid REFERENCES diagnostic_reports(id) ON DELETE CASCADE,
    loinc_code      text NOT NULL,
    display         text NOT NULL,
    value           numeric NOT NULL,
    unit            text NOT NULL,
    ref_low         numeric,
    ref_high        numeric,
    interpretation  text NOT NULL CHECK (interpretation IN ('H', 'L', 'N')),
    effective_at    timestamptz NOT NULL
);
CREATE INDEX observations_trend_idx ON observations (patient_id, loinc_code, effective_at);

-- AI-drafted, clinician-reviewed explanation of a report.
-- Patients only ever see `final_text`, and only once status = 'approved'.
CREATE TABLE result_explanations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id       uuid NOT NULL UNIQUE REFERENCES diagnostic_reports(id) ON DELETE CASCADE,
    draft_text      text NOT NULL,
    final_text      text,
    questions       jsonb NOT NULL DEFAULT '[]'::jsonb,
    status          text NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review', 'approved', 'rejected')),
    produced_by     text NOT NULL,
    reviewed_by     uuid REFERENCES users(id),
    reviewed_at     timestamptz
);

-- CarePlan and its Tasks
CREATE TABLE care_plans (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    title           text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'revoked'))
);

CREATE TABLE care_plan_tasks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    care_plan_id    uuid NOT NULL REFERENCES care_plans(id) ON DELETE CASCADE,
    position        integer NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('lab', 'medication', 'appointment', 'referral', 'checkin', 'lifestyle')),
    title           text NOT NULL,
    detail          text,
    specialty       text,
    due_on          date,
    status          text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'done')),
    completed_at    timestamptz
);

-- Preventive-care gaps surfaced in My Health Story.
CREATE TABLE care_gaps (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    title       text NOT NULL,
    detail      text NOT NULL,
    specialty   text,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed'))
);

-- Clinician review queue: the human-in-the-loop gate (docs/decisions/004).
CREATE TABLE review_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL CHECK (kind IN ('result_explanation', 'agent_escalation', 'red_flag')),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    ref_id          uuid,
    title           text NOT NULL,
    body            text NOT NULL,
    priority        text NOT NULL DEFAULT 'routine' CHECK (priority IN ('urgent', 'routine')),
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    resolution      text,
    resolved_by     uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz
);
CREATE INDEX review_items_open_idx ON review_items (practitioner_id, created_at) WHERE status = 'open';

-- Doctor Agent configuration, one per clinician.
CREATE TABLE doctor_agent_configs (
    practitioner_id         uuid PRIMARY KEY REFERENCES practitioners(id),
    active                  boolean NOT NULL DEFAULT true,
    previsit_questions      jsonb NOT NULL DEFAULT '[]'::jsonb,
    followup_protocol       jsonb NOT NULL DEFAULT '[]'::jsonb,
    escalation_rules        jsonb NOT NULL DEFAULT '[]'::jsonb,
    approval_requirements   jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- Immutable audit trail (AuditEvent + Provenance). Append-only.
CREATE TABLE audit_events (
    id              bigserial PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    actor_user_id   uuid REFERENCES users(id),
    actor_role      text,
    agent           text,
    model           text,
    action          text NOT NULL,
    entity_type     text NOT NULL,
    entity_id       uuid,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_events_entity_idx ON audit_events (entity_type, entity_id);

CREATE FUNCTION audit_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
