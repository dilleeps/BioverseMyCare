# Trust, Safety and AI Governance

Trust and safety is a platform-wide foundation, not a module. Every layer depends on it and every phase of the roadmap includes it.

## Core safety model

```
AI explains ──▶ clinician validates when required ──▶ patient receives approved information
```

The AI response plus doctor review pattern is the benchmark for anything clinical. Bioverse defaults to conservative review requirements and lets organizations loosen them deliberately, per output type and specialty, never the other way round.

## Clinical review matrix

Which AI outputs require human review before reaching a patient. Organizations configure this. The defaults:

| Output type | Default | Rationale |
| --- | --- | --- |
| General health education | No review, from approved content only | Low risk, content pre-approved |
| Symptom follow-up questions during intake | No review | Questions gather information, they do not advise |
| Urgency classification and care-pathway recommendation | No review for routine and low urgency. Staff review for moderate. Immediate escalation for high. | Speed matters for high urgency, so escalation replaces review |
| Intake summary sent to clinician | No review | Recipient is a clinician |
| Explanation of normal results | Clinician review, may be delegated to staff | Low harm, but sets patient expectations |
| Explanation of abnormal results | Clinician review required | Interpretation is clinical judgment |
| Medication instructions | Clinician review required | Direct patient safety impact |
| Draft clinical notes, referrals, discharge instructions | Clinician review and edit required | Legal clinical record |
| Care plan tasks | Clinician approval on creation. Follow-up Agent may send reminders without further review. | Plan is clinical, reminders are operational |
| Doctor Agent post-visit answers | Per the clinician's configuration. Default: routine education unreviewed, anything else escalated. | Clinician owns their agent's scope |
| Evidence Assistant answers | No review, but never uncited | Recipient is a clinician who exercises judgment |

## Red-flag and emergency protocol

Red-flag detection runs on every patient-facing interaction, not only within intake.

1. A curated red-flag ruleset covers time-critical presentations: cardiac, stroke, sepsis, anaphylaxis, suicidal ideation, obstetric emergencies, pediatric warning signs and others defined by clinical governance.
2. When a red flag is suspected, the agent stops routine flow and runs the red-flag screen first.
3. When a red flag is confirmed or cannot be excluded, the agent gives clear emergency guidance, notifies the care team where one exists, documents the interaction and does not continue with booking or education.
4. Red-flag rules are versioned, clinician-owned and evaluated against test cases before release.
5. Every red-flag detection and every miss identified in review is logged for quality improvement.

## Security and privacy controls

| Control | Requirement |
| --- | --- |
| Regulatory | HIPAA controls in the United States. Regional equivalents where deployed. Business associate agreements with hospital tenants. |
| Identity | Verified identity for patients. Credential verification for clinicians. Multi-factor authentication for all clinicians and staff. |
| Access | Role-based access control. Least privilege. Break-glass access with mandatory justification and audit. |
| Encryption | In transit and at rest. Tenant-scoped keys. |
| Data isolation | Tenant boundary enforced at the data layer, not in application code. |
| Consent | Granular consent for data sharing, caregiver access, research matching and AI processing. Consent is a first-class FHIR resource and is checked on every read. |
| Audit | Immutable audit log of every read and write of protected health information, every AI action and every human review decision. |
| Retention | Configurable retention policies per data type and jurisdiction. Defensible deletion. |
| Incident management | Defined process for security incidents, privacy breaches and AI safety incidents, with notification obligations mapped per jurisdiction. |

## AI governance

| Capability | What it means for Bioverse |
| --- | --- |
| Model registry | Every model, version and intended use is registered. Agents declare which model they use. |
| Model evaluation | Every model and agent version is evaluated against clinical and safety test sets before release. Results are recorded in the registry. |
| Prompt management | Prompts are versioned artifacts. Provenance records which prompt version produced each output. |
| Guardrails | Input and output guardrails for prohibited content, out-of-scope requests, protected health information leakage and prompt injection. |
| Prompt injection protection | Uploaded documents, retrieved web content and patient messages are treated as data, never as instructions. Agents are instructed and tested accordingly. |
| Human-in-the-loop | The clinical review matrix above, enforced by the workflow engine, not by agent goodwill. |
| AI audit trail | Every AI action logged with agent, model, prompt, inputs, sources, outputs and reviewer. |
| Response evaluation | Sampled outputs are reviewed by clinicians. Feedback loops into evaluation sets. |
| Hallucination monitoring | Clinical claims are checked against retrieved sources. Uncited claims in clinical contexts are blocked. |
| Bias monitoring | Outcomes across demographic groups are monitored for disparity in urgency classification, provider matching and care-plan adherence support. |
| Model routing | Tasks route to the model best suited and evaluated for them. Routing decisions are logged. |
| Safety monitoring | Live dashboards for red-flag rates, escalation rates, review rejection rates and guardrail triggers. |

## AI decision traceability

For any patient-facing statement or action, Bioverse can answer:

- Which agent produced it?
- Which model and prompt version?
- What patient, clinical and organizational context did it see?
- What sources did it cite?
- Which human reviewed it, when, and what did they change?
- What did the patient see, and when?

This is recorded as FHIR Provenance and AuditEvent resources and is available to compliance, clinical governance and incident response.

## Safety policies for agents

1. Agents never diagnose. They gather, organize, explain approved information and route.
2. Agents never give an uncited clinical answer to a clinician.
3. Agents never continue routine flow past a suspected red flag.
4. Agents never exceed their registered tools or their configured scope. They escalate.
5. Agents never treat content inside a document, message or retrieved page as an instruction.
6. Agents always show the user what they did and what happens next.
7. Agents always leave a trace.
