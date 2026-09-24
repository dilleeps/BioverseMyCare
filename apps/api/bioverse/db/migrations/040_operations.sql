-- Hospital operations, organization configuration and care pathways.
-- Additive only: new tables, plus nullable columns on practitioners and care_plans.

-- Organization profile and branding (one row per Organization).
CREATE TABLE organization_profiles (
    organization_id uuid PRIMARY KEY REFERENCES organizations(id),
    display_name    text NOT NULL,
    accent_color    text NOT NULL DEFAULT '#0e6b60',
    support_phone   text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    updated_by      uuid REFERENCES users(id)
);

-- Location (FHIR Location): a building, or the virtual "location" of video visits.
CREATE TABLE locations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name            text NOT NULL,
    kind            text NOT NULL DEFAULT 'physical' CHECK (kind IN ('physical', 'virtual')),
    address         text,
    phone           text,
    step_free       boolean NOT NULL DEFAULT false,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);

-- Department (a FHIR Organization that is partOf the tenant; kept in its own table).
-- hours: {"mon": {"open": "08:00", "close": "17:00"}, ..., "sun": null}
CREATE TABLE departments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name            text NOT NULL,
    specialty       text NOT NULL,
    location_id     uuid REFERENCES locations(id),
    hours           jsonb NOT NULL DEFAULT '{}'::jsonb,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);

-- Services and appointment types (FHIR HealthcareService).
CREATE TABLE healthcare_services (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    department_id   uuid NOT NULL REFERENCES departments(id),
    name            text NOT NULL,
    duration_min    integer NOT NULL CHECK (duration_min BETWEEN 5 AND 240),
    mode            text NOT NULL CHECK (mode IN ('in_person', 'video', 'either')),
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (department_id, name)
);

-- Care-pathway templates (FHIR PlanDefinition) and their ordered task templates (PlanDefinition.action).
CREATE TABLE plan_definitions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name            text NOT NULL,
    specialty       text NOT NULL,
    description     text,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);

CREATE TABLE plan_definition_actions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_definition_id  uuid NOT NULL REFERENCES plan_definitions(id) ON DELETE CASCADE,
    position            integer NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('lab', 'medication', 'appointment', 'referral', 'checkin', 'lifestyle')),
    title               text NOT NULL,
    detail              text,
    specialty           text,
    due_offset_days     integer NOT NULL DEFAULT 0 CHECK (due_offset_days BETWEEN 0 AND 730)
);
CREATE INDEX plan_definition_actions_idx ON plan_definition_actions (plan_definition_id, position);

-- Provider directory: link a practitioner to a structured location (location_name stays the display value).
ALTER TABLE practitioners ADD COLUMN location_id uuid REFERENCES locations(id);

-- Care plans remember the pathway they were started from and when they were completed.
ALTER TABLE care_plans ADD COLUMN plan_definition_id uuid REFERENCES plan_definitions(id);
ALTER TABLE care_plans ADD COLUMN completed_at timestamptz;

-- Operations and analytics read these ranges constantly.
CREATE INDEX IF NOT EXISTS slots_starts_at_idx ON slots (starts_at);
CREATE INDEX IF NOT EXISTS intakes_created_at_idx ON intakes (created_at);
CREATE INDEX IF NOT EXISTS appointments_intake_idx ON appointments (intake_id);
