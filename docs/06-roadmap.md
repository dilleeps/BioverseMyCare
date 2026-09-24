# Bioverse Roadmap

The platform is large. Sequencing is the strategy. Each phase delivers something a patient, clinician or hospital can use on its own, and each phase creates the demand and the data the next phase needs.

Foundation work (Trust and Safety, Interoperability, AI Platform, tenancy) begins in Phase 0 and continues in every phase. It is never "done."

## Phase 0: Foundation

**Goal.** A secure, FHIR-native, multi-tenant platform with an agent orchestrator and governance, with no patient-facing features yet.

**Deliverables.**
- FHIR data store and API gateway with tenant scoping, consent checks and audit logging
- Identity and access: patient identity, clinician credentialing, RBAC, MFA
- Agent orchestrator with tool registry, handoff protocol, provenance recording
- Model registry, prompt versioning, evaluation harness, guardrails
- Red-flag ruleset v1, clinician-owned, with test cases
- Terminology service for ICD-10, SNOMED CT, LOINC, RxNorm, CPT
- Security and privacy program: policies, incident process, retention configuration

**Exit criteria.** An internal agent can read and write FHIR resources under consent and RBAC with full provenance, and every action appears in the audit log.

## Phase 1: The Front Door

**Goal.** A patient can describe a need and end up with the right appointment booked, with the clinician briefed.

**Modules.** AI Front Door, Intake, Care Navigator, Appointment and Visit Navigator (before and after visit), Hospital and Health System (directory only), Patient, Intake, Care Navigator and Scheduling agents.

**Deliverables.**
- Voice and text conversation with intent routing, red-flag detection and multilingual support
- Dynamic intake producing patient and clinician summaries
- Provider matching on specialty, location, language and accessibility
- Booking, rescheduling, cancellation and waitlist against a connected scheduling system
- Pre-visit checklist, reminders, directions; post-visit summary and tasks
- Staff review queue for moderate-urgency intakes and escalations

**Pilot shape.** One health system, one or two departments, scheduling integration only.

**Success measures.**
- Share of conversations that end in a completed booking or a clear next step
- Red-flag detection sensitivity against clinician-labelled test sets
- Clinician rating of intake summary usefulness
- Patient task completion for pre-visit checklists

## Phase 2: The Persistent Relationship

**Goal.** Bioverse stays useful between visits. The patient's health story lives in Bioverse.

**Modules.** Patient Health Record, Results and Report Assistant, Care Plan, Personal Health AI (v1), Billing and Coverage (eligibility only), Family and Caregiver (basic dependents), Results and Follow-up agents, patient analytics.

**Deliverables.**
- EHR read under SMART on FHIR, plus patient-uploaded documents, into one timeline
- Result extraction, abnormal highlighting, trends, plain-language explanation with clinician review queue
- Care plans with tasks, reminders, progress and missed-task alerts
- "What happened with my health this year?" summary
- Coverage eligibility informing provider matching
- Parent and dependent profiles

**Success measures.**
- Share of abnormal results with a clinician-approved explanation delivered to the patient within the target window
- Care-plan task completion rate
- Monthly active use between visits

## Phase 3: The Clinician Side

**Goal.** Clinicians adopt Bioverse because it saves them time and extends their reach.

**Modules.** Clinician Workspace, Doctor Agent, Evidence Assistant, Referral Manager, Messaging and Care Team, Doctor and Evidence agents, clinician analytics.

**Deliverables.**
- Clinician Workspace with patient overview, pre-visit briefing and AI drafting under AI Draft → Review → Edit → Approve → Publish
- EHR write-back of approved notes, referrals and instructions
- Doctor Agent configuration and pre- and post-visit operation
- Evidence Assistant with citations, dates and quality indicators over licensed sources
- Closed-loop referral tracking
- Secure messaging with AI-assisted drafts and triage

**Success measures.**
- Clinician time saved per visit on documentation
- Doctor Agent question resolution rate without escalation, and escalation appropriateness
- Referral loop closure rate and time to specialist appointment
- Evidence Assistant citation accuracy in clinician review samples

## Phase 4: The Hospital Platform

**Goal.** A health system can deploy and configure Bioverse as its own platform.

**Modules.** Hospital and Health System (operations and Hospital AI), Organization Platform (full configuration), Appointment and Visit Navigator (during visit), Hospital agent, hospital analytics.

**Deliverables.**
- Digital check-in, queue status, estimated wait, wayfinding
- Patient flow, capacity, utilization, referral leakage and staff workload dashboards
- Staff, department, scheduling, referral and care coordination assistants
- Tenant configuration: branding, custom workflows, custom agents within governance, custom knowledge bases, custom forms, custom care pathways and escalation rules
- Bulk FHIR onboarding

**Success measures.**
- Time to onboard a new tenant
- Wait-time and no-show reduction in pilot departments
- Referral leakage reduction

## Phase 5: The Ecosystem

**Goal.** Bioverse covers the whole of health, not only sick-care.

**Modules.** Pharmacy, Wellness and Prevention, Research and Clinical Trials, Family and Caregiver (full), Billing and Coverage (full), Personal Health AI (mature).

**Deliverables.**
- Prescription status, refills, interaction warnings, pharmacist communication
- Preventive reminders, screenings, wellness goals and tracking
- Consented trial matching and enrollment workflow
- Caregiver permissions, proxy communication, elder and child workflows
- Bills, estimates, payment plans, financial assistance

**Success measures.**
- Preventive-care gap closure rate
- Medication adherence in care plans
- Caregiver-managed patient engagement

## Cross-phase commitments

| Commitment | Applies from |
| --- | --- |
| Every AI action recorded with provenance | Phase 0 |
| Red-flag detection on every patient interaction | Phase 1 |
| Clinical review matrix enforced by the workflow engine | Phase 2 |
| Bias monitoring across urgency, matching and adherence | Phase 1, expanding each phase |
| Clinician-reviewed evaluation sets refreshed each release | Phase 1 |
| Security and privacy review before each phase launch | Every phase |

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Building all 25 modules at once and shipping none well | Strict phase gating. Phase 1 pilot must hit its success measures before Phase 2 scales. |
| Hospital integration slower than planned | Phase 1 depends only on scheduling integration. The staged adoption path in [05-interoperability.md](05-interoperability.md) keeps each step independently valuable. |
| Clinician distrust of AI outputs | Nothing clinical reaches a patient without review by default. Clinicians configure their own agents. Evidence is always cited. |
| Patient-safety incident from a missed red flag | Clinician-owned, versioned ruleset with test cases. Conservative default to escalate. Every miss feeds back into evaluation. |
| Regulatory exposure across jurisdictions | Consent, retention and privacy controls are configurable per tenant and jurisdiction from Phase 0. |
| Agent sprawl into disconnected bots | One orchestrator, one handoff protocol, one provenance model. Agents are registered and cannot exceed their tools. |
