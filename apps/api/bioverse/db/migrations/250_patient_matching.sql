-- Master patient index: find the existing record before creating a new one, and merge duplicates.
--
-- Contact details live on the patient record too (not only on the login), so records created without a
-- login (HL7 import, front desk, CSV) can still be matched on them later.
ALTER TABLE patients ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS phone text;
-- A merged (retired) record is kept for audit and legal reasons and points at the record that survived.
-- Lists and searches show only records WHERE merged_into IS NULL.
ALTER TABLE patients ADD COLUMN IF NOT EXISTS merged_into uuid REFERENCES patients(id);
ALTER TABLE patients ADD COLUMN IF NOT EXISTS merged_at timestamptz;
ALTER TABLE patients ADD CONSTRAINT patients_not_merged_into_self CHECK (merged_into IS DISTINCT FROM id);

-- Candidate pre-filters: matching never scans the whole organization.
CREATE INDEX IF NOT EXISTS patients_org_birth_date_idx ON patients (organization_id, birth_date) WHERE merged_into IS NULL;
CREATE INDEX IF NOT EXISTS patients_org_email_idx ON patients (organization_id, lower(email)) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS patients_org_phone_idx
    ON patients (organization_id, right(regexp_replace(phone, '\D', '', 'g'), 10)) WHERE phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS users_lower_email_idx ON users (lower(email));

-- Pairs of records that may be the same person, waiting for a person to decide.
CREATE TABLE match_reviews (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    patient_a       uuid NOT NULL REFERENCES patients(id),   -- the record that already existed
    patient_b       uuid NOT NULL REFERENCES patients(id),   -- the newer record
    level           text NOT NULL CHECK (level IN ('certain', 'probable', 'possible')),
    score           integer NOT NULL,
    reasons         jsonb NOT NULL DEFAULT '[]',
    source          text NOT NULL DEFAULT 'registration',   -- what created the newer record: admin, invite, self, import, hl7...
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'merged', 'not_duplicate')),
    survivor        uuid REFERENCES patients(id),
    merge_report    jsonb,
    decided_by      uuid REFERENCES users(id),
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (patient_a <> patient_b)
);
-- One open review per pair, whichever way round.
CREATE UNIQUE INDEX match_reviews_one_open_pair
    ON match_reviews (LEAST(patient_a, patient_b), GREATEST(patient_a, patient_b)) WHERE status = 'open';
CREATE INDEX match_reviews_org_status_idx ON match_reviews (organization_id, status, created_at DESC);
