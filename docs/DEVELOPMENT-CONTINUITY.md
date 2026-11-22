# Evo4 Development Continuity

This document is the continuity record for future Evo4 conversations. Important architectural decisions made in future conversations must be incorporated into version-controlled documentation such as this file, `README.md`, `ROADMAP.md`, `docs/DEVELOPMENT-CONTROL-PLANE.md`, and `AGENTS.md`, rather than existing only in chat history.

## Central vision

See `docs/ARCHITECTURE.md` for the definitive entity model and architectural relationships.

Evo4 is a model-agnostic AI development and experimentation platform designed to assemble, evaluate, coordinate, and continuously improve AI systems using existing models, agents, tools, and infrastructure.

The ambition is to pursue increasingly capable, potentially superintelligent AI systems through software development: memory, context management, orchestration, tools, agent collaboration, evaluation, and controlled self-improvement.

Evo4 is not pursuing foundation-model training, custom neural-network engineering, or a general-purpose AI research laboratory.

The personal assistant and coding-agent experience are configurations built on this platform, not the fundamental reason the platform exists.

## Accepted architectural decisions

- Models and external frameworks are replaceable components, not architectural foundations.
- Evo4 owns its interfaces, integration contracts, experiment records, evaluation criteria, and orchestration.
- Real models are integration targets and experimental subjects, not prerequisites for development.
- GitHub remains the immediate shared engineering workspace and permanent source of truth.
- Hybrid collaboration: cooperative agent networks plus hierarchical governance.
- Every task has one accountable owner.
- Multiple agents may independently review or challenge work.
- Bounded delegation, budgets, timeouts, loop prevention, and auditability are required.
- Provider compliance is mandatory; use supported interfaces and official APIs only.
- Human steering and accountability remain central.
- A minimal independent bootstrap/recovery mechanism must remain outside the control plane.
- Agent and development-control-plane roles are contracts, not fixed model identities.
- New agents begin with restricted evaluation access; permissions expand proportionally to demonstrated capability and explicit authorization.
- Lifecycle supervision is a separate future milestone, not part of current coding-agent reliability work.

## Proposed decisions awaiting discussion

- Persistent first-class experiment records and experiment management.
- Hardware and operating-system portability strategy.
- How independently replaceable individual subsystems should be.
- Detailed optimization priorities and tradeoffs.
- Exact implementation and sequencing of autonomous self-development.
- Development control plane implementation details and acceptance criteria.

## Current development state

- Branch: `agent-lifecycle-reconciliation-v1`
- HEAD: `ce80415a707cc5de94eae3021a034e6ef79f6230`
- Working tree contains uncommitted generated artifacts and diagnostic files.
- Implemented and validated in this branch: agent lifecycle reconciliation, verified background coding, build identity, truncated-response safety, malformed-tool-call recovery, and verification completion guards.
- Live Coding Agent Execution Reliability acceptance was attempted and did not pass. Direct coding failed because the model produced malformed tool-call JSON. Plan-first coding created files but could not run verification because the configured allowlist did not include `python test_calculator.py`; the plan was marked completed despite failed verification commands.
- The development control plane and lifecycle supervisor are documented as proposed architecture only.

## Outstanding tasks and blockers

- Repeat live coding-agent acceptance after provider/model reliability and allowlist configuration are addressed.
- Decide whether plan completion semantics should require successful verification when verification is configured.
- Define and implement the development control plane only after design review.
- Define lifecycle supervisor architecture only after the current coding-agent milestone closes.

## Next recommended discussion or engineering decision

Before further implementation, GPT-6 should decide how to make verification authoritative for plan completion in a user-configurable allowlist environment, and whether to add an explicit verification status of `blocked` when no permitted command is available.
