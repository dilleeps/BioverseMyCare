-- Messaging & Care Team (module 12) and the Doctor Agent runtime (module 8).
--
-- A thread (FHIR Communication grouped by topic) belongs to exactly one patient. Messages are text only:
-- attachments and document sharing are out of scope for this module.

-- Secure thread between a patient and their care team.
CREATE TABLE communication_threads (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    organization_id     uuid NOT NULL REFERENCES organizations(id),
    subject             text NOT NULL,
    -- care_team: patient <-> care team. previsit: Doctor Agent pre-visit interview. followup: protocol check-ins.
    kind                text NOT NULL DEFAULT 'care_team' CHECK (kind IN ('care_team', 'previsit', 'followup')),
    -- The clinician the thread is addressed to (care-team clinician). Their Doctor Agent config applies.
    practitioner_id     uuid REFERENCES practitioners(id),
    appointment_id      uuid REFERENCES appointments(id),
    care_plan_id        uuid REFERENCES care_plans(id),
    -- Latest triage of the patient's messages.
    category            text CHECK (category IN ('new_symptom', 'worsening_symptom', 'side_effect', 'medication_question',
                                                 'results_question', 'logistics', 'billing', 'other')),
    priority            text NOT NULL DEFAULT 'routine' CHECK (priority IN ('urgent', 'routine')),
    triage_reason       text,
    -- Red flag: emergency guidance was shown and the care team alerted.
    flagged             boolean NOT NULL DEFAULT false,
    flag_reason         text,
    flag_acknowledged_by uuid REFERENCES users(id),
    flag_acknowledged_at timestamptz,
    -- Who is expected to answer: the clinician, the front desk, or the nurse-triage pool (staff).
    assigned_to         text NOT NULL DEFAULT 'clinician' CHECK (assigned_to IN ('clinician', 'front_desk', 'nurse_triage')),
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    -- Set when a patient message is waiting for a human answer; cleared when a clinician or staff member replies.
    awaiting_since      timestamptz,
    -- Doctor Agent working state (clarifying questions asked, pre-visit interview position).
    agent_state         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_message_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX communication_threads_patient_idx ON communication_threads (patient_id, last_message_at DESC);
CREATE INDEX communication_threads_practitioner_idx ON communication_threads (practitioner_id) WHERE status = 'open';
CREATE UNIQUE INDEX communication_threads_previsit_uq ON communication_threads (appointment_id) WHERE kind = 'previsit';
CREATE UNIQUE INDEX communication_threads_followup_uq ON communication_threads (care_plan_id) WHERE kind = 'followup';

-- Who takes part in a thread, and how far each has read (read receipts).
CREATE TABLE communication_participants (
    thread_id       uuid NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES users(id),
    role            text NOT NULL CHECK (role IN ('patient', 'clinician', 'staff', 'care_coordinator')),
    last_read_seq   bigint NOT NULL DEFAULT 0,
    last_read_at    timestamptz,
    joined_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (thread_id, user_id)
);
CREATE INDEX communication_participants_user_idx ON communication_participants (user_id);

-- One message (FHIR Communication).
CREATE TABLE communications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Rows written in one transaction share now(); seq is the true order.
    seq             bigserial NOT NULL UNIQUE,
    thread_id       uuid NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    author_user_id  uuid REFERENCES users(id),
    -- agent: the clinician's Doctor Agent. system: safety guidance and notices.
    author_kind     text NOT NULL CHECK (author_kind IN ('patient', 'clinician', 'staff', 'agent', 'system')),
    author_label    text NOT NULL,
    body            text NOT NULL,
    -- Structured extras: {"kind": "emergency" | "previsit_question" | "checkin" | "education" | "handoff" | ...}
    payload         jsonb,
    -- Triage of a patient message.
    category        text,
    priority        text CHECK (priority IN ('urgent', 'routine')),
    triage_reason   text,
    produced_by     text,
    model           text,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX communications_thread_idx ON communications (thread_id, seq);

-- Replies waiting for a human: AI drafts a clinician asked for, and Doctor Agent answers that need approval.
-- Never visible to the patient. Sending one creates a communications row authored by the clinician.
CREATE TABLE communication_drafts (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id               uuid NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    patient_id              uuid NOT NULL REFERENCES patients(id),
    requested_by            uuid REFERENCES users(id),
    source                  text NOT NULL CHECK (source IN ('ai_draft', 'agent_pending_approval')),
    body                    text NOT NULL,
    grounding               jsonb NOT NULL DEFAULT '[]'::jsonb,
    produced_by             text NOT NULL,
    model                   text,
    status                  text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'discarded')),
    sent_communication_id   uuid REFERENCES communications(id),
    created_at              timestamptz NOT NULL DEFAULT now(),
    decided_by              uuid REFERENCES users(id),
    decided_at              timestamptz
);
CREATE INDEX communication_drafts_thread_idx ON communication_drafts (thread_id) WHERE status = 'draft';

-- Approved patient education the Doctor Agent may share verbatim (FHIR DocumentReference, education category).
CREATE TABLE education_content (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    topic           text NOT NULL CHECK (topic IN ('side_effect', 'general')),
    title           text NOT NULL,
    body            text NOT NULL,
    -- Matching: a side-effect item applies when one of `symptoms` is in the message and one of `medications`
    -- is in the message or on the patient's active care plan.
    medications     text[] NOT NULL DEFAULT '{}',
    symptoms        text[] NOT NULL DEFAULT '{}',
    status          text NOT NULL DEFAULT 'approved' CHECK (status IN ('approved', 'retired')),
    approved_by     uuid REFERENCES users(id),
    approved_at     timestamptz NOT NULL DEFAULT now()
);

-- Pre-visit interview answers (FHIR QuestionnaireResponse, one row per item).
CREATE TABLE questionnaire_responses (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    practitioner_id     uuid NOT NULL REFERENCES practitioners(id),
    appointment_id      uuid NOT NULL REFERENCES appointments(id),
    thread_id           uuid NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    question_id         text NOT NULL,
    question_text       text NOT NULL,
    answer_text         text NOT NULL,
    communication_id    uuid REFERENCES communications(id),
    mentions_symptoms   boolean NOT NULL DEFAULT false,
    screen_level        text NOT NULL DEFAULT 'none',
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (appointment_id, question_id)
);

-- Scheduled follow-up check-ins from a clinician's protocol (FHIR CommunicationRequest).
-- There are no background workers: due rows are sent when the patient or clinician opens messaging.
CREATE TABLE communication_requests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid NOT NULL REFERENCES patients(id),
    practitioner_id     uuid NOT NULL REFERENCES practitioners(id),
    care_plan_id        uuid NOT NULL REFERENCES care_plans(id),
    task_id             uuid NOT NULL REFERENCES care_plan_tasks(id) ON DELETE CASCADE,
    step_day            integer NOT NULL,
    action              text NOT NULL,
    due_on              date NOT NULL,
    status              text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'sent', 'skipped')),
    communication_id    uuid REFERENCES communications(id),
    sent_at             timestamptz,
    UNIQUE (task_id, step_day)
);
CREATE INDEX communication_requests_due_idx ON communication_requests (patient_id, due_on) WHERE status = 'scheduled';
