-- Billing & Coverage (module 15) and Pharmacy (module 16).
--
-- Billing here is the PATIENT financial experience (docs/decisions/003). It never stores card data:
-- in this demo a "Demo payer" (rules in these tables) adjudicates claims, and a real deployment would
-- hand payments to the hospital's own processor. All money is integer cents.

-- ============================================================================================
-- Billing & Coverage
-- ============================================================================================

-- Service price list (FHIR ChargeItemDefinition). `allowed_cents` is the demo payer's contracted rate.
CREATE TABLE service_prices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code            text NOT NULL,
    name            text NOT NULL,
    category        text NOT NULL CHECK (category IN ('primary_care', 'specialist', 'telehealth', 'imaging', 'lab')),
    price_cents     integer NOT NULL CHECK (price_cents >= 0),
    allowed_cents   integer NOT NULL CHECK (allowed_cents >= 0 AND allowed_cents <= price_cents),
    UNIQUE (organization_id, code)
);

-- Coverage (FHIR Coverage) with the plan-year benefit accumulators the demo payer keeps.
CREATE TABLE coverages (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    payer_name              text NOT NULL,
    plan_name               text NOT NULL,
    member_id               text NOT NULL,
    group_number            text,
    status                  text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    effective_start         date NOT NULL,
    effective_end           date,
    deductible_cents        integer NOT NULL CHECK (deductible_cents >= 0),
    deductible_met_cents    integer NOT NULL DEFAULT 0 CHECK (deductible_met_cents >= 0),
    oop_max_cents           integer NOT NULL CHECK (oop_max_cents >= 0),
    oop_met_cents           integer NOT NULL DEFAULT 0 CHECK (oop_met_cents >= 0),
    coinsurance_pct         integer NOT NULL CHECK (coinsurance_pct BETWEEN 0 AND 100),
    oon_coinsurance_pct     integer NOT NULL CHECK (oon_coinsurance_pct BETWEEN 0 AND 100),
    -- {"primary_care": 2500, ...}: categories with a flat in-network copay. Others go through deductible.
    copays                  jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX coverages_patient_idx ON coverages (patient_id);

-- CoverageEligibilityResponse: each eligibility check against the demo payer.
CREATE TABLE coverage_eligibility_responses (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    coverage_id uuid NOT NULL REFERENCES coverages(id),
    patient_id  uuid NOT NULL REFERENCES patients(id),
    outcome     text NOT NULL CHECK (outcome IN ('active', 'inactive')),
    benefits    jsonb NOT NULL DEFAULT '{}'::jsonb,
    checked_by  uuid REFERENCES users(id),
    checked_at  timestamptz NOT NULL DEFAULT now()
);

-- Claim (FHIR Claim).
CREATE TABLE claims (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    coverage_id     uuid NOT NULL REFERENCES coverages(id),
    practitioner_id uuid REFERENCES practitioners(id),
    service_code    text NOT NULL,
    service_name    text NOT NULL,
    category        text NOT NULL,
    service_date    date NOT NULL,
    billed_cents    integer NOT NULL CHECK (billed_cents >= 0),
    status          text NOT NULL CHECK (status IN ('submitted', 'in_review', 'paid', 'denied', 'appealed')),
    denial_reason   text,
    appeal_reason   text,
    appealed_at     timestamptz,
    submitted_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX claims_patient_idx ON claims (patient_id, service_date DESC);

-- ExplanationOfBenefit: the demo payer's adjudication of a claim. Absent until adjudicated.
CREATE TABLE explanation_of_benefits (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id            uuid NOT NULL UNIQUE REFERENCES claims(id),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    allowed_cents       integer NOT NULL CHECK (allowed_cents >= 0),
    plan_paid_cents     integer NOT NULL CHECK (plan_paid_cents >= 0),
    copay_cents         integer NOT NULL DEFAULT 0 CHECK (copay_cents >= 0),
    deductible_cents    integer NOT NULL DEFAULT 0 CHECK (deductible_cents >= 0),
    coinsurance_cents   integer NOT NULL DEFAULT 0 CHECK (coinsurance_cents >= 0),
    patient_resp_cents  integer NOT NULL CHECK (patient_resp_cents >= 0),
    adjudicated_at      timestamptz NOT NULL DEFAULT now()
);

-- Patient statement (FHIR Invoice): what the patient owes for one claim.
-- Balance = amount - adjustments - payments; never stored, always computed.
CREATE TABLE patient_statements (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    claim_id        uuid NOT NULL UNIQUE REFERENCES claims(id),
    amount_cents    integer NOT NULL CHECK (amount_cents >= 0),
    issued_on       date NOT NULL,
    due_on          date NOT NULL
);
CREATE INDEX patient_statements_patient_idx ON patient_statements (patient_id);

-- Financial assistance application. Reviewed by organization administrators in /admin/billing.
CREATE TABLE financial_assistance_applications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    household_size  integer NOT NULL CHECK (household_size BETWEEN 1 AND 20),
    income_band     text NOT NULL CHECK (income_band IN ('under_200_fpl', '200_300_fpl', '300_400_fpl', 'over_400_fpl')),
    attestations    jsonb NOT NULL DEFAULT '{}'::jsonb,
    status          text NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'approved', 'denied')),
    discount_pct    integer CHECK (discount_pct BETWEEN 1 AND 100),
    decision_note   text,
    decided_by      uuid REFERENCES users(id),
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX fa_applications_patient_idx ON financial_assistance_applications (patient_id, created_at DESC);
CREATE UNIQUE INDEX fa_applications_one_open_idx ON financial_assistance_applications (patient_id) WHERE status = 'submitted';

-- Reductions to a statement, e.g. a financial assistance discount.
CREATE TABLE statement_adjustments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    statement_id    uuid NOT NULL REFERENCES patient_statements(id),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    kind            text NOT NULL CHECK (kind IN ('financial_assistance')),
    amount_cents    integer NOT NULL CHECK (amount_cents > 0),
    application_id  uuid REFERENCES financial_assistance_applications(id),
    created_by      uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Payment recorded in the demo (FHIR PaymentReconciliation, simplified).
-- Deliberately has NO card, bank or processor-token columns.
CREATE SEQUENCE payment_receipt_seq START 1001;
CREATE TABLE payments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    statement_id    uuid NOT NULL REFERENCES patient_statements(id),
    amount_cents    integer NOT NULL CHECK (amount_cents > 0),
    method          text NOT NULL DEFAULT 'demo' CHECK (method IN ('demo')),
    receipt_number  text NOT NULL UNIQUE,
    recorded_by     uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX payments_statement_idx ON payments (statement_id, created_at);

-- Payment plan: a statement balance split into monthly installments.
CREATE TABLE payment_plans (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    statement_id    uuid NOT NULL REFERENCES patient_statements(id),
    installments    integer NOT NULL CHECK (installments BETWEEN 2 AND 12),
    total_cents     integer NOT NULL CHECK (total_cents > 0),
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed')),
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX payment_plans_one_active_idx ON payment_plans (statement_id) WHERE status = 'active';

CREATE TABLE payment_plan_installments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         uuid NOT NULL REFERENCES payment_plans(id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    due_on          date NOT NULL,
    amount_cents    integer NOT NULL CHECK (amount_cents >= 0),
    UNIQUE (plan_id, seq)
);

-- ============================================================================================
-- Pharmacy
-- ============================================================================================

-- Pharmacy directory (FHIR Organization + Location). Fictional demo pharmacies.
CREATE TABLE pharmacies (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    address         text NOT NULL,
    phone           text NOT NULL,
    hours           text NOT NULL,
    distance_km     numeric(5, 1) NOT NULL DEFAULT 0,
    open_24_hours   boolean NOT NULL DEFAULT false
);

CREATE TABLE patient_pharmacy_preferences (
    patient_id      uuid PRIMARY KEY REFERENCES patients(id),
    pharmacy_id     uuid NOT NULL REFERENCES pharmacies(id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Curated demo drug information. NOT generated by AI and not for clinical use.
CREATE TABLE drug_monographs (
    code                text PRIMARY KEY,
    name                text NOT NULL,
    drug_class          text NOT NULL,
    uses                text NOT NULL,
    how_to_take         text NOT NULL,
    common_side_effects text[] NOT NULL DEFAULT '{}',
    call_doctor_if      text[] NOT NULL DEFAULT '{}'
);

-- Curated interaction pairs. `drug_b` is another monograph; `substance` is a food or drink advisory.
CREATE TABLE drug_interactions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    drug_a      text NOT NULL REFERENCES drug_monographs(code),
    drug_b      text REFERENCES drug_monographs(code),
    substance   text,
    severity    text NOT NULL CHECK (severity IN ('major', 'moderate', 'advisory')),
    summary     text NOT NULL,
    advice      text NOT NULL,
    CHECK ((drug_b IS NULL) <> (substance IS NULL))
);

-- MedicationRequest (prescriptions).
CREATE TABLE medication_requests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    prescriber_id       uuid NOT NULL REFERENCES practitioners(id),
    drug_code           text NOT NULL REFERENCES drug_monographs(code),
    drug_name           text NOT NULL,
    strength            text NOT NULL,
    sig                 text NOT NULL,
    quantity            integer NOT NULL CHECK (quantity > 0),
    refills_authorized  integer NOT NULL DEFAULT 0 CHECK (refills_authorized >= 0),
    refills_remaining   integer NOT NULL DEFAULT 0 CHECK (refills_remaining >= 0),
    status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_hold', 'completed', 'stopped')),
    pharmacy_id         uuid REFERENCES pharmacies(id),
    authored_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX medication_requests_patient_idx ON medication_requests (patient_id, authored_at DESC);

-- MedicationDispense: one per fill. The prescription's dispense status is its latest fill's status.
CREATE TABLE medication_dispenses (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_request_id   uuid NOT NULL REFERENCES medication_requests(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    pharmacy_id             uuid NOT NULL REFERENCES pharmacies(id),
    fill_number             integer NOT NULL,
    status                  text NOT NULL CHECK (status IN ('sent', 'received', 'ready', 'picked_up')),
    sent_at                 timestamptz NOT NULL DEFAULT clock_timestamp(),
    ready_at                timestamptz,
    picked_up_at            timestamptz,
    UNIQUE (medication_request_id, fill_number)
);

-- Refill request from the patient. Auto-sent when refills remain; otherwise waits for the prescriber.
CREATE TABLE refill_requests (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_request_id   uuid NOT NULL REFERENCES medication_requests(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    prescriber_id           uuid NOT NULL REFERENCES practitioners(id),
    pharmacy_id             uuid NOT NULL REFERENCES pharmacies(id),
    status                  text NOT NULL CHECK (status IN ('sent_to_pharmacy', 'pending_approval', 'approved', 'denied')),
    patient_note            text,
    dispense_id             uuid REFERENCES medication_dispenses(id),
    review_item_id          uuid REFERENCES review_items(id),
    decision_note           text,
    decided_by              uuid REFERENCES users(id),
    decided_at              timestamptz,
    created_at              timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX refill_requests_one_pending_idx ON refill_requests (medication_request_id) WHERE status = 'pending_approval';

-- Patient-reported doses (FHIR MedicationStatement, one row per day taken).
CREATE TABLE medication_adherence_logs (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_request_id   uuid NOT NULL REFERENCES medication_requests(id),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    taken_on                date NOT NULL,
    logged_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (medication_request_id, taken_on)
);
