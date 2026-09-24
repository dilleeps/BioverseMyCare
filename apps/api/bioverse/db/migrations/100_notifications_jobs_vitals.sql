-- Platform, round two: notifications, scheduled jobs, and vital signs in the shared Observation table.

-- Notification (FHIR CommunicationRequest, simplified). One row per recipient and message.
-- In-app delivery is the row itself; other channels are attempted by the dispatch job.
CREATE TABLE notifications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    patient_id      uuid REFERENCES patients(id),
    kind            text NOT NULL,                 -- e.g. medication_reminder, vital_alert, appointment_reminder
    title           text NOT NULL,
    body            text NOT NULL DEFAULT '',
    link            text,
    priority        text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    channels        text[] NOT NULL DEFAULT '{in_app}',
    due_at          timestamptz NOT NULL DEFAULT now(),
    dedupe_key      text,                          -- same key for the same user is only ever created once
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'cancelled')),
    delivery        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- per channel: {"email": {"status": "sent", "at": ...}}
    created_by      text NOT NULL DEFAULT 'system',
    created_at      timestamptz NOT NULL DEFAULT now(),
    sent_at         timestamptz,
    read_at         timestamptz,
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX notifications_inbox_idx ON notifications (user_id, due_at DESC) WHERE status <> 'cancelled';
CREATE INDEX notifications_due_idx ON notifications (due_at) WHERE status = 'pending';

-- Per-user delivery preferences. Missing row = defaults (in-app only, no quiet hours).
CREATE TABLE notification_preferences (
    user_id         uuid PRIMARY KEY REFERENCES users(id),
    email           text,
    phone           text,
    channels        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"medication_reminder": ["in_app", "push"], ...}
    quiet_start     time,
    quiet_end       time,
    timezone        text NOT NULL DEFAULT 'America/New_York',
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Scheduled jobs: one row per run, so the runner knows what is due and admins can see history.
CREATE TABLE job_runs (
    id              bigserial PRIMARY KEY,
    name            text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX job_runs_name_idx ON job_runs (name, started_at DESC);

-- Vital signs and patient-generated data live in `observations`, like lab results, coded with LOINC
-- (see bioverse/vitals_codes.py). These columns say where a value came from and group paired values.
ALTER TABLE observations ADD COLUMN category text NOT NULL DEFAULT 'laboratory'
    CHECK (category IN ('laboratory', 'vital-signs', 'activity', 'survey'));
ALTER TABLE observations ADD COLUMN source text NOT NULL DEFAULT 'lab'
    CHECK (source IN ('lab', 'manual', 'device', 'photo', 'import', 'clinic'));
ALTER TABLE observations ADD COLUMN device text;          -- make/model or integration name
ALTER TABLE observations ADD COLUMN panel_id uuid;        -- groups systolic + diastolic, etc.
ALTER TABLE observations ADD COLUMN note text;
CREATE INDEX observations_category_idx ON observations (patient_id, category, effective_at DESC);

-- Critical flags (HH/LL) and "abnormal" (A) for values without a direction.
ALTER TABLE observations DROP CONSTRAINT observations_interpretation_check;
ALTER TABLE observations ADD CONSTRAINT observations_interpretation_check
    CHECK (interpretation IN ('H', 'L', 'N', 'HH', 'LL', 'A'));
