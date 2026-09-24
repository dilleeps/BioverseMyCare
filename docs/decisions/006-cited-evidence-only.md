# 006. Clinical answers to clinicians must carry citations

**Status.** Accepted

## Context

The Evidence Assistant and Doctor Agent will answer clinical questions for clinicians. An unsupported AI answer, however plausible, cannot be verified at the point of care and erodes trust the first time it is wrong. The reference model cited in the brief retrieves evidence across a large corpus of publications, guidelines and drug labels. The principle Bioverse adopts is AI answer + evidence + citation + clinician judgment.

## Decision

Any clinical claim the Evidence Assistant or Doctor Agent presents to a clinician must be grounded in a retrieved source and carry a citation, source link, evidence date and a quality indicator. When no supporting source is retrieved, the agent says so rather than answering. Hallucination monitoring checks clinical claims against retrieved sources and blocks uncited claims in clinical contexts.

## Alternatives considered

- **Model knowledge with a general disclaimer.** Rejected. It cannot be audited and it ages silently.
- **Citations optional, shown when available.** Rejected. Optional citations train users to trust uncited answers.

## Consequences

- Licensed, indexed evidence sources are a Phase 3 dependency, and their currency is an operational responsibility.
- Retrieval quality is a monitored metric.
- Some questions will receive "no evidence found." That is the correct behavior.
- Evidence age is always visible, so clinicians can weigh older guidance appropriately.
