-- Health companion (proactive layer): reminders, dose records, check-ins and the patient's choices.
-- Additive only. Notifications themselves live in the shared `notifications` table (bioverse/notify.py).

-- What the companion may do for one patient. No row means the defaults below.
CREATE TABLE companion_settings (
    patient_id              uuid PRIMARY KEY REFERENCES patients(id),
    medication_reminders    boolean NOT NULL DEFAULT true,
    appointment_reminders   boolean NOT NULL DEFAULT true,
    checkins                boolean NOT NULL DEFAULT true,
    results_ready           boolean NOT NULL DEFAULT true,
    care_gap_nudges         boolean NOT NULL DEFAULT true,
    daily_brief             boolean NOT NULL DEFAULT false,      -- opt-in
    daily_brief_time        time NOT NULL DEFAULT '07:30',
    -- Preferred clock time for each part of the day: {"morning": "08:00", "evening": "21:00"}.
    dose_times              jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Per-prescription overrides: {"<medication_request id>": ["07:00", "19:00"]}.
    medication_times        jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_by              uuid REFERENCES users(id),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- MedicationAdministration, patient-reported: one row per scheduled dose the patient marked.
-- A scheduled dose with no row is "not recorded" (missed once its day is over).
CREATE TABLE medication_doses (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    medication_request_id   uuid NOT NULL REFERENCES medication_requests(id),
    scheduled_at            timestamptz NOT NULL,         -- the dose time (instant)
    scheduled_local         timestamp NOT NULL,           -- the dose time on the patient's clock, as reminded
    status                  text NOT NULL CHECK (status IN ('taken', 'skipped')),   -- FHIR: completed | not-done
    reason                  text CHECK (reason IN ('forgot', 'side_effects', 'ran_out', 'felt_unwell',
                                                   'away_from_home', 'other')),
    recorded_by             uuid REFERENCES users(id),
    recorded_at             timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (medication_request_id, scheduled_local),
    CHECK (status = 'skipped' OR reason IS NULL)
);
CREATE INDEX medication_doses_patient_idx ON medication_doses (patient_id, scheduled_at DESC);

-- Follow-up check-ins (a small QuestionnaireResponse): the day after a visit, three days into a new medicine.
CREATE TABLE companion_checkins (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    kind                text NOT NULL CHECK (kind IN ('post_visit', 'new_medication')),
    ref_id              uuid NOT NULL,                  -- encounters.id or medication_requests.id
    subject             text NOT NULL,                  -- "your visit with Dr. Okafor", "Atorvastatin 20 mg"
    practitioner_id     uuid REFERENCES practitioners(id),   -- who hears about it if it needs attention
    prompt              text NOT NULL,                  -- what the patient is asked (template or AI-phrased)
    produced_by         text NOT NULL,                  -- 'companion/rules' or 'companion/claude'
    model               text,
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'expired')),
    response            text CHECK (response IN ('better', 'same', 'worse')),
    note                text,
    screen_level        text CHECK (screen_level IN ('none', 'screen', 'emergency', 'crisis')),
    screen_flags        text[] NOT NULL DEFAULT '{}',
    escalation          text CHECK (escalation IN ('urgent', 'routine')),
    escalation_reason   text,
    review_item_id      uuid REFERENCES review_items(id),
    due_at              timestamptz NOT NULL,
    answered_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, kind, ref_id)
);
CREATE INDEX companion_checkins_patient_idx ON companion_checkins (patient_id, due_at DESC);
