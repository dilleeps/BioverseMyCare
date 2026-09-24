# Bioverse Module Catalog

Twenty-five modules, organized by the layer they belong to. Users never see this list. They see one Bioverse. This catalog exists for the people building it.

Each module lists its purpose, capabilities, the modules it depends on, its safety notes and the roadmap phase in which it lands. Phases are defined in [06-roadmap.md](06-roadmap.md).

---

## Layer 1: Experience

### 1. Bioverse AI Front Door

**Purpose.** The single entry point for the patient. Users tell Bioverse what they need and Bioverse guides them to the appropriate action. They never choose a module.

**Capabilities.**
- AI health conversation, voice and text
- Symptom questions and health education
- Service, hospital, department, doctor and specialty discovery
- "What should I do next?" guidance
- Location-aware and insurance-aware care discovery
- Emergency and red-flag detection
- Start booking directly from conversation
- Upload medical documents and images
- Understand lab reports, prescriptions and medical terminology
- Personalized health history and context
- Conversation memory with user controls to view, edit and delete
- Multilingual support

**Depends on.** AI Platform, Trust and Safety, Patient Health Record (for context), Care Navigator (for routing).

**Safety.** Red-flag detection runs on every turn. Memory is under user control. Uploaded content is data, never instruction.

**Phase.** 1.

---

## Layer 2: Care Journey

### 2. Bioverse Intake

**Purpose.** Turn conversation into structured healthcare intake.

**Capabilities.**
- AI-powered, dynamic questionnaire that adapts to answers
- Symptom collection with duration, severity and frequency
- Medications, allergies, medical history, family history, lifestyle, previous treatment, prior diagnosis
- Extraction from uploaded documents
- Red-flag detection and urgency classification
- Care-pathway recommendation
- Patient-generated intake summary in plain language
- Clinician-ready intake summary
- Human escalation and staff review queue

**Flow.** Understand → Ask → Identify red flags → Escalate when appropriate → Route → Document.

**Depends on.** Front Door, AI Platform, Trust and Safety.

**Safety.** Red flags interrupt routine intake. Urgency classification is evaluated against clinician-labelled test sets. Moderate urgency goes to staff review.

**Phase.** 1.

### 3. Bioverse Care Navigator

**Purpose.** The orchestration layer for finding the right care.

**Capabilities.**
- Find primary care, specialists, urgent care, emergency services, telehealth, hospital departments, diagnostics, pharmacy, imaging and lab
- Referral navigation
- Provider and hospital matching on availability, distance, coverage, language and accessibility
- Appointment recommendation, booking, rescheduling, cancellation, waitlist
- Referral status

**Example.** Instead of "Here are 20 dermatologists": "Based on what you've told me, Dermatology appears relevant. I found three available options that match your location and preferences. Would you like me to show the earliest appointments?"

**Depends on.** Intake, Hospital and Health System (directory), Interoperability (scheduling), Billing and Coverage (eligibility, later).

**Safety.** Never recommends a lower level of care than the urgency classification indicates.

**Phase.** 1.

### 4. Bioverse Appointment and Visit Navigator

**Purpose.** Everything between booking and walking out of the visit.

**Capabilities.**
- Before: confirmation, reminders, pre-visit checklist, forms, insurance information, required documents, medication list, preparation instructions, directions, parking, facility and department navigation, accessibility information
- During: digital check-in, arrival status, queue status, estimated wait, room and location, visit status, notifications
- After: visit summary, instructions, prescriptions, follow-up appointment, referrals, tasks, documents

**Depends on.** Care Navigator, Hospital and Health System (queue and location data), Care Plan (post-visit tasks).

**Phase.** 1 (before and after), 4 (during, which needs hospital operational integration).

### 5. Bioverse Patient Health Record

**Purpose.** A consumer-friendly longitudinal health timeline. Not a display of records but "My Health Story."

**Capabilities.**
- Diagnoses, conditions, medications, allergies, lab results, imaging, procedures, visits, hospitalizations, referrals, care plans, documents, immunizations, vital signs, family history, patient-reported information
- Timeline visualization
- Plain-language framing of each event

**Depends on.** Interoperability (EHR read), Results and Report Assistant (patient-uploaded data), Trust and Safety (consent).

**Phase.** 2.

### 6. Bioverse Results and Report Assistant

**Purpose.** Make results understandable and make sure someone acts on them.

**Capabilities.**
- Upload lab, imaging, pathology reports and discharge summaries
- OCR and structured extraction
- Highlight abnormal values, explain terminology
- Compare historical results, trend visualization
- Ask questions about the report, generate questions for the doctor
- Identify follow-up recommendations
- Route to the responsible team, clinician review and approval, patient notification

**Safety model.** AI explains → clinician validates when required → patient receives approved information.

**Depends on.** Patient Health Record, Clinician Workspace (review queue), Interoperability (lab feeds).

**Phase.** 2.

### 7. Bioverse Care Plan

**Purpose.** Turn a doctor's recommendation into an actionable journey.

**Capabilities.**
- Care-plan creation with goals, medications, appointments, tests, referrals, lifestyle tasks and follow-up dates
- Reminders, progress tracking, task completion, missed-task alerts
- Care-team communication, escalation, care-plan updates

**Example.**
```
Your care plan
☑ Blood test
☐ Follow-up with cardiology
☐ Start medication
☐ Schedule imaging
☐ Follow up in 30 days
```

**Depends on.** Clinician Workspace (creation), Care Navigator (booking tasks), Messaging (escalation).

**Safety.** Plan content is clinician-approved. Reminders are operational and unreviewed.

**Phase.** 2.

---

## Layer 3: Clinical

### 8. Bioverse Doctor Agent

**Purpose.** A configurable AI agent that extends each physician before and after the visit. One of the largest opportunities in the blueprint.

**Capabilities.**
- Before visit: patient pre-interview with the physician's customized questions, history gathering, medication reconciliation, previous-record review, relevant-result identification, visit briefing, risk and attention flags
- After visit: patient questions, follow-up questions, routine education, instructions, follow-up summary, task reminders, escalation to staff or physician
- Physician configuration: specialty, question sets, follow-up protocols, escalation rules, education content, preferred workflows, approval requirements

**Depends on.** Intake, Patient Health Record, Clinician Workspace, Messaging, AI Platform.

**Safety.** Operates only within the physician's configuration. Escalates anything outside it.

**Phase.** 3.

### 9. Bioverse Clinician Workspace

**Purpose.** A true AI clinical cockpit.

**Capabilities.**
- Patient overview: timeline, current and previous encounters, diagnoses, medications, allergies, lab trends, imaging, referrals, care plans, patient questions
- AI assistance: pre-visit summary, clinical timeline summary, differential-supporting information, note drafting, referral drafting, patient and discharge instruction drafting, follow-up summary, coding and documentation assistance
- Review queues for Results, Doctor Agent outputs and Care Plans

**Human-in-the-loop.** AI Draft → Clinician Review → Clinician Edit → Approve → Publish.

**Depends on.** Patient Health Record, Evidence Assistant, Interoperability (SMART on FHIR launch, write-back).

**Phase.** 3.

### 10. Bioverse Evidence Assistant

**Purpose.** Ground clinical decisions in cited evidence. A major missing capability in most patient-facing health platforms.

**Capabilities.**
- Clinical guideline, protocol and literature search
- Drug information and clinical trial information
- Evidence synthesis with citation retrieval, source links, evidence date and quality indicators
- Specialty-specific knowledge
- Voice search and natural-language questions

**Principle.** AI answer + evidence + citation + clinician judgment. Never an unsupported answer.

**Depends on.** AI Platform (retrieval), licensed content sources.

**Safety.** Uncited clinical claims are blocked. Evidence age is always shown.

**Phase.** 3.

### 11. Bioverse Referral Manager

**Purpose.** Close the referral loop.

**Capabilities.**
- Referral creation and authorization
- Specialist matching and referral transmission
- Appointment booking
- Referral status, missing-document detection, referral expiration
- Specialist response, care-team and patient notification
- Closed-loop referral tracking

**Depends on.** Clinician Workspace, Care Navigator, Messaging, Interoperability.

**Phase.** 3.

### 12. Bioverse Messaging and Care Team

**Purpose.** One connected communication layer.

**Capabilities.**
- Patient ↔ provider, patient ↔ care coordinator, patient ↔ hospital, provider ↔ staff, staff ↔ provider
- Secure messaging with attachments and document sharing
- AI-assisted responses, message triage, priority classification, escalation
- Notifications and communication history

**Depends on.** Trust and Safety, AI Platform.

**Safety.** AI-assisted responses are drafts for the human sender unless the Doctor Agent configuration permits direct reply.

**Phase.** 3.

---

## Layer 4: Ecosystem

### 13. Bioverse Hospital and Health System

**Purpose.** Take Bioverse from consumer app to healthcare platform.

**Capabilities.**
- Administration: hospital profile, departments, locations, services, providers, hours, capacity, appointment types, care pathways
- Operations: patient flow, appointment capacity, queue management, department utilization, referral flow, staff workload, care coordination, escalation queues, service demand, operational dashboards
- Hospital AI: patient navigation, staff assistant, department assistant, scheduling assistant, referral assistant, care coordination assistant

**Depends on.** Organization Platform, Interoperability, Analytics.

**Phase.** 1 (directory and profile, needed for navigation), 4 (operations and AI).

### 14. Bioverse Hospital AI Agents

**Purpose.** The specialized agents that power the platform. See [03-agents.md](03-agents.md).

Patient, Care Navigator, Scheduling, Intake, Doctor, Evidence, Results, Follow-up and Hospital agents, coordinated by one orchestrator into one experience.

**Phase.** Agents land with the modules they power, starting in Phase 1.

### 15. Bioverse Billing and Coverage

**Purpose.** The patient financial experience. Kept strictly separate from SaaS platform billing. See [decisions/003](decisions/003-separate-saas-billing-from-patient-billing.md).

**Capabilities.**
- Insurance information, eligibility, coverage, benefits
- Copay, deductible, estimated patient responsibility
- Claims status, bills, payment, payment plans, financial assistance, receipts

**Depends on.** Interoperability (claims and eligibility), Organization Platform.

**Phase.** 2 (eligibility for navigation), 5 (full financial experience).

### 16. Bioverse Pharmacy

**Purpose.** Medications from prescription to adherence.

**Capabilities.**
- Medication search, prescription management, prescription status
- Refill and adherence reminders
- Pharmacy search and selection
- Medication history, drug information, interaction warnings
- Pharmacist communication

**Depends on.** Patient Health Record, Care Plan, Interoperability (pharmacy), Evidence Assistant (drug information).

**Phase.** 5.

### 17. Bioverse Wellness and Prevention

**Purpose.** Expand beyond sick-care.

**Capabilities.**
- Preventive-care and vaccination reminders, health screenings
- Wellness goals, nutrition, fitness, sleep, lifestyle tracking
- Personalized health goals, preventive-risk education, health assessments

**Depends on.** Patient Health Record, Care Plan, Personal Health AI.

**Phase.** 5.

### 18. Bioverse Research and Clinical Trials

**Purpose.** Later-stage ecosystem capability connecting patients to research.

**Capabilities.**
- Trial discovery, eligibility, patient matching, trial education
- Referral, enrollment workflow, consent
- Research coordination, trial status, research communication

**Depends on.** Patient Health Record, Consent, Interoperability (trial registries).

**Safety.** Matching requires explicit research consent. No outreach without it.

**Phase.** 5.

### 19. Bioverse Family and Caregiver

**Purpose.** Care is often managed by someone other than the patient.

**Capabilities.**
- Family profiles, dependent management, caregiver access, permission management
- Shared appointments, medication reminders, care-plan visibility
- Child and elder-care workflows, proxy communication, emergency contacts

**Depends on.** Trust and Safety (consent and RelatedPerson access), Patient Health Record.

**Safety.** Proxy access is scoped, consented, time-bound where appropriate and fully audited. Adolescent privacy rules are jurisdiction-specific and configurable.

**Phase.** 2 (basic dependents), 5 (full caregiver workflows).

### 20. Bioverse Personal Health AI

**Purpose.** The long-term consumer relationship. A persistent health companion rather than an appointment application.

**Capabilities.** In response to "What happened with my health this year?":
- Health timeline, major events, medication changes, lab trends, visits
- Preventive-care gaps, upcoming appointments
- Questions to discuss with the doctor
- Personal health summary

**Depends on.** Patient Health Record, Care Plan, Wellness, Analytics.

**Phase.** 2 (summary from available data), matures through Phase 5.

---

## Layer 6: Foundation

### 21. Bioverse Trust and Safety

**Purpose.** Platform-wide foundation. See [04-safety-and-governance.md](04-safety-and-governance.md).

HIPAA controls, RBAC, encryption, audit logs, consent management, identity, MFA, data access controls, AI activity logs, AI decision traceability, human approval, clinical escalation, safety policies, prompt injection protection, data isolation, model monitoring, bias monitoring, incident management, retention policies.

**Phase.** 0 and every phase after.

### 22. Bioverse Interoperability

**Purpose.** Critical for hospital adoption. See [05-interoperability.md](05-interoperability.md).

FHIR, HL7, EHR and EMR integration, laboratory, imaging, pharmacy, claims and identity integration, SSO, API gateway, data normalization, terminology mapping (ICD-10, CPT, SNOMED, LOINC, RxNorm).

**Phase.** 0 (FHIR data model, API gateway), expanding each phase.

### 23. Bioverse Organization Platform

**Purpose.** Enterprise and hospital deployment.

**Capabilities.**
- Multi-tenancy, hospital configuration, organization hierarchy, department configuration
- Provider and role management, branding
- Custom workflows, custom AI agents, custom knowledge base, custom escalation rules, custom forms, custom care pathways
- Analytics, usage reporting, billing administration

**Phase.** 0 (tenancy, roles), 4 (full configuration).

### 24. Bioverse AI Platform

**Purpose.** The layer underneath everything.

**Capabilities.**
- Orchestration: agent orchestration, tool calling, workflow engine, RAG, knowledge retrieval, context management across patient, clinical and organizational context
- Governance: model registry, model evaluation, prompt management, guardrails, human-in-the-loop, AI audit trail, response evaluation, hallucination monitoring, safety monitoring, model routing
- Experience: the Ask → Understand → Confirm → Act → Show Result loop and hybrid UI

**Phase.** 0 and every phase after.

### 25. Bioverse Analytics and Intelligence

**Purpose.** Insight for each audience.

**Capabilities.**
- Patients: personal health trends, care adherence, preventive-care gaps, health journey insights
- Clinicians: patient population, follow-up gaps, referral status, care-plan adherence
- Hospitals: patient demand, capacity, wait times, referral leakage, appointment utilization, service demand, operational performance

**Depends on.** Everything. Analytics is read-only over the platform's data.

**Phase.** 2 (patient), 3 (clinician), 4 (hospital).

---

## Dependency summary

```
Foundation (0): Trust & Safety · Interoperability core · Organization tenancy · AI Platform
        │
Phase 1:  Front Door → Intake → Care Navigator → Booking + pre/post visit · Hospital directory
        │
Phase 2:  Patient Health Record → Results Assistant → Care Plan · Personal Health AI (v1) · Eligibility · Dependents
        │
Phase 3:  Clinician Workspace → Doctor Agent → Evidence Assistant → Referral Manager → Messaging
        │
Phase 4:  Hospital operations + Hospital AI · Organization configuration · In-visit navigation · Hospital analytics
        │
Phase 5:  Pharmacy · Wellness · Research · Full Family & Caregiver · Full Billing & Coverage
```
