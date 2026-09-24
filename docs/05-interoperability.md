# Interoperability

Interoperability is critical for hospital adoption. A platform that cannot read from and write to the systems a hospital already runs will not be deployed.

## Principles

1. **FHIR-native, not FHIR-adapted.** The Bioverse data model is FHIR from the start. See the domain model in [01-architecture.md](01-architecture.md).
2. **Read from the source of truth.** The hospital's EHR or EMR remains the clinical record. Bioverse reads, enriches and writes back through sanctioned interfaces. It does not become a shadow record.
3. **Normalize at the edge.** Integration adapters translate external formats into FHIR at ingestion. Everything above the adapter layer speaks FHIR.
4. **Terminology everywhere.** Every coded concept carries a standard code. Free text is retained but never the only representation.

## Standards

| Standard | Use in Bioverse |
| --- | --- |
| FHIR R4 and later | Primary data model and API surface |
| HL7 v2 | Inbound ADT, ORM, ORU and SIU feeds from legacy hospital systems, translated to FHIR at the adapter |
| SMART on FHIR | Clinician Workspace launch from within the EHR, and patient-authorized data access |
| CDS Hooks | Delivering Evidence Assistant and Doctor Agent insights into the EHR workflow |
| OAuth 2.0, OpenID Connect, SAML | Identity, single sign-on with hospital identity providers |
| Bulk FHIR | Population-level analytics and initial tenant onboarding |

## Terminology

| Domain | Standard |
| --- | --- |
| Diagnoses | ICD-10, SNOMED CT |
| Procedures | CPT, SNOMED CT |
| Clinical findings, symptoms | SNOMED CT |
| Lab observations | LOINC |
| Medications | RxNorm |
| Units | UCUM |

A terminology service provides code lookup, validation, mapping between code systems and value set expansion. Agents call the terminology service. They do not embed codes.

## Integration surfaces

| Surface | Direction | Purpose | Modules served |
| --- | --- | --- | --- |
| EHR / EMR | Bidirectional | Patient demographics, encounters, problems, medications, allergies, notes, orders | Patient Health Record, Clinician Workspace, Doctor Agent |
| Scheduling system | Bidirectional | Slots, appointments, check-in status | Care Navigator, Appointment and Visit Navigator, Hospital |
| Laboratory | Inbound | Results as Observation and DiagnosticReport | Results and Report Assistant |
| Imaging | Inbound | Reports and study references | Results and Report Assistant |
| Pharmacy | Bidirectional | Prescriptions, fill status, refill requests | Pharmacy, Care Plan |
| Claims and eligibility | Bidirectional | Coverage, eligibility, estimates, claims status | Billing and Coverage, Care Navigator |
| Identity provider | Inbound | Clinician and staff authentication, roles | Trust and Safety, Organization Platform |
| Trial registries | Inbound | Study definitions and eligibility criteria | Research and Clinical Trials |
| Patient-supplied documents | Inbound | Uploaded reports, discharge summaries, external records | Results and Report Assistant, Patient Health Record |

## API gateway

A single API gateway fronts all Bioverse services. It enforces authentication, tenant scoping, consent checks, rate limits and audit logging before any request reaches a service. External partners integrate through the gateway only.

## Data normalization pipeline

```
External source ──▶ Adapter ──▶ Validation ──▶ Terminology mapping ──▶ Deduplication
──▶ Patient matching ──▶ FHIR store ──▶ Provenance recorded
```

Patient matching across sources uses a master patient index with configurable matching rules and a manual resolution queue for ambiguous matches. A wrong merge is a patient-safety event, so the matching threshold is conservative.

## Adoption path for a hospital tenant

1. **Read-only pilot.** Connect scheduling and directory data. Enable patient front door, navigation and booking against the hospital's real availability.
2. **Clinical read.** Connect EHR read access under SMART on FHIR. Enable Patient Health Record, Results and Report Assistant, and the Clinician Workspace patient overview.
3. **Clinical write.** Enable intake summaries, draft notes and care plans written back to the EHR after clinician approval.
4. **Full orchestration.** Enable referral management, messaging, operational dashboards and hospital agents.

Each step is independently valuable and independently reversible.
