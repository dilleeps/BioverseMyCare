# 005. FHIR-native data model from day one

**Status.** Accepted

## Context

Hospital adoption depends on interoperability with EHRs, labs, imaging, pharmacies and payers. Many consumer health products start with a bespoke schema and bolt FHIR on later, and the translation layer becomes a permanent source of bugs and lost fidelity.

## Decision

Bioverse's data model is FHIR from the start. Core entities map directly to FHIR resources as listed in [01-architecture.md](../01-architecture.md). Integration adapters translate external formats into FHIR at ingestion. Everything above the adapter layer speaks FHIR. Coded concepts carry standard terminology codes via a terminology service.

## Alternatives considered

- **Bespoke relational schema optimized for the consumer app, with FHIR export.** Faster for the first screens, slower for every integration after, and produces two models to keep in sync.
- **FHIR for clinical data only, bespoke for everything else.** Considered for operational and conversational data. Rejected for clinical, scheduling, consent and provenance data. Conversation transcripts and operational telemetry may use purpose-built stores, with references to FHIR resources.

## Consequences

- Early engineering pays a learning cost on FHIR.
- SMART on FHIR, CDS Hooks and Bulk FHIR become natural extensions rather than projects.
- Provenance and AuditEvent give AI traceability a standard representation.
- A FHIR server or equivalent store is a Phase 0 dependency.
