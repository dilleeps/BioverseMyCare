# Architecture Decision Records

Each record captures one decision that shapes the platform, the context that forced it, the alternatives considered and the consequences accepted. Records are numbered and never deleted. A superseded record is marked as such and points to its replacement.

| ID | Decision | Status |
| --- | --- | --- |
| [001](001-single-front-door.md) | One conversational front door, never a module menu | Accepted |
| [002](002-orchestrated-agents-not-bots.md) | Specialized agents under one orchestrator, not independent bots | Accepted |
| [003](003-separate-saas-billing-from-patient-billing.md) | SaaS platform billing is separate from healthcare patient billing | Accepted |
| [004](004-human-in-the-loop-for-clinical-outputs.md) | Clinical outputs default to human review before reaching patients | Accepted |
| [005](005-fhir-native-data-model.md) | FHIR-native data model from day one | Accepted |
| [006](006-cited-evidence-only.md) | Clinical answers to clinicians must carry citations | Accepted |

## Template

```
# NNN. Title

**Status.** Proposed | Accepted | Superseded by NNN

## Context
## Decision
## Alternatives considered
## Consequences
```
