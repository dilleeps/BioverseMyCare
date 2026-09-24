# 002. Specialized agents under one orchestrator, not independent bots

**Status.** Accepted

## Context

The platform needs nine or more specialized capabilities: understanding patients, collecting intake, finding care, scheduling, supporting doctors, retrieving evidence, coordinating results, managing follow-up and coordinating hospital services. The failure mode is nine disconnected bots, each with its own conversation, memory and tone, that hand the patient off like a call center.

## Decision

One orchestrator owns the conversation, the user's confirmation state and the assembled context. Specialized agents own tasks. Handoffs between agents are structured messages carrying intent, context reference, payload, confirmation state and provenance. The orchestrator logs every handoff. Agents are registered with their permitted tools and cannot exceed them.

## Alternatives considered

- **One monolithic agent with every tool.** Simpler to start, but impossible to evaluate, govern or scope. A single prompt cannot safely hold intake logic, scheduling logic and clinical evidence retrieval.
- **Independent bots per module with a router in front.** Easy to build in parallel, but produces the disconnected experience the blueprint explicitly rejects and makes end-to-end tracing impossible.

## Consequences

- The handoff protocol and context assembly are Phase 0 platform work.
- Agents can be built, evaluated and versioned independently.
- End-to-end traces of a care journey are available for quality review and incident investigation.
- The orchestrator is a single point of failure and must be engineered and monitored accordingly.
