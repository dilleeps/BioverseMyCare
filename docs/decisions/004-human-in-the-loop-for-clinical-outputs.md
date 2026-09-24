# 004. Clinical outputs default to human review before reaching patients

**Status.** Accepted

## Context

AI can explain a lab result, draft a note or answer a post-visit question faster than a clinician. It can also be wrong in ways a patient cannot detect. The reference model cited in the brief uses an AI response plus doctor review pattern in certain specialties. Regulators, clinicians and patients all expect a clinician to stand behind clinical communication.

## Decision

Any AI output that is clinical in nature and destined for a patient passes through AI Draft → Clinician Review → Clinician Edit → Approve → Publish by default. The clinical review matrix in [04-safety-and-governance.md](../04-safety-and-governance.md) defines defaults per output type. Organizations and clinicians may loosen requirements deliberately, per output type and specialty, within platform limits. The workflow engine enforces the matrix. Agents cannot bypass it.

## Alternatives considered

- **Direct AI answers with disclaimers.** Faster, but shifts risk onto the patient and undermines clinician trust in the platform.
- **Review everything, always.** Safest on paper, but creates a review backlog that delays even routine education and makes clinicians resent the platform.

## Consequences

- Review queues and clinician workflow are core product, not admin tooling. The Clinician Workspace must make review fast.
- Review turnaround becomes a monitored service level.
- Every review decision and edit is recorded, which builds the evaluation data that lets organizations loosen requirements with evidence.
- Delegation to staff for low-risk outputs is supported so clinicians review only what needs them.
