-- Appointment and Visit Navigator (module 4) and Referral Manager (module 11).
-- Additive only: new tables, no changes to existing columns or constraints.

-- Location (FHIR Location): wayfinding for each place named in practitioners.location_name.
-- A virtual location ("Video visit") carries a join link and tech-check guidance instead of an address.
CREATE TABLE locations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name            text NOT NULL,              -- matches practitioners.location_name
    mode            text NOT NULL DEFAULT 'physical' CHECK (mode IN ('physical', 'virtual')),
    address         text,
    phone           text,
    parking         text,
    directions      text,
    accessibility   text[] NOT NULL DEFAULT '{}',
    join_url        text,
    tech_check      text[] NOT NULL DEFAULT '{}',
    UNIQUE (organization_id, name)
);

-- Pre-visit checklist (FHIR Task, one row per item). Generated from templates when a visit is first
-- shown; the patient ticks items off and the state persists.
CREATE TABLE appointment_checklist_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id  uuid NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    item_key        text NOT NULL,
    position        integer NOT NULL,
    label           text NOT NULL,
    detail          text,
    done_at         timestamptz,
    done_by         uuid REFERENCES users(id),
    UNIQUE (appointment_id, item_key)
);
CREATE INDEX appointment_checklist_patient_idx ON appointment_checklist_items (patient_id);

-- Questions the patient wants to ask at a visit (QuestionnaireResponse-like, free text).
CREATE TABLE appointment_questions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id  uuid NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    text            text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX appointment_questions_appt_idx ON appointment_questions (appointment_id, created_at);

-- Day-of-visit status (FHIR Encounter.status for a booked Appointment). No row means "booked".
-- appointments.status keeps its meaning: it becomes 'fulfilled' when the visit is completed.
CREATE TABLE appointment_encounters (
    appointment_id  uuid PRIMARY KEY REFERENCES appointments(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    status          text NOT NULL CHECK (status IN ('arrived', 'roomed', 'in_progress', 'completed', 'no_show')),
    room            text,
    arrived_at      timestamptz,
    roomed_at       timestamptz,
    started_at      timestamptz,
    completed_at    timestamptz,
    no_show_at      timestamptz,
    encounter_id    uuid REFERENCES encounters(id),   -- the past-visit record written on completion
    updated_by      uuid REFERENCES users(id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX appointment_encounters_queue_idx ON appointment_encounters (practitioner_id, status);

-- After-visit summary (FHIR Composition). Authored by the treating clinician and published directly.
CREATE TABLE after_visit_summaries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    appointment_id  uuid UNIQUE REFERENCES appointments(id),
    encounter_id    uuid UNIQUE REFERENCES encounters(id),
    instructions    text NOT NULL,
    follow_up       text,
    prescriptions   text,
    author_user_id  uuid REFERENCES users(id),
    published_at    timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (appointment_id IS NOT NULL OR encounter_id IS NOT NULL)
);
CREATE INDEX after_visit_summaries_patient_idx ON after_visit_summaries (patient_id);

-- Referral (FHIR ServiceRequest), closed loop from creation to completed visit.
CREATE TABLE service_requests (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         uuid NOT NULL REFERENCES organizations(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    requester_id            uuid NOT NULL REFERENCES practitioners(id),
    specialty               text NOT NULL,
    target_practitioner_id  uuid REFERENCES practitioners(id),
    reason                  text NOT NULL,
    priority                text NOT NULL DEFAULT 'routine' CHECK (priority IN ('routine', 'urgent')),
    required_documents      text[] NOT NULL DEFAULT '{}',
    provided_documents      text[] NOT NULL DEFAULT '{}',
    status                  text NOT NULL DEFAULT 'draft' CHECK (status IN
                                ('draft', 'sent', 'accepted', 'scheduled', 'completed', 'declined', 'expired', 'cancelled')),
    expires_on              date NOT NULL,
    appointment_id          uuid REFERENCES appointments(id),
    status_note             text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    sent_at                 timestamptz,
    accepted_at             timestamptz,
    scheduled_at            timestamptz,
    completed_at            timestamptz,
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX service_requests_patient_idx ON service_requests (patient_id, created_at DESC);
CREATE INDEX service_requests_requester_idx ON service_requests (requester_id, created_at DESC);
CREATE INDEX service_requests_open_idx ON service_requests (organization_id, status)
    WHERE status IN ('sent', 'accepted', 'scheduled');

-- Every status change with who and when. actor_user_id is NULL for automatic changes (expiry, booking detected).
CREATE TABLE service_request_history (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_request_id  uuid NOT NULL REFERENCES service_requests(id) ON DELETE CASCADE,
    patient_id          uuid NOT NULL REFERENCES patients(id),
    from_status         text,
    to_status           text NOT NULL,
    actor_user_id       uuid REFERENCES users(id),
    note                text,
    occurred_at         timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX service_request_history_idx ON service_request_history (service_request_id, occurred_at);
CREATE INDEX service_request_history_patient_idx ON service_request_history (patient_id, occurred_at);
