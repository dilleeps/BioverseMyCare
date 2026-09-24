# Bioverse Architecture

## The six layers

Users see one experience. Underneath, the platform is organized into six layers. Each layer depends only on the layers below it.

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1  EXPERIENCE                                                 │
│ Bioverse AI Front Door. Voice + text. "Tell me what you need."      │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 2  CARE JOURNEY                                               │
│ Discover → Intake → Navigate → Book → Prepare → Visit → Results     │
│ → Care Plan → Follow-up                                             │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 3  CLINICAL                                                   │
│ Doctor Agent → Clinician Workspace → Evidence Assistant             │
│ → Clinical Review                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 4  ECOSYSTEM                                                  │
│ Hospitals → Doctors → Labs → Pharmacies → Specialists → Insurance   │
│ → Research                                                          │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 5  AGENTS                                                     │
│ Patient | Intake | Care Navigator | Scheduling | Doctor | Evidence  │
│ | Results | Follow-up | Hospital                                    │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 6  FOUNDATION                                                 │
│ AI Platform → Data → FHIR → Identity → Security → Consent           │
│ → Governance → Audit                                                │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer 1: Experience

The single entry point. One conversation surface across web, mobile and voice. The user never selects a module. The Patient Agent interprets intent and hands off to the right journey step. Hybrid UI means the conversation can render structured widgets (appointment slots, a checklist, a lab trend chart) inline rather than forcing everything into text.

### Layer 2: Care Journey

The patient-facing workflow modules that move a person from "something is wrong" to "this is resolved and followed up." Every step produces structured data that the next step consumes. Intake produces a clinician-ready summary. Navigation produces a booking. The visit produces a summary and tasks. Results produce a reviewed explanation. The care plan produces tracked tasks.

### Layer 3: Clinical

The clinician-facing modules. The Doctor Agent extends a physician's reach before and after the visit. The Clinician Workspace is the cockpit for the visit itself. The Evidence Assistant grounds decisions in cited sources. Clinical Review is the human-in-the-loop gate that every patient-facing clinical output passes through when policy requires it.

### Layer 4: Ecosystem

The institutions and services that Bioverse connects. Bioverse does not replace hospitals, labs or pharmacies. It orchestrates across them. This layer is where the Hospital and Health System module, Referral Manager, Pharmacy, Billing and Coverage, and Research modules live.

### Layer 5: Agents

Specialized agents with narrow responsibilities, coordinated by an orchestrator. See [03-agents.md](03-agents.md). Agents are an implementation detail the patient never sees. The user experiences one Bioverse.

### Layer 6: Foundation

The AI platform (orchestration, retrieval, governance), the data platform (longitudinal record, FHIR store), identity and access, security, consent, audit and traceability. Everything above depends on this layer. Nothing in this layer is optional.

## The interaction loop

Every AI action in Bioverse follows the same loop:

```
Ask ──▶ Understand ──▶ Confirm ──▶ Act ──▶ Show Result
```

| Step | What happens | Example |
| --- | --- | --- |
| Ask | The user expresses a need in their own words, by voice or text | "I've had chest discomfort since yesterday." |
| Understand | The agent classifies intent, extracts entities, checks context and detects red flags | Symptom: chest discomfort. Onset: 1 day. Red flag: possible cardiac. |
| Confirm | The agent asks targeted follow-ups and confirms its understanding before acting | "Is the discomfort present right now? Any shortness of breath, sweating or pain in your arm or jaw?" |
| Act | The agent takes the appropriate action, escalating when required | Red flag confirmed → direct to emergency services and notify the care team. Otherwise → intake and routing. |
| Show Result | The user sees what was done and what happens next | "I've documented your symptoms and found the earliest cardiology slot. Here is what to do before then." |

Confirm is not optional for consequential actions. Booking, cancelling, sharing records, sending messages to a clinician and any clinical recommendation require explicit confirmation.

## The clinical review loop

Any AI output that is clinical in nature and destined for a patient passes through:

```
AI Draft ──▶ Clinician Review ──▶ Clinician Edit ──▶ Approve ──▶ Publish
```

Which outputs require review is a policy decision configured per organization, per specialty and per output type. The default is conservative. See [04-safety-and-governance.md](04-safety-and-governance.md) for the review matrix.

## Core domain model

The platform is FHIR-aligned from the start. The core entities and their FHIR counterparts:

| Bioverse concept | FHIR resource | Notes |
| --- | --- | --- |
| Person / Patient | Patient, RelatedPerson | RelatedPerson covers caregivers and family proxies |
| Clinician | Practitioner, PractitionerRole | PractitionerRole links a clinician to an organization, specialty and location |
| Hospital / Department | Organization, Location, HealthcareService | HealthcareService models bookable services |
| Appointment | Appointment, Slot, Schedule | Slot and Schedule feed availability search |
| Visit | Encounter | Links intake, notes, orders and results |
| Intake | QuestionnaireResponse, Condition, Observation | Dynamic questionnaire captured as QuestionnaireResponse |
| Diagnosis / Condition | Condition | |
| Medication | MedicationRequest, MedicationStatement | Request is the prescription. Statement is what the patient reports taking. |
| Allergy | AllergyIntolerance | |
| Lab result | Observation, DiagnosticReport | Coded with LOINC |
| Imaging | ImagingStudy, DiagnosticReport | |
| Procedure | Procedure | Coded with CPT / SNOMED |
| Immunization | Immunization | |
| Referral | ServiceRequest, Task | Task tracks the closed loop |
| Care plan | CarePlan, Goal, Task | Task is the unit of patient work |
| Message | Communication, CommunicationRequest | |
| Document | DocumentReference, Binary | Uploaded reports, discharge summaries |
| Consent | Consent | |
| Coverage / Claim | Coverage, Claim, ExplanationOfBenefit | |
| Research | ResearchStudy, ResearchSubject | |
| Audit | AuditEvent, Provenance | Provenance records which agent or human produced each artifact |

See [05-interoperability.md](05-interoperability.md) for the integration strategy.

## Cross-cutting concerns

**Context management.** Every agent call carries three contexts: patient context (who, history, preferences, consents), clinical context (current encounter, active problems, recent results) and organizational context (which tenant, which policies, which workflows). Context is assembled by the platform, not by individual agents, so that access control is enforced once.

**Traceability.** Every AI-produced artifact carries provenance: which agent, which model version, which prompt version, which sources, which human reviewed it. This is what makes AI decision traceability and incident investigation possible.

**Tenancy.** Hospitals and health systems are tenants. Data isolation is at the tenant boundary. Patients can hold records across tenants under their own consent.

**Escalation.** Every agent has a defined escalation path to a human: staff queue, care coordinator, clinician or emergency services. An agent that cannot resolve a request within its remit hands off rather than guessing.

**Multilingual.** Language is a first-class user attribute that flows into conversation, documents, provider matching and messaging.

## Technology posture

This blueprint is technology-neutral. The decisions that must hold regardless of stack:

- A FHIR-native data layer, not a relational schema retrofitted to FHIR later.
- An agent orchestration layer with tool calling, a workflow engine and retrieval-augmented generation over governed knowledge bases.
- Model routing so that different tasks can use different models, and models can be swapped without rewriting agents.
- A single identity and access layer with role-based access control and multi-factor authentication for clinicians and staff.
- Immutable audit logs and provenance for every read and write of protected health information and every AI action.
- SaaS platform billing kept separate from healthcare patient billing. See [decisions/003](decisions/003-separate-saas-billing-from-patient-billing.md).
