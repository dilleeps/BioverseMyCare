-- Clinician availability: weekly working hours and time off, from which bookable `slots` are generated.
-- Additive only. Existing slots (seeded, imported or added by hand) default to source 'manual' and are
-- never changed or removed by the generator; it only manages the free slots it created itself.

-- Where the generator keeps a practitioner's hours: the time zone the hours are written in, and how far
-- ahead to keep slots open. No row means the clinic time zone (BIOVERSE_CLINIC_TZ) and the default horizon.
CREATE TABLE availability_settings (
    practitioner_id uuid PRIMARY KEY REFERENCES practitioners(id),
    timezone        text NOT NULL,
    horizon_days    integer NOT NULL DEFAULT 28 CHECK (horizon_days BETWEEN 7 AND 90),
    updated_by      uuid REFERENCES users(id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- One working window on one weekday (PractitionerRole.availableTime, plus the slot length and place).
-- weekday: 0 = Monday ... 6 = Sunday. Times are wall-clock in the practitioner's time zone.
CREATE TABLE availability_windows (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    weekday         smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time      time NOT NULL,
    end_time        time NOT NULL,
    mode            text NOT NULL DEFAULT 'in_person' CHECK (mode IN ('in_person', 'video')),
    location        text,
    slot_minutes    integer NOT NULL DEFAULT 20 CHECK (slot_minutes BETWEEN 5 AND 120),
    effective_from  date,
    effective_until date,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (end_time > start_time),
    CHECK (effective_from IS NULL OR effective_until IS NULL OR effective_until >= effective_from)
);
CREATE INDEX availability_windows_practitioner_idx ON availability_windows (practitioner_id, weekday);

-- Whole days a practitioner is away (vacation, conference). No new slots are opened on these days and
-- free generated ones are withdrawn; booked appointments are kept for the practice to rebook.
CREATE TABLE availability_time_off (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    starts_on       date NOT NULL,
    ends_on         date NOT NULL,
    reason          text,
    created_by      uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_on >= starts_on)
);
CREATE INDEX availability_time_off_practitioner_idx ON availability_time_off (practitioner_id, ends_on);

-- Where a slot came from. 'template' slots are owned by the generator; everything else is left alone.
ALTER TABLE slots ADD COLUMN source text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'template'));
ALTER TABLE slots ADD COLUMN location text;
CREATE INDEX slots_template_idx ON slots (practitioner_id, starts_at) WHERE source = 'template';
