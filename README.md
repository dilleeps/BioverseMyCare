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

Every module in the [module catalog](docs/02-modules.md) has a working first version, wired into one
database, one API, one front door and one audit trail. Switch identities in the top-right corner to see
each role; **More** lists everything that role can open.

| Who | What they can do |
| --- | --- |
| Patient (Maya Thornton) | Ask Bioverse by typing, voice or photo (medicine box, skin, paper report) with red-flag screening; Today companion with dose, visit and check-in reminders; home vitals with meter photos, device import and abnormal-reading alerts; online consultations by message or video with verified clinicians; order medicines for delivery; insurance card with QR, eligibility and benefits; nutrition and food scan, weight coach, mood and anxiety checks, challenges and rewards; health fact check; specialist AI agents; find your way in the hospital; notifications by app, email or text; plus booking, visits, referrals, care plan, results, My Health Story, messages, pharmacy, bills, wellness, family, research, privacy |
| Senior mode (Rana Haddad) | Large text and buttons, four big actions on the home screen, read-aloud replies |
| Caregiver (David Thornton) | Everything a patient has, plus acting for the people who granted access |
| Clinician (Dr. Adaeze Okafor) | Workspace with pre-visit brief, review queue and panels for home vitals, between-visit adherence, nutrition and weight, mood and anxiety, online consults; consult queue and video room; monitoring plans; public specialist agent; inbox, clinic queue, referrals, care plans, refills, Evidence Assistant, research, analytics, Doctor Agent settings, break-glass, incidents |
| Clinician (Dr. Nadia Benali) | Dermatology online consults and her license page |
| Front desk | Inbox, clinic queue, referrals, insurance eligibility and card scanning, claims |
| Pharmacist (Lena Marsh) | Order verification queue with interaction and allergy checks, packing, dispatch and delivery |
| Medical student (Priya Raman) | De-identified case library with a tutor, quizzes, evidence search; never sees identifiable records |
| Hospital admin (Northside Operations) | Operations, Hospital Agent, analytics, organization, credentialing, payer connections, specialist agent approvals, wayfinding closures and signs, scheduled jobs, pathways, financial assistance, lab import, compliance audit, retention, incidents, AI governance |

AI features use Claude when an Anthropic key is configured and a patient hasn't opted out; every one of
them has a rules-based path, so the whole app works without a key. See
[docs/engineering/modules.md](docs/engineering/modules.md) for how modules plug in.

Not built yet: real sign-in (the identity switcher is a demo), live EHR, payer and pharmacy connections
(billing uses a demo payer, lab feeds arrive as pasted HL7 v2), notifications by email or text, and
background jobs (check-ins and expiries update when someone opens the relevant screen).
