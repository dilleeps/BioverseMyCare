-- Public learning: health misinformation checker, public specialist AI agents ("digital doubles"),
-- and medical-student access (de-identified case library, Socratic tutor, quizzes).

-- Medical students are a new role. They never reach identifiable patient data (see bioverse/auth.py).
ALTER TABLE users DROP CONSTRAINT users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('patient', 'clinician', 'staff', 'admin', 'student'));

-- ---------------------------------------------------------------------------------------------
-- Misinformation checker
-- ---------------------------------------------------------------------------------------------

-- Curated claim reviews (schema.org ClaimReview, flattened). A claim matches a review when every
-- term group has at least one term in the claim. Verdicts cite evidence_items rows only.
CREATE TABLE factcheck_claim_reviews (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim             text NOT NULL,                  -- canonical wording, e.g. "Vaccines cause autism"
    match_terms       jsonb NOT NULL,                 -- [["vaccin", "mmr"], ["autis"]]
    verdict           text NOT NULL CHECK (verdict IN ('supported', 'contradicted', 'misleading', 'not_enough_evidence')),
    -- The verdict when the claim is stated in the negative ("vaccines do not cause autism").
    negated_verdict   text NOT NULL CHECK (negated_verdict IN ('supported', 'contradicted', 'misleading', 'not_enough_evidence')),
    explanation       text NOT NULL,                  -- one plain-language line
    negated_explanation text NOT NULL,
    evidence_item_ids uuid[] NOT NULL DEFAULT '{}',   -- evidence_items(id); never free-text citations
    example_text      text,                           -- a demo message the screen offers to try
    active            boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- One row per check. No pasted text and no user identity: a hash of the text and the verdicts only.
CREATE TABLE factcheck_checks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    text_sha256     text NOT NULL,
    char_count      integer NOT NULL,
    claim_count     integer NOT NULL,
    verdicts        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{verdict, review_id, evidence_ids}]
    safety_level    text NOT NULL DEFAULT 'none',
    url_present     boolean NOT NULL DEFAULT false,
    mode            text NOT NULL CHECK (mode IN ('ai', 'rules')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX factcheck_checks_created_idx ON factcheck_checks (created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- Public specialist agents
-- ---------------------------------------------------------------------------------------------

CREATE TABLE public_agents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id     uuid NOT NULL UNIQUE REFERENCES practitioners(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    display_name        text NOT NULL,
    specialty           text NOT NULL,
    headline            text NOT NULL DEFAULT '',
    bio                 text NOT NULL DEFAULT '',
    topics              text[] NOT NULL DEFAULT '{}',       -- allowed topics (scope)
    tone                text NOT NULL DEFAULT 'warm' CHECK (tone IN ('warm', 'direct', 'formal')),
    -- draft -> pending_approval (clinician submits) -> approved | rejected (admin decides)
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'pending_approval', 'approved', 'rejected')),
    paused              boolean NOT NULL DEFAULT false,
    submitted_at        timestamptz,
    reviewed_by         uuid REFERENCES users(id),
    reviewed_at         timestamptz,
    review_note         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- The clinician's own guidance: the only clinician voice the agent may quote.
CREATE TABLE public_agent_guidance (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        uuid NOT NULL REFERENCES public_agents(id),
    topic           text NOT NULL,
    title           text NOT NULL,
    body            text NOT NULL,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    search          tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', topic || ' ' || title), 'A')
                        || setweight(to_tsvector('english', body), 'B')
                    ) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX public_agent_guidance_agent_idx ON public_agent_guidance (agent_id);
CREATE INDEX public_agent_guidance_search_idx ON public_agent_guidance USING GIN (search);

-- Sample questions and answers the clinician must approve before the agent can be submitted.
CREATE TABLE public_agent_samples (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        uuid NOT NULL REFERENCES public_agents(id),
    question        text NOT NULL,
    answer          text NOT NULL,
    citations       jsonb NOT NULL DEFAULT '[]'::jsonb,
    approved        boolean NOT NULL DEFAULT false,
    approved_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX public_agent_samples_agent_idx ON public_agent_samples (agent_id);

-- Conversation log. The clinician reviews it without seeing who asked.
CREATE TABLE public_agent_messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        uuid NOT NULL REFERENCES public_agents(id),
    user_id         uuid NOT NULL REFERENCES users(id),
    -- Set when the asker is a patient: the question may describe their health.
    patient_id      uuid REFERENCES patients(id),
    conversation_id uuid NOT NULL,
    question        text NOT NULL,
    kind            text NOT NULL
                    CHECK (kind IN ('answer', 'no_answer', 'out_of_scope', 'personal', 'emergency')),
    answer          text NOT NULL,
    citations       jsonb NOT NULL DEFAULT '[]'::jsonb,
    guidance_ids    uuid[] NOT NULL DEFAULT '{}',
    mode            text NOT NULL CHECK (mode IN ('ai', 'rules')),
    safety_level    text NOT NULL DEFAULT 'none',
    flagged         boolean NOT NULL DEFAULT false,
    flag_note       text,
    flagged_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX public_agent_messages_agent_idx ON public_agent_messages (agent_id, created_at DESC);
CREATE INDEX public_agent_messages_user_idx ON public_agent_messages (user_id, created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- Medical-student learning
-- ---------------------------------------------------------------------------------------------

-- De-identified teaching cases. Built once from demo records by bioverse/routers/learning_cases.py;
-- there is deliberately no column linking a case back to a patient.
CREATE TABLE learning_cases (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    title           text NOT NULL,
    specialty       text NOT NULL,
    difficulty      text NOT NULL DEFAULT 'core' CHECK (difficulty IN ('core', 'intermediate', 'advanced')),
    summary         text NOT NULL,
    content         jsonb NOT NULL,       -- stages, model answers, teaching points, quiz
    published       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- A student working through a case with the tutor.
CREATE TABLE learning_attempts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    case_id         uuid NOT NULL REFERENCES learning_cases(id),
    stage           integer NOT NULL DEFAULT 0,          -- index of the stage awaiting an answer
    responses       jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{stage, answer, covered, missed, feedback, question, mode, at}]
    status          text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    score           integer,
    started_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz
);
CREATE INDEX learning_attempts_user_idx ON learning_attempts (user_id, started_at DESC);

CREATE TABLE learning_quiz_attempts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    case_id         uuid NOT NULL REFERENCES learning_cases(id),
    answers         jsonb NOT NULL,
    score           integer NOT NULL,
    total           integer NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX learning_quiz_attempts_user_idx ON learning_quiz_attempts (user_id, created_at DESC);
