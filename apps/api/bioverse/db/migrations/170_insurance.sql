-- Insurance connections (module 170): payer registry and connections, X12 eligibility (270/271),
-- professional claims (837P) with acknowledgments (277CA) and remittances (835), the digital insurance
-- card, patient-reported coverage from a card scan, and a prior authorization tracker.
--
-- Additive only. It builds on billing's coverages, claims, explanation_of_benefits and
-- patient_statements (050_billing_pharmacy.sql) and never changes their columns or constraints.
-- Credentials are never stored: payer_connections holds the NAME of a secret, never its value.

-- Payer registry (FHIR Organization with a payer role). Shared across organizations.
CREATE TABLE payers (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                        text NOT NULL,
    payer_id                    text NOT NULL UNIQUE,          -- X12 payer ID (NM109 with qualifier PI)
    connection_type             text NOT NULL CHECK (connection_type IN ('x12_clearinghouse', 'fhir_payer_api')),
    transactions                text[] NOT NULL DEFAULT '{}',  -- e.g. {270/271, 837P, 277CA, 835}
    fhir_base_url               text,                          -- CARIN Blue Button / Da Vinci PDex endpoint
    fhir_profiles               text[] NOT NULL DEFAULT '{}',
    member_phone                text,
    provider_phone              text,
    claims_address              text,
    auth_required_procedures    text[] NOT NULL DEFAULT '{}',  -- CPT/HCPCS the payer requires prior auth for
    fictional                   boolean NOT NULL DEFAULT true,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    CHECK (connection_type <> 'fhir_payer_api' OR fhir_base_url IS NOT NULL)
);

-- One organization's connection to a payer.
CREATE TABLE payer_connections (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         uuid NOT NULL REFERENCES organizations(id),
    payer_ref               uuid NOT NULL REFERENCES payers(id),
    status                  text NOT NULL DEFAULT 'disconnected' CHECK (status IN ('connected', 'disconnected')),
    gateway                 text NOT NULL DEFAULT 'simulated' CHECK (gateway IN ('simulated', 'http')),
    -- The NAME of an environment variable or Secret Manager secret. Never a credential value.
    credentials_secret_name text CHECK (credentials_secret_name ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    last_tested_at          timestamptz,
    last_test_ok            boolean,
    last_test_message       text,
    updated_by              uuid REFERENCES users(id),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, payer_ref)
);

-- What an 837P needs about the billing organization (loop 2010AA) and submitter (1000A).
CREATE TABLE insurance_billing_providers (
    organization_id     uuid PRIMARY KEY REFERENCES organizations(id),
    name                text NOT NULL,
    npi                 text NOT NULL CHECK (npi ~ '^[12][0-9]{9}$'),
    tax_id              text NOT NULL,
    taxonomy            text,
    address_line        text NOT NULL,
    city                text NOT NULL,
    state               text NOT NULL,
    zip                 text NOT NULL,
    phone               text,
    submitter_id        text NOT NULL
);

-- Rendering provider numbers (loop 2310B). Kept here so billing and interop tables stay unchanged.
CREATE TABLE insurance_provider_numbers (
    practitioner_id     uuid PRIMARY KEY REFERENCES practitioners(id),
    npi                 text NOT NULL UNIQUE CHECK (npi ~ '^[12][0-9]{9}$'),
    taxonomy            text
);

-- Coverage details billing's coverages table has no columns for: the registered payer, pharmacy
-- routing numbers for the card, and the subscriber (loop 2010BA) when it is not the patient.
CREATE TABLE coverage_details (
    coverage_id             uuid PRIMARY KEY REFERENCES coverages(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    payer_ref               uuid NOT NULL REFERENCES payers(id),
    relationship            text NOT NULL DEFAULT 'self' CHECK (relationship IN ('self', 'spouse', 'child', 'other')),
    subscriber_name         text,
    subscriber_birth_date   date,
    address_line            text,
    city                    text,
    state                   text,
    zip                     text,
    rx_bin                  text,
    rx_pcn                  text,
    rx_group                text,
    source                  text NOT NULL DEFAULT 'registration' CHECK (source IN ('registration', 'card_scan', 'manual')),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- Coverage a patient added from their card (photo or typed), waiting to be verified with the payer.
-- Verification by a 271 turns it into a billing coverage row plus coverage_details.
CREATE TABLE reported_coverages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    payer_ref           uuid REFERENCES payers(id),
    payer_name          text NOT NULL,
    plan_name           text,
    member_id           text NOT NULL,
    group_number        text,
    rx_bin              text,
    rx_pcn              text,
    rx_group            text,
    payer_phone         text,
    relationship        text NOT NULL DEFAULT 'self' CHECK (relationship IN ('self', 'spouse', 'child', 'other')),
    source              text NOT NULL CHECK (source IN ('photo', 'manual')),
    status              text NOT NULL DEFAULT 'unverified'
                        CHECK (status IN ('unverified', 'verified', 'not_found', 'inactive', 'error')),
    status_message      text,
    coverage_id         uuid REFERENCES coverages(id),
    created_by          uuid REFERENCES users(id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    verified_at         timestamptz
);
CREATE INDEX reported_coverages_patient_idx ON reported_coverages (patient_id, created_at DESC);

-- Each real-time eligibility check (FHIR CoverageEligibilityRequest/Response) with its X12.
CREATE TABLE insurance_eligibility_checks (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    coverage_id             uuid REFERENCES coverages(id),
    reported_coverage_id    uuid REFERENCES reported_coverages(id),
    payer_ref               uuid REFERENCES payers(id),
    appointment_id          uuid REFERENCES appointments(id),
    trigger                 text NOT NULL CHECK (trigger IN ('patient', 'staff', 'job', 'verification', 'seed')),
    status                  text NOT NULL CHECK (status IN ('active', 'inactive', 'not_found', 'error')),
    benefits                jsonb NOT NULL DEFAULT '{}'::jsonb,   -- parsed 271 (EligibilityResult)
    summary                 text[] NOT NULL DEFAULT '{}',         -- plain-language lines
    error                   text,
    request_x12             text,
    response_x12            text,
    simulated               boolean NOT NULL DEFAULT true,
    requested_by            uuid REFERENCES users(id),
    checked_at              timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX insurance_eligibility_patient_idx ON insurance_eligibility_checks (patient_id, checked_at DESC);

-- Prior authorization (FHIR Claim with use = preauthorization, and its ClaimResponse).
CREATE TABLE prior_authorizations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    coverage_id         uuid NOT NULL REFERENCES coverages(id),
    payer_ref           uuid REFERENCES payers(id),
    practitioner_id     uuid REFERENCES practitioners(id),
    procedure_code      text NOT NULL,
    description         text NOT NULL,
    diagnosis_codes     text[] NOT NULL DEFAULT '{}',
    status              text NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'pended', 'approved', 'denied')),
    payer_reference     text,
    note                text,
    submitted_at        timestamptz NOT NULL DEFAULT now(),
    decided_at          timestamptz,
    valid_from          date,
    valid_to            date,
    created_by          uuid REFERENCES users(id),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX prior_authorizations_patient_idx ON prior_authorizations (patient_id, submitted_at DESC);

-- One 837P sent for a billing claim, with the payer's 277CA acknowledgment.
CREATE SEQUENCE insurance_control_seq START 1001;      -- ISA13 / GS06 interchange control numbers
CREATE SEQUENCE insurance_claim_number_seq START 1001;  -- CLM01 patient control numbers
CREATE TABLE insurance_claim_submissions (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         uuid NOT NULL REFERENCES organizations(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    claim_id                uuid NOT NULL REFERENCES claims(id),
    encounter_id            uuid REFERENCES encounters(id),
    coverage_id             uuid NOT NULL REFERENCES coverages(id),
    payer_ref               uuid NOT NULL REFERENCES payers(id),
    prior_authorization_id  uuid REFERENCES prior_authorizations(id),
    patient_control_number  text NOT NULL UNIQUE,
    diagnosis_codes         text[] NOT NULL,
    service_lines           jsonb NOT NULL,
    total_charge_cents      integer NOT NULL CHECK (total_charge_cents > 0),
    status                  text NOT NULL CHECK (status IN ('sent', 'accepted', 'rejected', 'paid', 'denied')),
    x12_837                 text NOT NULL,
    interchange_control     text NOT NULL,
    x12_277ca               text,
    ack_category            text,
    ack_status_code         text,
    ack_message             text,
    payer_claim_number      text,
    simulated               boolean NOT NULL DEFAULT true,
    submitted_by            uuid REFERENCES users(id),
    submitted_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    acknowledged_at         timestamptz,
    remitted_at             timestamptz
);
-- A billing claim has at most one submission still in play; a rejected one can be corrected and resent.
CREATE UNIQUE INDEX insurance_claim_submissions_live_idx ON insurance_claim_submissions (claim_id)
    WHERE status <> 'rejected';
CREATE INDEX insurance_claim_submissions_org_idx ON insurance_claim_submissions (organization_id, submitted_at DESC);

-- An 835 received (from the simulated payer or pasted from a real clearinghouse).
-- Provider-level adjustments (PLB) live here: billing has no table for them.
CREATE TABLE insurance_remittances (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    payer_ref           uuid REFERENCES payers(id),
    payer_name          text NOT NULL,
    trace_number        text NOT NULL,
    payment_cents       integer NOT NULL,
    payment_method      text NOT NULL,
    payment_date        date NOT NULL,
    provider_adjustments jsonb NOT NULL DEFAULT '[]'::jsonb,
    provider_adjustment_cents integer NOT NULL DEFAULT 0,
    x12_835             text NOT NULL,
    source              text NOT NULL CHECK (source IN ('simulated', 'imported', 'seed')),
    received_by         uuid REFERENCES users(id),
    received_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, payer_name, trace_number)
);

-- Each CLP in an 835 and how it was posted to billing.
CREATE TABLE insurance_remittance_claims (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    remittance_id           uuid NOT NULL REFERENCES insurance_remittances(id),
    submission_id           uuid REFERENCES insurance_claim_submissions(id),
    claim_id                uuid REFERENCES claims(id),
    patient_id              uuid REFERENCES patients(id),
    patient_control_number  text NOT NULL,
    status_code             text NOT NULL,
    charge_cents            integer NOT NULL,
    paid_cents              integer NOT NULL,
    patient_resp_cents      integer NOT NULL,
    payer_claim_number      text,
    adjustments             jsonb NOT NULL DEFAULT '[]'::jsonb,   -- every CAS, claim and line level
    service_lines           jsonb NOT NULL DEFAULT '[]'::jsonb,
    posting_status          text NOT NULL CHECK (posting_status IN ('posted', 'already_posted', 'unmatched', 'needs_review')),
    posting_note            text,
    posted_at               timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX insurance_remittance_claims_patient_idx ON insurance_remittance_claims (patient_id);

-- ============================================================================================
-- SIMULATED PAYER SIDE. Everything below stands in for a payer's own systems so the demo can run
-- end to end without a clearinghouse contract. Fictional members, keyed by member ID as a payer
-- would key them; the payer never sees our patient IDs.
-- ============================================================================================

CREATE TABLE payer_sim_members (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_ref                   uuid NOT NULL REFERENCES payers(id),
    member_id                   text NOT NULL,
    first_name                  text NOT NULL,
    last_name                   text NOT NULL,
    birth_date                  date NOT NULL,
    gender                      text NOT NULL DEFAULT 'U' CHECK (gender IN ('F', 'M', 'U')),
    group_number                text,
    plan_name                   text NOT NULL,
    plan_begin                  date NOT NULL,
    plan_end                    date,
    deductible_cents            integer NOT NULL,
    deductible_met_cents        integer NOT NULL DEFAULT 0,
    family_deductible_cents     integer,
    family_deductible_met_cents integer NOT NULL DEFAULT 0,
    oop_max_cents               integer NOT NULL,
    oop_met_cents               integer NOT NULL DEFAULT 0,
    family_oop_max_cents        integer,
    family_oop_met_cents        integer NOT NULL DEFAULT 0,
    coinsurance_pct             integer NOT NULL DEFAULT 20,
    oon_coinsurance_pct         integer NOT NULL DEFAULT 40,
    -- {"primary_care": 2500, "specialist": 5000, "telehealth": 1500, "urgent_care": 7500, "generic_rx": 1000}
    copays                      jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (payer_ref, member_id)
);

-- Claims the simulated payer has received and not yet paid or denied.
CREATE TABLE payer_sim_claims (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_ref               uuid NOT NULL REFERENCES payers(id),
    patient_control_number  text NOT NULL,
    payer_claim_number      text NOT NULL UNIQUE,
    claim                   jsonb NOT NULL,                 -- the parsed 837P
    status                  text NOT NULL CHECK (status IN ('accepted', 'adjudicated')),
    received_at             timestamptz NOT NULL DEFAULT clock_timestamp(),
    adjudicated_at          timestamptz,
    remit_trace             text
);
CREATE INDEX payer_sim_claims_pending_idx ON payer_sim_claims (payer_ref) WHERE status = 'accepted';
