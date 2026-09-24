-- Platform: an organization admin role, and a label marking who appears in the demo identity switcher.

ALTER TABLE users DROP CONSTRAINT users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('patient', 'clinician', 'staff', 'admin'));

-- Non-null means "offer this user in the demo switcher". Remove with real authentication.
ALTER TABLE users ADD COLUMN demo_label text;
ALTER TABLE users ADD COLUMN demo_order integer NOT NULL DEFAULT 100;

-- Review queue: modules add their own kinds (refill requests, referrals, uploaded results...).
-- A kind the core does not know gets "acknowledge" plus a link back to the owning module.
ALTER TABLE review_items DROP CONSTRAINT review_items_kind_check;
ALTER TABLE review_items ADD COLUMN link text;

-- Audit events name the patient they concern, so a patient can see who accessed their record.
ALTER TABLE audit_events ADD COLUMN patient_id uuid REFERENCES patients(id);
CREATE INDEX audit_events_patient_idx ON audit_events (patient_id, occurred_at DESC) WHERE patient_id IS NOT NULL;

-- Consent (FHIR Consent). One row per patient, scope and grantee. See bioverse/consent.py for scopes.
CREATE TABLE consents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    scope       text NOT NULL,
    grantee     text NOT NULL DEFAULT '',   -- '' for scopes without a grantee; a user id for caregiver access
    status      text NOT NULL CHECK (status IN ('granted', 'denied', 'revoked')),
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    expires_at  timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  uuid REFERENCES users(id),
    UNIQUE (patient_id, scope, grantee)
);

-- Databases seeded before this migration already have these users.
UPDATE users SET demo_label = 'Patient', demo_order = 10 WHERE email = 'maya@example.com';
UPDATE users SET demo_label = 'Cardiology', demo_order = 20 WHERE email = 'a.okafor@northside.example';
