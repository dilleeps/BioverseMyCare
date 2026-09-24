-- Front-door access: display preferences (senior mode, text size, contrast, motion, read-aloud)
-- and skin photos a patient chose to send to their care team.
-- Additive only: new tables, no changes to existing columns or constraints.

-- Per-user display preferences. Any role may have them; they follow the person across devices.
CREATE TABLE ui_preferences (
    user_id         uuid PRIMARY KEY REFERENCES users(id),
    senior_mode     boolean NOT NULL DEFAULT false,
    text_scale      numeric(3, 2) NOT NULL DEFAULT 1.00 CHECK (text_scale >= 1.00 AND text_scale <= 1.60),
    high_contrast   boolean NOT NULL DEFAULT false,
    reduce_motion   boolean NOT NULL DEFAULT false,
    read_aloud      boolean NOT NULL DEFAULT false,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- A skin photo the patient explicitly consented to send (FHIR Media + a Communication to the care team).
-- Photos asked about but not sent are never stored. The review item links to the clinician view.
CREATE TABLE skin_photo_submissions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    submitted_by    uuid NOT NULL REFERENCES users(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    media_type      text NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'image/webp')),
    image           bytea NOT NULL,
    size_bytes      integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
    sha256          text NOT NULL,
    note            text,
    checklist       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- ids the patient ticked; [] means "none of these"
    level           text NOT NULL DEFAULT 'routine' CHECK (level IN ('routine', 'urgent')),
    consented_at    timestamptz NOT NULL,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replied', 'resolved')),
    reply           text,
    replied_by      uuid REFERENCES users(id),
    replied_at      timestamptz,
    review_item_id  uuid REFERENCES review_items(id),
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX skin_photo_submissions_patient_idx ON skin_photo_submissions (patient_id, created_at DESC);
CREATE INDEX skin_photo_submissions_practitioner_idx ON skin_photo_submissions (practitioner_id, status);
