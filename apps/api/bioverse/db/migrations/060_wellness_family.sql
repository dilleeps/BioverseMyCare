-- Wellness and prevention, family and caregivers (modules 17 and 19).
-- Personal Health AI (module 20) reads the record and needs no tables of its own.

-- Sex assigned at birth drives sex-specific preventive screenings. Nullable: unknown means
-- sex-specific screenings are listed as "ask your doctor" rather than guessed.
ALTER TABLE patients ADD COLUMN IF NOT EXISTS sex_at_birth text
    CHECK (sex_at_birth IN ('female', 'male', 'intersex', 'unknown'));

-- Goal (FHIR Goal): a patient-set wellness target. Patient-reported, never clinical.
CREATE TABLE wellness_goals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    kind            text NOT NULL CHECK (kind IN ('steps', 'sleep_hours', 'active_minutes', 'fruit_veg_servings', 'custom')),
    title           text NOT NULL,
    unit            text NOT NULL,
    target          numeric NOT NULL CHECK (target > 0),
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    source          text NOT NULL DEFAULT 'patient' CHECK (source IN ('patient', 'assessment')),
    assessment_id   uuid,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX wellness_goals_patient_idx ON wellness_goals (patient_id, status);

-- Observation (patient-reported): one value per goal per day. Logging again replaces the day's value.
CREATE TABLE wellness_goal_entries (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id     uuid NOT NULL REFERENCES wellness_goals(id) ON DELETE CASCADE,
    patient_id  uuid NOT NULL REFERENCES patients(id),
    day         date NOT NULL,
    value       numeric NOT NULL CHECK (value >= 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (goal_id, day)
);

-- QuestionnaireResponse: the lifestyle assessment and what it suggested.
CREATE TABLE wellness_assessments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    version         text NOT NULL,
    answers         jsonb NOT NULL,
    suggestions     jsonb NOT NULL DEFAULT '[]'::jsonb,
    red_flag_level  text NOT NULL DEFAULT 'none',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX wellness_assessments_patient_idx ON wellness_assessments (patient_id, created_at DESC);

-- Which care gap a preventive rule owns, so syncing never duplicates a gap and can close it later.
CREATE TABLE prevention_gap_links (
    gap_id      uuid PRIMARY KEY REFERENCES care_gaps(id) ON DELETE CASCADE,
    patient_id  uuid NOT NULL REFERENCES patients(id),
    rule_id     text NOT NULL,
    ruleset     text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, rule_id)
);

-- RelatedPerson: someone connected to the patient who has a user account. WHAT they may see or do
-- lives in consents (scope 'caregiver_access', grantee = user_id); this row carries who they are.
CREATE TABLE related_persons (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    user_id         uuid NOT NULL REFERENCES users(id),
    relationship    text NOT NULL CHECK (relationship IN ('parent', 'child', 'spouse', 'other')),
    created_by      uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, user_id)
);
CREATE INDEX related_persons_user_idx ON related_persons (user_id);

-- Emergency contacts (Patient.contact). Not an access grant: contacts see nothing in Bioverse.
CREATE TABLE emergency_contacts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    name            text NOT NULL,
    relationship    text NOT NULL,
    phone           text NOT NULL,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX emergency_contacts_patient_idx ON emergency_contacts (patient_id);
