# 003. SaaS platform billing is separate from healthcare patient billing

**Status.** Accepted

## Context

Bioverse has two unrelated financial flows. The first is platform billing: hospitals, health systems and clinicians pay for the Bioverse service, typically by subscription. The second is the patient financial experience: insurance eligibility, coverage, copays, deductibles, claims, bills, payment plans and financial assistance for the care itself.

A card-payment SaaS billing capability, such as Stripe subscriptions, is well suited to the first and unsuited to the second.

## Decision

Platform billing and patient healthcare billing are separate subsystems with separate data models, separate integrations and separate compliance scopes. The Billing and Coverage module handles the patient financial experience through claims and eligibility integrations with payers and hospital revenue-cycle systems. SaaS billing lives in the Organization Platform's billing administration and never touches protected health information.

## Alternatives considered

- **One billing system for both.** Rejected. Healthcare billing involves payer adjudication, regulated statements and revenue-cycle systems that a SaaS billing provider does not model, and mixing the two puts patient financial data into a system scoped for subscriptions.

## Consequences

- The Billing and Coverage module is a healthcare integration project, not a payments project, and is sequenced in Phase 2 (eligibility) and Phase 5 (full).
- Patient payments, where Bioverse facilitates them, flow to the hospital's own payment processor and revenue-cycle system, with Bioverse as the experience layer.
- Compliance scope for the SaaS billing subsystem stays narrow.
