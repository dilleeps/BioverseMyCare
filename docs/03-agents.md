# Bioverse Agents

## One experience, many agents

Bioverse is powered by specialized agents. The patient never meets them individually. The key design rule: **do not build nine disconnected bots.** Build one coordinated experience powered by specialized agents underneath.

The orchestrator owns the conversation. Agents own tasks. The orchestrator decides which agent handles a step, passes it the assembled context, receives a structured result, and decides what the user sees next.

```
                        ┌──────────────────────┐
   user (voice/text) ──▶│     Orchestrator     │──▶ Hybrid UI
                        │  intent · context ·  │
                        │  routing · confirm   │
                        └──────────┬───────────┘
                                   │
   ┌──────────┬──────────┬─────────┼─────────┬──────────┬──────────┐
   ▼          ▼          ▼         ▼         ▼          ▼          ▼
Patient   Intake    Care Nav  Scheduling  Doctor   Evidence   Results
 Agent     Agent      Agent      Agent     Agent     Agent      Agent
                                   │
                            ┌──────┴──────┐
                            ▼             ▼
                        Follow-up      Hospital
                          Agent          Agent
```

## Agent catalog

| Agent | Responsibility | Primary tools | Hands off to | Escalates to |
| --- | --- | --- | --- | --- |
| **Patient Agent** | Understands what the patient needs. Owns the conversational front door, health education, document understanding and personal health summaries. | Intent classification, patient record read, document OCR, knowledge retrieval, conversation memory | Intake, Care Navigator, Results, Follow-up | Red flags → emergency guidance and care team notification |
| **Intake Agent** | Converts conversation into structured intake. Dynamic questioning, red-flag detection, urgency classification, care-pathway recommendation. | Questionnaire engine, symptom ontology, red-flag rules, document extraction, summary generation | Care Navigator, Doctor Agent (visit briefing) | Staff review queue, clinician, emergency |
| **Care Navigator Agent** | Finds the right care. Matches specialty, provider, hospital, location, insurance, language and accessibility. | Provider directory, HealthcareService search, coverage eligibility, distance, referral rules | Scheduling | Care coordinator |
| **Scheduling Agent** | Books, reschedules, cancels, waitlists. Manages reminders and pre-visit checklists. | Slot and Schedule search, Appointment write, notification service | Follow-up (post-visit) | Front-desk staff |
| **Doctor Agent** | Extends a specific clinician. Pre-visit interview with the physician's own question set, medication reconciliation, visit briefing, post-visit questions and instructions. | Physician configuration, patient record read, Encounter write, education content library | Clinician Workspace, Results | Staff, then the physician, per configured rules |
| **Evidence Agent** | Retrieves clinical guidelines, protocols, literature, drug information and trial information with citations, dates and quality indicators. | Guideline index, literature index, drug label index, trial registry, citation formatter | Clinician Workspace, Doctor Agent | Never gives an uncited clinical answer. Falls back to "no evidence found." |
| **Results Agent** | Coordinates results. Extracts and structures reports, flags abnormals, explains terminology, compares history, routes to the responsible clinician, releases approved explanations. | OCR, structured extraction, LOINC mapping, reference ranges, trend engine, review queue | Clinical Review, Follow-up | Responsible clinician, care team |
| **Follow-up Agent** | Manages next steps. Care-plan tasks, reminders, missed-task alerts, referral status, follow-up scheduling. | CarePlan and Task read/write, reminder engine, referral tracker | Scheduling, Messaging | Care coordinator, clinician |
| **Hospital Agent** | Coordinates institutional services. Patient flow, queue status, department utilization, staff assistance, scheduling capacity. | Operational data, queue system, capacity model, staff directory | Scheduling, Care Navigator | Operations staff |

## Handoff protocol

A handoff between agents is a structured message, not a conversation. It carries:

- **Intent** the receiving agent must fulfil.
- **Context reference** so the receiving agent reads the same patient, clinical and organizational context.
- **Structured payload** from the sending agent (an intake summary, a matched provider list, a result set).
- **Confirmation state** recording what the user has already confirmed so the receiving agent does not re-ask.
- **Provenance** of the sending agent and its outputs.

The orchestrator logs every handoff. This is what makes an end-to-end trace of a care journey possible.

## Worked example: chest discomfort

> User: "I've had chest discomfort since yesterday."

1. **Orchestrator** classifies intent as symptom report and routes to the Intake Agent with patient context.
2. **Intake Agent** recognizes a potential cardiac red flag. Before anything else it asks the red-flag screen: is it present now, shortness of breath, sweating, radiating pain, history of heart disease.
3. If red flags are **present**, the Intake Agent escalates immediately: clear guidance to contact emergency services, care team notified, conversation documented. It does not continue routine intake.
4. If red flags are **absent**, the Intake Agent gathers duration, severity, triggers, medications, history, and produces two summaries: one in plain language for the patient, one clinician-ready.
5. **Orchestrator** confirms with the user: "Based on what you've shared, this appears appropriate for a same-week primary care or cardiology visit. Shall I find options?"
6. **Care Navigator Agent** matches on specialty, location, coverage and language and returns three options.
7. **Scheduling Agent** shows the earliest slots. On confirmation it books, sends confirmation and starts the pre-visit checklist.
8. **Doctor Agent** for the booked clinician receives the intake summary and prepares a visit briefing with attention flags.
9. After the visit, **Follow-up Agent** turns the clinician's plan into tasks and reminders and tracks them to completion.

Six agents participated. The patient had one conversation.

## Worked example: a lab report

> User uploads a PDF of a lipid panel.

1. **Patient Agent** recognizes a document upload and routes to the Results Agent.
2. **Results Agent** extracts values, maps them to LOINC, applies reference ranges, flags an elevated LDL, compares to the patient's two prior panels, and drafts a plain-language explanation plus three questions to ask the doctor.
3. Because organizational policy requires clinician review of abnormal result explanations, the draft enters the **Clinical Review** queue for the responsible clinician.
4. The clinician approves with a small edit. The patient is notified and sees the approved explanation, the trend, and the questions.
5. **Follow-up Agent** notes the clinician's recommendation to recheck in three months and schedules a reminder.

## Physician configuration of the Doctor Agent

Each clinician configures their own agent within organizational policy:

| Setting | Examples |
| --- | --- |
| Specialty | Cardiology, dermatology, pediatrics |
| Pre-visit question sets | Specialty defaults plus the clinician's own additions |
| Follow-up protocols | Post-procedure day 1, day 7, day 30 check-ins |
| Escalation rules | Which patient messages go to staff, which go directly to the clinician, which trigger urgent alerts |
| Education content | Approved handouts and instructions the agent may share |
| Preferred workflows | Note templates, referral templates, instruction templates |
| Approval requirements | Which agent outputs the clinician must approve before release |

The Doctor Agent never exceeds its configuration. If a patient asks something outside the configured scope, it escalates.

## Agent governance

Every agent is registered in the model registry with its tools, permitted actions, prompt version and evaluation results. Agents cannot call tools they are not registered for. Agent activity logs are retained and searchable. See [04-safety-and-governance.md](04-safety-and-governance.md).
