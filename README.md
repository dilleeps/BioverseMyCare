# Bioverse One

**One place for your healthcare.**

Bioverse is not a healthcare chatbot. Bioverse is an AI-powered healthcare companion and orchestration platform that connects people, clinicians, hospitals and healthcare services across the entire care journey.

The patient says what they need. Bioverse helps them understand, decide, connect, act and follow through. The sophistication stays under the hood.

## What this repository holds

The platform blueprint, and a working first slice of it: a React web app, a Python (FastAPI) API, and a PostgreSQL database.

| Path | What it is |
| --- | --- |
| [apps/web](apps/web) | React app (Vite, plain JavaScript). Patient front door, care navigator, care plan, results, My Health Story, clinician workspace, Doctor Agent settings |
| [apps/api](apps/api) | FastAPI service. Orchestrator, red-flag rules, triage agent (Claude or rules), scheduling, records, review queue, audit trail |
| [apps/api/bioverse/db/migrations](apps/api/bioverse/db/migrations) | Postgres schema, one table per FHIR-aligned resource |
| [deploy/gcp](deploy/gcp) | Google Cloud deployment for project `bioverseone-509616`: Cloud Run, Cloud SQL, Secret Manager |
| [docs](docs) | The blueprint documents below |

## Run it locally

You need Node 20+, Python 3.11+, and PostgreSQL 16 (or Docker for the included Compose file).

```bash
# 1. Database
docker compose up -d postgres

# 2. API on :8000
cd apps/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                  # add ANTHROPIC_API_KEY to use Claude; without it, rules mode
python -m bioverse.db.migrate
python -m bioverse.db.seed            # demo tenant: Northside Health
uvicorn bioverse.main:app --reload --port 8000

# 3. Web app on :5173, in a second terminal
cd apps/web
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server forwards every `/api` request to the API on port 8000, so the browser sees one origin. Use the selector in the top right to switch between the demo patient, Maya Thornton, and the demo clinician, Dr. Adaeze Okafor.

Things to try:

- Type "I've had chest discomfort since yesterday". Bioverse runs a safety check first. Answer "None of these" to get cardiology options and book one. Pick a symptom instead to see the emergency path, then switch to Dr. Okafor to find the red flag at the top of her review queue.
- Type "I have an itchy rash". Dermatology options come back ranked by language match, coverage, then earliest time.
- As Dr. Okafor, edit and approve Jun Park's HbA1c explanation. Patients never see an AI draft before a clinician approves it.

Run the API tests (they reset the `bioverse_test` database):

```bash
cd apps/api && python -m pytest
```

To serve everything from one process like production, run `npm run build` in `apps/web`, then start the API. It serves the built app at `/`.

**The sign-in is a demo.** The identity selector sends a header the API trusts. Replace it with real authentication before any real patient data goes near this. See [deploy/gcp/README.md](deploy/gcp/README.md#before-any-real-patient-data).

## The blueprint

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

Phase 1 vertical slice in code: front door with red-flag screening and safety checks, intake and routing, care navigation and booking, care plan, results with clinician-reviewed explanations, My Health Story, clinician workspace with pre-visit brief and review queue, and Doctor Agent configuration with organization-locked rules. Every action is written to an append-only audit trail.

Not built yet: real authentication, EHR integration, the Evidence Assistant's licensed sources, messaging, referrals, pharmacy and billing. See the [roadmap](docs/06-roadmap.md) for the sequence.
