-- Online pharmacy ordering and delivery (builds on 050 Pharmacy).
--
-- Patients order over-the-counter products and their ready prescriptions for home delivery or pickup at the
-- clinic pharmacy. Safety checks run at add-to-cart and checkout; flagged orders and every prescription wait for
-- a pharmacist. Payment is a DEMO: only fake demo tokens are accepted and only the demo card's brand and last
-- four digits are kept. No card number, CVV or processor token is ever stored.

-- Pharmacists: staff users allowed into the verification and fulfilment workspace (FHIR PractitionerRole).
CREATE TABLE pharmacy_staff (
    user_id         uuid PRIMARY KEY REFERENCES users(id),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    role            text NOT NULL DEFAULT 'pharmacist' CHECK (role IN ('pharmacist')),
    license_number  text,
    pharmacy_id     uuid REFERENCES pharmacies(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Over-the-counter catalog (FHIR MedicationKnowledge). Fictional brands, generic ingredient names.
-- `ingredients` is [{"code": "ibuprofen", "name": "Ibuprofen", "strength": "200 mg"}].
-- `drug_classes` drive the interaction table (nsaid, decongestant, sedating_antihistamine...).
CREATE TABLE otc_products (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sku                     text NOT NULL UNIQUE,
    name                    text NOT NULL,
    generic_name            text NOT NULL,
    category                text NOT NULL CHECK (category IN ('pain_relief', 'allergy', 'cold_flu', 'digestive',
                                                               'first_aid', 'vitamins', 'devices', 'sleep')),
    form                    text NOT NULL,
    pack_size               text NOT NULL,
    price_cents             integer NOT NULL CHECK (price_cents > 0),
    ingredients             jsonb NOT NULL DEFAULT '[]'::jsonb,
    drug_classes            text[] NOT NULL DEFAULT '{}',
    allergens               text[] NOT NULL DEFAULT '{}',
    pharmacist_only         boolean NOT NULL DEFAULT false,
    min_age                 integer CHECK (min_age BETWEEN 0 AND 21),
    max_qty_per_order       integer NOT NULL DEFAULT 5 CHECK (max_qty_per_order BETWEEN 1 AND 20),
    controlled_schedule     text CHECK (controlled_schedule IN ('II', 'III', 'IV', 'V')),
    requires_refrigeration  boolean NOT NULL DEFAULT false,
    warnings                text[] NOT NULL DEFAULT '{}',
    active                  boolean NOT NULL DEFAULT true
);
CREATE INDEX otc_products_category_idx ON otc_products (category, name) WHERE active;

-- Saved delivery addresses (FHIR Patient.address).
CREATE TABLE pharmacy_delivery_addresses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    label           text NOT NULL,
    recipient_name  text NOT NULL,
    line1           text NOT NULL,
    line2           text,
    city            text NOT NULL,
    state           text NOT NULL CHECK (state ~ '^[A-Z]{2}$'),
    postal_code     text NOT NULL CHECK (postal_code ~ '^[0-9]{5}(-[0-9]{4})?$'),
    phone           text,
    instructions    text,
    is_default      boolean NOT NULL DEFAULT false,
    archived_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pharmacy_delivery_addresses_patient_idx ON pharmacy_delivery_addresses (patient_id) WHERE archived_at IS NULL;
CREATE UNIQUE INDEX pharmacy_delivery_addresses_one_default_idx
    ON pharmacy_delivery_addresses (patient_id) WHERE is_default AND archived_at IS NULL;

-- The patient's cart: an OTC product or one of their own prescriptions.
CREATE TABLE pharmacy_cart_items (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id              uuid NOT NULL REFERENCES patients(id),
    product_id              uuid REFERENCES otc_products(id),
    medication_request_id   uuid REFERENCES medication_requests(id),
    quantity                integer NOT NULL CHECK (quantity BETWEEN 1 AND 20),
    added_at                timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((product_id IS NULL) <> (medication_request_id IS NULL))
);
CREATE UNIQUE INDEX pharmacy_cart_product_idx ON pharmacy_cart_items (patient_id, product_id) WHERE product_id IS NOT NULL;
CREATE UNIQUE INDEX pharmacy_cart_rx_idx ON pharmacy_cart_items (patient_id, medication_request_id)
    WHERE medication_request_id IS NOT NULL;

-- An order (FHIR SupplyRequest + Task for fulfilment). Status machine lives in routers/pharmacy_orders.py.
CREATE SEQUENCE pharmacy_order_number_seq START 100101;
CREATE TABLE pharmacy_orders (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number              text NOT NULL UNIQUE,
    patient_id          uuid NOT NULL REFERENCES patients(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    status              text NOT NULL CHECK (status IN ('placed', 'pharmacist_review', 'approved', 'rejected', 'packed',
                                                        'out_for_delivery', 'delivered', 'ready_for_pickup',
                                                        'picked_up', 'cancelled')),
    fulfillment         text NOT NULL CHECK (fulfillment IN ('delivery', 'pickup')),
    pharmacy_id         uuid NOT NULL REFERENCES pharmacies(id),     -- fulfilling (clinic) pharmacy
    address_id          uuid REFERENCES pharmacy_delivery_addresses(id),
    address             jsonb,                                       -- snapshot at checkout; NULL for pickup
    window_code         text NOT NULL,
    window_label        text NOT NULL,
    window_start        timestamptz NOT NULL,
    window_end          timestamptz NOT NULL,
    cold_chain          boolean NOT NULL DEFAULT false,
    requires_review     boolean NOT NULL DEFAULT false,
    review_reasons      jsonb NOT NULL DEFAULT '[]'::jsonb,          -- check codes that routed it to a pharmacist
    checks              jsonb NOT NULL DEFAULT '{}'::jsonb,          -- check results at checkout, as the patient saw them
    patient_note        text,
    subtotal_cents      integer NOT NULL CHECK (subtotal_cents >= 0),
    delivery_fee_cents  integer NOT NULL DEFAULT 0 CHECK (delivery_fee_cents >= 0),
    total_cents         integer NOT NULL CHECK (total_cents >= 0),
    counseling_note     text,                                        -- pharmacist's note shown to the patient
    rejection_reason    text,
    cancel_reason       text,
    courier_name        text,
    eta                 timestamptz,
    delivery_proof      jsonb,                                       -- {"type": "recipient"|"left_at_door", ...}
    completed_at        timestamptz,
    reviewed_by         uuid REFERENCES users(id),
    reviewed_at         timestamptz,
    placed_at           timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((fulfillment = 'delivery') = (address IS NOT NULL))
);
CREATE INDEX pharmacy_orders_patient_idx ON pharmacy_orders (patient_id, placed_at DESC);
CREATE INDEX pharmacy_orders_queue_idx ON pharmacy_orders (organization_id, status, placed_at);

CREATE TABLE pharmacy_order_items (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id                uuid NOT NULL REFERENCES pharmacy_orders(id) ON DELETE CASCADE,
    kind                    text NOT NULL CHECK (kind IN ('otc', 'rx')),
    product_id              uuid REFERENCES otc_products(id),
    medication_request_id   uuid REFERENCES medication_requests(id),
    rx_mode                 text CHECK (rx_mode IN ('ready_fill', 'refill')),
    dispense_id             uuid REFERENCES medication_dispenses(id),  -- the fill this delivers
    name                    text NOT NULL,
    detail                  text NOT NULL DEFAULT '',
    quantity                integer NOT NULL CHECK (quantity BETWEEN 1 AND 20),
    unit_price_cents        integer NOT NULL CHECK (unit_price_cents >= 0),
    line_total_cents        integer NOT NULL CHECK (line_total_cents >= 0),
    price_note              text,
    requires_refrigeration  boolean NOT NULL DEFAULT false,
    CHECK ((kind = 'otc') = (product_id IS NOT NULL)),
    CHECK ((kind = 'rx') = (medication_request_id IS NOT NULL AND rx_mode IS NOT NULL))
);
CREATE INDEX pharmacy_order_items_order_idx ON pharmacy_order_items (order_id);
CREATE INDEX pharmacy_order_items_rx_idx ON pharmacy_order_items (medication_request_id) WHERE medication_request_id IS NOT NULL;

-- Status history: one row per transition. Also written to audit_events.
CREATE TABLE pharmacy_order_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        uuid NOT NULL REFERENCES pharmacy_orders(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    from_status     text,
    to_status       text NOT NULL,
    actor_user_id   uuid REFERENCES users(id),
    actor_role      text NOT NULL,
    agent           text,
    note            text,
    at              timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX pharmacy_order_events_order_idx ON pharmacy_order_events (order_id, at);

-- Demo payment. Deliberately has NO card number, CVV, expiry or token column: brand and last four only.
CREATE SEQUENCE pharmacy_order_receipt_seq START 5001;
CREATE TABLE pharmacy_order_payments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        uuid NOT NULL UNIQUE REFERENCES pharmacy_orders(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    amount_cents    integer NOT NULL CHECK (amount_cents >= 0),
    method          text NOT NULL DEFAULT 'demo_card' CHECK (method IN ('demo_card')),
    card_brand      text NOT NULL,
    card_last4      text NOT NULL CHECK (card_last4 ~ '^[0-9]{4}$'),
    status          text NOT NULL CHECK (status IN ('authorized', 'captured', 'voided')),
    receipt_number  text NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
