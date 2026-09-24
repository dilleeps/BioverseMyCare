-- Interoperability (module 22) and patient document upload (module 6).
-- Additive only: new tables plus one nullable column on diagnostic_reports.

-- Where a report came from. NULL for rows that predate this migration (treated as the lab feed).
ALTER TABLE diagnostic_reports ADD COLUMN source text
    CHECK (source IN ('lab_feed', 'patient_upload', 'hl7_import'));

-- Terminology service (FHIR CodeSystem.concept). A small, clearly labeled SUBSET of each code system,
-- seeded by bioverse/db/seeds/s090_interop_documents.py. Not a licensed terminology release.
CREATE TABLE code_system_concepts (
    system      text NOT NULL,                        -- canonical URI, e.g. http://loinc.org
    code        text NOT NULL,
    display     text NOT NULL,
    synonyms    text[] NOT NULL DEFAULT '{}',          -- lower-case names used to map free text to this code
    properties  jsonb NOT NULL DEFAULT '{}'::jsonb,    -- e.g. {"unit": "mg/dL"} for a LOINC lab
    PRIMARY KEY (system, code)
);

-- Patient.identifier: medical record numbers and other external identifiers (master patient index).
CREATE TABLE patient_identifiers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    system          text NOT NULL,                     -- FHIR identifier system URI
    hl7_authority   text NOT NULL,                     -- HL7 v2 assigning authority (CX.4) that issues it
    value           text NOT NULL,
    type_code       text NOT NULL DEFAULT 'MR',        -- HL7 v2 table 0203 identifier type
    UNIQUE (system, value),
    UNIQUE (hl7_authority, value)
);

-- Practitioner.identifier: how external systems (OBR-16 ordering provider) name our clinicians.
CREATE TABLE practitioner_identifiers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    system          text NOT NULL,
    hl7_authority   text NOT NULL,
    value           text NOT NULL,
    UNIQUE (system, value),
    UNIQUE (hl7_authority, value)
);

-- DocumentReference + Binary: a patient-supplied document, stored in the database (no external storage).
CREATE TABLE document_references (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    uploaded_by     uuid NOT NULL REFERENCES users(id),
    kind            text NOT NULL DEFAULT 'lab_report',
    filename        text,
    content_type    text NOT NULL,
    size_bytes      integer NOT NULL,
    sha256          text NOT NULL,
    content         bytea NOT NULL,
    -- uploaded -> extracted (values proposed) -> confirmed (patient checked and saved) | discarded
    status          text NOT NULL DEFAULT 'uploaded'
                    CHECK (status IN ('uploaded', 'extracted', 'confirmed', 'discarded')),
    extraction      jsonb,
    extracted_by    text,
    report_id       uuid REFERENCES diagnostic_reports(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    confirmed_at    timestamptz
);
CREATE INDEX document_references_patient_idx ON document_references (patient_id, created_at DESC);

-- Inbound HL7 v2 messages and the outcome of each (the lab-import log). Rejected messages keep
-- patient_id NULL: a message we could not match is never attached to anyone.
CREATE TABLE hl7_inbound_messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at         timestamptz NOT NULL DEFAULT now(),
    received_by         uuid REFERENCES users(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    message_type        text,
    control_id          text,
    sending_facility    text,
    raw                 text NOT NULL,
    outcome             text NOT NULL CHECK (outcome IN ('accepted', 'rejected')),
    reason              text,
    match_method        text,
    patient_id          uuid REFERENCES patients(id),
    report_id           uuid REFERENCES diagnostic_reports(id),
    review_item_id      uuid REFERENCES review_items(id),
    detail              jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX hl7_inbound_messages_recent_idx ON hl7_inbound_messages (organization_id, received_at DESC);
CREATE INDEX hl7_inbound_messages_control_idx ON hl7_inbound_messages (sending_facility, control_id)
    WHERE outcome = 'accepted';
