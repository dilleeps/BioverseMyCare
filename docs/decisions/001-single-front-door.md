# 001. One conversational front door, never a module menu

**Status.** Accepted

## Context

Bioverse spans 25 modules. Healthcare consumers already struggle to know which department to call, which portal to log into or which form to fill. Presenting a menu of modules recreates that problem inside the product.

## Decision

The patient experience has one entry point: a conversation, by voice or text, that begins with "Tell me what you need." The Patient Agent and orchestrator interpret intent and route to the appropriate journey step. Structured widgets render inline in the conversation where they help. Users never select a module.

## Alternatives considered

- **Module-based navigation with an AI assistant on the side.** Familiar, but it puts the routing burden on the patient and makes the AI a helper rather than the experience.
- **Task-based home screen with quick actions.** Useful for returning users and retained as shortcuts within the conversation surface, but not as the primary model.

## Consequences

- Intent classification and routing quality become critical path. They need evaluation sets and monitoring from Phase 1.
- Every module must expose its capability as actions the orchestrator can invoke, not only as screens.
- Hybrid UI is required. Pure text is insufficient for appointment slots, checklists and trends.
- Deep links and shortcuts remain available for power users and for notifications that land on a specific item.
