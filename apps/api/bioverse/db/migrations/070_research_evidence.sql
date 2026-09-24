-- Evidence Assistant (module 10) and Research & Clinical Trials (module 18).

-- Curated evidence library (FHIR Evidence + Citation, flattened). Each row is a short paraphrase of
-- public guidance with its source. The library is what rules mode answers from, and what Claude is
-- given as citable documents in AI mode.
CREATE TABLE evidence_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title           text NOT NULL,
    publisher       text NOT NULL,
    url             text NOT NULL,
    -- Publication date, or for drug labels the date the label version was checked (date_kind).
    published_on    date NOT NULL,
    date_kind       text NOT NULL DEFAULT 'published' CHECK (date_kind IN ('published', 'label_checked')),
    evidence_type   text NOT NULL CHECK (evidence_type IN ('guideline', 'systematic_review', 'drug_label', 'rct')),
    quality         text NOT NULL CHECK (quality IN ('high', 'moderate', 'low')),
    quality_note    text NOT NULL DEFAULT '',          -- e.g. "USPSTF grade B"
    specialties     text[] NOT NULL DEFAULT '{}',
    loinc_codes     text[] NOT NULL DEFAULT '{}',      -- labs this evidence is about (patient panel)
    keywords        text NOT NULL DEFAULT '',          -- drug and condition terms, searched with weight B
    snippet         text NOT NULL,
    search          tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', title), 'A')
                        || setweight(to_tsvector('english', keywords), 'B')
                        || setweight(to_tsvector('english', snippet), 'C')
                    ) STORED,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_items_search_idx ON evidence_items USING GIN (search);
CREATE INDEX evidence_items_loinc_idx ON evidence_items USING GIN (loinc_codes);

-- A clinician's question and the answer shown. The question is stored after patient identifiers
-- were stripped. patient_id is set only when the clinician chose to use that patient's
-- de-identified context.
CREATE TABLE evidence_queries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    practitioner_id uuid REFERENCES practitioners(id),
    patient_id      uuid REFERENCES patients(id),
    question        text NOT NULL,
    mode            text NOT NULL CHECK (mode IN ('ai', 'rules')),
    model           text,
    answer          jsonb NOT NULL,
    sources_count   integer NOT NULL DEFAULT 0,
    -- Uncited sentences the AI wrote and Bioverse blocked. Kept for hallucination monitoring, never shown.
    removed_claims  jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_queries_user_idx ON evidence_queries (user_id, created_at DESC);

-- ResearchStudy. Eligibility is structured so a deterministic engine (bioverse/trials.py) can
-- evaluate it; see that module for the criterion shapes.
CREATE TABLE research_studies (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title           text NOT NULL,
    short_title     text NOT NULL,
    sponsor         text NOT NULL,
    phase           text NOT NULL,
    status          text NOT NULL CHECK (status IN ('recruiting', 'not_yet_recruiting', 'active_not_recruiting', 'completed')),
    conditions      text[] NOT NULL DEFAULT '{}',
    summary         text NOT NULL,                     -- plain language, patient-facing
    what_happens    text NOT NULL DEFAULT '',          -- visits, duration, what participants do
    sites           jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{name, city, distance_km}]
    contact         jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {name, phone, email}
    eligibility     jsonb NOT NULL,
    is_demo         boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ResearchSubject: a patient's interest in a study and where it is in the pipeline.
CREATE TABLE research_subjects (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    study_id            uuid NOT NULL REFERENCES research_studies(id),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    status              text NOT NULL DEFAULT 'interested'
                        CHECK (status IN ('interested', 'contacted', 'screening', 'enrolled', 'not_eligible', 'withdrawn')),
    -- False once the patient revokes research consent: the study team may no longer contact them.
    contact_permitted   boolean NOT NULL DEFAULT true,
    history             jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{status, at, by_role, note}]
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (study_id, patient_id)
);
CREATE INDEX research_subjects_patient_idx ON research_subjects (patient_id);
