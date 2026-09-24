-- Online consultations with a verified clinician network.
-- Additive only: new tables. Nothing existing is changed.

-- Practitioner.qualification plus its VerificationResult, flattened: one row per license.
-- A clinician appears in the online directory, and may accept consultations, only while they hold at least
-- one `verified` license whose `expires_on` has not passed and none that is `suspended`.
-- Lookups against NPPES and state boards are SIMULATED in this demo; `verification_checks` records each step
-- with a label that says so.
CREATE TABLE practitioner_credentials (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id     uuid NOT NULL REFERENCES practitioners(id),
    license_number      text NOT NULL,
    jurisdiction        text NOT NULL,                  -- two-letter state or territory code
    license_type        text NOT NULL,                  -- MD, DO, NP, PA...
    board_certification text,
    npi                 text NOT NULL CHECK (npi ~ '^[0-9]{10}$'),
    issued_on           date,
    expires_on          date NOT NULL,
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'verified', 'expired', 'rejected', 'suspended')),
    source              text NOT NULL DEFAULT 'state_board' CHECK (source IN ('nppes', 'state_board')),
    verification_checks jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{"check", "result", "detail", "demo": true}]
    verified_by         uuid REFERENCES users(id),
    verified_at         timestamptz,
    decision_reason     text,                           -- why it was rejected or suspended
    notes               text,
    submitted_by        uuid REFERENCES users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (jurisdiction, license_number),
    CHECK (issued_on IS NULL OR issued_on < expires_on)
);
CREATE INDEX practitioner_credentials_practitioner_idx ON practitioner_credentials (practitioner_id);
CREATE INDEX practitioner_credentials_queue_idx ON practitioner_credentials (status, expires_on);

-- What a clinician offers online (PractitionerRole.availableTime + a price). Weekly hours are clinic-local.
CREATE TABLE consult_profiles (
    practitioner_id     uuid PRIMARY KEY REFERENCES practitioners(id),
    modes               text[] NOT NULL DEFAULT '{message}'
                        CHECK (cardinality(modes) > 0 AND modes <@ ARRAY['message', 'video', 'phone']),
    fee_cents           integer NOT NULL CHECK (fee_cents >= 0),
    years_in_practice   integer CHECK (years_in_practice BETWEEN 0 AND 70),
    bio                 text,
    hours               jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"mon": ["09:00", "17:00"], ...}
    slot_minutes        integer NOT NULL DEFAULT 30 CHECK (slot_minutes BETWEEN 10 AND 120),
    reply_hours         integer NOT NULL DEFAULT 24 CHECK (reply_hours BETWEEN 1 AND 72),
    accepting           boolean NOT NULL DEFAULT true,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Online consultation (FHIR Encounter with class "virtual", plus the request that started it).
CREATE TABLE consultations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    practitioner_id     uuid REFERENCES practitioners(id),     -- NULL until a clinician claims it
    requested_practitioner_id uuid REFERENCES practitioners(id), -- who the patient asked for, if anyone
    specialty           text NOT NULL,
    mode                text NOT NULL CHECK (mode IN ('message', 'video', 'phone')),
    reason              text NOT NULL,
    status              text NOT NULL DEFAULT 'requested'
                        CHECK (status IN ('requested', 'accepted', 'in_progress', 'completed', 'cancelled', 'declined')),
    scheduled_at        timestamptz,
    fee_cents           integer NOT NULL DEFAULT 0 CHECK (fee_cents >= 0),
    telehealth_consent  boolean NOT NULL CHECK (telehealth_consent),
    consented_at        timestamptz NOT NULL DEFAULT now(),
    intake_summary      jsonb,                                 -- pre-consult summary for the clinician
    intake_produced_by  text,
    intake_model        text,
    summary             text,                                  -- visit summary shown to the patient
    follow_up           text,
    decline_reason      text,
    cancel_reason       text,
    cancelled_by        text CHECK (cancelled_by IN ('patient', 'clinician', 'system')),
    flagged             boolean NOT NULL DEFAULT false,         -- a red flag was raised in this consult
    flag_reason         text,
    medication_request_id uuid REFERENCES medication_requests(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    accepted_at         timestamptz,
    started_at          timestamptz,
    completed_at        timestamptz,
    closed_at           timestamptz,                           -- cancelled or declined
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (mode = 'message' OR scheduled_at IS NOT NULL),
    CHECK (status = 'requested' OR status = 'cancelled' OR practitioner_id IS NOT NULL)
);
CREATE INDEX consultations_patient_idx ON consultations (patient_id, created_at DESC);
CREATE INDEX consultations_practitioner_idx ON consultations (practitioner_id, status);
CREATE INDEX consultations_pool_idx ON consultations (lower(specialty), created_at) WHERE practitioner_id IS NULL AND status = 'requested';

-- Communication within a consultation.
CREATE TABLE consultation_messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    seq                 bigserial NOT NULL UNIQUE,
    consultation_id     uuid NOT NULL REFERENCES consultations(id) ON DELETE CASCADE,
    patient_id          uuid NOT NULL REFERENCES patients(id),
    author_kind         text NOT NULL CHECK (author_kind IN ('patient', 'clinician', 'system')),
    author_user_id      uuid REFERENCES users(id),
    author_label        text NOT NULL,
    body                text NOT NULL,
    payload             jsonb,                                 -- e.g. {"kind": "emergency", ...}
    screen_level        text,                                  -- red-flag screen result for patient messages
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX consultation_messages_idx ON consultation_messages (consultation_id, seq);

-- A patient's rating after a completed consultation. One per consultation.
-- Comments are published only when the red-flag screen is clear.
CREATE TABLE consultation_ratings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    consultation_id     uuid NOT NULL UNIQUE REFERENCES consultations(id),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    practitioner_id     uuid NOT NULL REFERENCES practitioners(id),
    stars               integer NOT NULL CHECK (stars BETWEEN 1 AND 5),
    comment             text,
    comment_status      text NOT NULL DEFAULT 'none' CHECK (comment_status IN ('none', 'published', 'withheld')),
    moderation_note     text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX consultation_ratings_practitioner_idx ON consultation_ratings (practitioner_id);

-- WebRTC signaling for video consultations: offers, answers and ICE candidates, polled over REST.
-- Short-lived: the consult_housekeeping job deletes rows older than a day.
CREATE TABLE consultation_signals (
    seq                 bigserial PRIMARY KEY,
    consultation_id     uuid NOT NULL REFERENCES consultations(id) ON DELETE CASCADE,
    patient_id          uuid NOT NULL REFERENCES patients(id),
    sender_user_id      uuid NOT NULL REFERENCES users(id),
    sender_role         text NOT NULL CHECK (sender_role IN ('patient', 'clinician')),
    kind                text NOT NULL CHECK (kind IN ('join', 'offer', 'answer', 'ice', 'leave')),
    payload             jsonb,
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX consultation_signals_idx ON consultation_signals (consultation_id, seq);
