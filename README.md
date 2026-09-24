# Bioverse One

**One place for your healthcare.**

Bioverse is not a healthcare chatbot. Bioverse is an AI-powered healthcare companion and orchestration platform that connects people, clinicians, hospitals and healthcare services across the entire care journey.

The patient says what they need. Bioverse helps them understand, decide, connect, act and follow through. The sophistication stays under the hood.

## What this repository holds

This repository is the platform blueprint for Bioverse. It defines the product vision, the six-layer architecture, the module catalog, the agent model, the safety and governance foundation, the interoperability plan and a phased delivery roadmap. Implementation will build on these documents.

| Document | Purpose |
| --- | --- |
| [docs/00-vision.md](docs/00-vision.md) | Why Bioverse exists, the strategic position, the consumer promise |
| [docs/01-architecture.md](docs/01-architecture.md) | The six layers, the interaction philosophy, the core domain model |
| [docs/02-modules.md](docs/02-modules.md) | The 25-module catalog with capabilities, dependencies and safety notes |
| [docs/03-agents.md](docs/03-agents.md) | The nine specialized agents and how they coordinate as one experience |
| [docs/04-safety-and-governance.md](docs/04-safety-and-governance.md) | Trust, safety, human-in-the-loop and AI governance as platform foundation |
| [docs/05-interoperability.md](docs/05-interoperability.md) | FHIR, HL7, terminology and integration strategy |
| [docs/06-roadmap.md](docs/06-roadmap.md) | Phased delivery plan, milestones and success measures |
| [docs/decisions/](docs/decisions/) | Architecture decision records |

## The six layers at a glance

```
LAYER 1  EXPERIENCE     Bioverse AI. "Tell me what you need."
LAYER 2  CARE JOURNEY   Discover → Intake → Navigate → Book → Prepare → Visit → Results → Care Plan → Follow-up
LAYER 3  CLINICAL       Doctor Agent → Clinician Workspace → Evidence Assistant → Clinical Review
LAYER 4  ECOSYSTEM      Hospitals → Doctors → Labs → Pharmacies → Specialists → Insurance → Research
LAYER 5  AGENTS         Patient | Intake | Care Navigator | Scheduling | Doctor | Evidence | Results | Follow-up | Hospital
LAYER 6  FOUNDATION     AI → Data → FHIR → Identity → Security → Consent → Governance → Audit
```

## Design principles

1. **One front door.** Users never choose a module. They describe a need and Bioverse routes them.
2. **Ask → Understand → Confirm → Act → Show Result.** Every AI action follows this loop, and the user always sees what happened.
3. **AI drafts, clinicians decide.** Anything clinical goes through a human before it reaches a patient when policy requires it.
4. **Close every loop.** Referrals, results, tasks and follow-ups are tracked to completion, never left dangling.
5. **Safety is foundation, not a feature.** Red-flag detection, consent, audit and traceability are built into every layer.
6. **Evidence with citations.** Clinical answers carry sources, dates and quality indicators, never unsupported assertions.

## Status

Blueprint stage. See the [roadmap](docs/06-roadmap.md) for the delivery sequence.
