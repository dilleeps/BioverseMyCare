-- Vital signs and connected devices: home readings, devices, clinician thresholds, alerts, monitoring plans.
-- Readings themselves live in the shared `observations` table (category vital-signs / activity).

-- Device (FHIR Device). A patient's connected health device. Pairing in this demo is simulated.
CREATE TABLE devices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    kind            text NOT NULL CHECK (kind IN ('bp_cuff', 'glucometer', 'scale', 'pulse_oximeter', 'thermometer',
                                                  'wearable')),
    vendor          text,
    model           text,
    integration     text NOT NULL CHECK (integration IN ('bluetooth', 'apple_health', 'health_connect', 'fitbit',
                                                         'manual_import')),
    serial          text,
    status          text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'disconnected')),
    simulated       boolean NOT NULL DEFAULT true,     -- demo pairing: no real device is talking to us
    last_sync       timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    disconnected_at timestamptz
);
CREATE INDEX devices_patient_idx ON devices (patient_id, status);

-- Which device sent a reading, and the circumstances of a glucose reading.
ALTER TABLE observations ADD COLUMN device_id uuid REFERENCES devices(id) ON DELETE SET NULL;
ALTER TABLE observations ADD COLUMN measurement_context text
    CHECK (measurement_context IN ('fasting', 'before_meal', 'after_meal', 'bedtime', 'random'));

-- Per-patient alert thresholds set by a clinician. Missing row = defaults from bioverse/vitals_codes.py.
-- `code` is a vitals_codes key (bp_systolic, spo2...), or 'weight_gain_3d' (high = kg gained over 3 days).
CREATE TABLE vital_alert_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    code            text NOT NULL,
    low             numeric,
    high            numeric,
    critical_low    numeric,
    critical_high   numeric,
    note            text,
    set_by          uuid REFERENCES practitioners(id),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, code)
);

-- Home monitoring prescribed by a clinician (FHIR ServiceRequest for home observation), e.g. BP twice daily.
CREATE TABLE vital_monitoring_plans (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    measure         text NOT NULL CHECK (measure IN ('bp', 'heart_rate', 'spo2', 'temperature', 'glucose', 'weight')),
    times           time[] NOT NULL,                   -- clinic-local times of day
    start_on        date NOT NULL,
    end_on          date NOT NULL,
    instructions    text,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'stopped')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    stopped_at      timestamptz,
    stopped_by      uuid REFERENCES users(id),
    CHECK (end_on >= start_on)
);
CREATE INDEX vital_monitoring_plans_patient_idx ON vital_monitoring_plans (patient_id, status);

-- Abnormal home readings (FHIR DetectedIssue). One open alert per patient, kind and measure: further
-- readings attach to it (reading_count) instead of raising another, so a bad day is one item, not ten.
CREATE TABLE vital_alerts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    measure         text NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('critical_high', 'critical_low', 'sustained_high', 'sustained_low',
                                                  'weight_gain')),
    severity        text NOT NULL CHECK (severity IN ('critical', 'warning')),
    title           text NOT NULL,
    detail          text NOT NULL,
    observation_id  uuid REFERENCES observations(id) ON DELETE SET NULL,
    reading_count   integer NOT NULL DEFAULT 1,
    last_reading_at timestamptz NOT NULL,
    practitioner_id uuid REFERENCES practitioners(id),
    review_item_id  uuid REFERENCES review_items(id),
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged')),
    acknowledged_by uuid REFERENCES users(id),
    acknowledged_at timestamptz,
    ack_note        text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX vital_alerts_one_open_idx ON vital_alerts (patient_id, measure, kind) WHERE status = 'open';
CREATE INDEX vital_alerts_patient_idx ON vital_alerts (patient_id, created_at DESC);
