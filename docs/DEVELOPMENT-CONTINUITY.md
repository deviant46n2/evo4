# Evo4 Development Continuity

This document is the continuity record for future Evo4 conversations. Important architectural decisions made in future conversations must be incorporated into version-controlled documentation such as this file, `README.md`, `ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT-CONTROL-PLANE.md`, and `AGENTS.md`, rather than existing only in chat history.

## Central vision

See `docs/ARCHITECTURE.md` for the definitive entity model and architectural relationships.

Evo is a portable, model-agnostic AI development and experimentation platform. Its purpose is to assemble, configure, evaluate, experiment with, coordinate, and continuously improve increasingly capable AI systems using existing models, agents, memory systems, tools, frameworks, and execution infrastructure.

The ambition is to pursue increasingly capable, potentially superintelligent AI systems through software engineering rather than foundation-model engineering.

Evo is not pursuing foundation-model training, custom neural-network engineering, or a general-purpose AI research laboratory.

The personal assistant and coding-agent experience are configurations built on this platform, not the fundamental reason the platform exists.

## Accepted architectural decisions

- Evo's identity is a portable, model-agnostic AI development and experimentation platform.
- The fundamental entities are Evo, AI configurations, software projects, workspaces/sessions, experiments, execution environments, and resource management.
- AI configurations and software projects are independent entities with independent version histories.
- Workspaces and sessions connect configurations to authorized targets; neither owns the other.
- Experiments preserve hypothesis, exact configuration version, exact software-project revision, environment, model/provider identity, settings, methodology, resource consumption, results, failures, conclusions, reproducibility information, and artifact references.
- Git is the authoritative project history for source code, configuration definitions, versioned documentation, and reproducible development states.
- Persistent experiment registries and artifact storage preserve structured findings and large artifacts; Git is not an indiscriminate dumping ground for large binary artifacts.
- Failed experiments are valuable engineering knowledge and must not simply disappear.
- Existing models and frameworks are replaceable components, not architectural foundations.
- Evo owns its interfaces, integration contracts, experiment records, evaluation criteria, and orchestration.
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
- The development control plane is a first-class Evo subsystem, but remains proposed architecture until implemented.
- Lifecycle supervision is a separate future milestone, not part of current coding-agent reliability work.
- Evo must not declare its own improvements successful without independent validation and measurable evidence.
- Safety, authorization, demonstrated reliability, and available resources constrain autonomy; there is no arbitrary prohibition on self-development.

## Proposed decisions awaiting discussion

- Persistent first-class experiment records and experiment management implementation details.
- Hardware and operating-system portability strategy.
- How independently replaceable individual subsystems should be.
- Detailed optimization priorities and tradeoffs.
- Exact implementation and sequencing of autonomous self-development.
- Development control plane implementation details and acceptance criteria.
- Whether plan completion should require successful verification when verification is configured.
- Whether an explicit `blocked` verification status is needed when no permitted command is available.

## Current development state

- Branch: `agent-lifecycle-reconciliation-v1`
- HEAD: `5d4ae8f53c4cbb150bfe8ac2f3d85444abad4ee5`
- Working tree contains uncommitted generated artifacts and diagnostic files.
- Implemented and validated in this branch: agent lifecycle reconciliation, verified background coding, build identity, truncated-response safety, malformed-tool-call recovery, verification completion guards, and documentation reconciliation.
- A direct coding acceptance run failed because the model produced malformed tool-call JSON.
- A plan-first acceptance run created files but could not run verification because the configured allowlist did not include `python test_calculator.py`; the plan was marked completed despite failed verification commands. This is historical evidence for the verification-authority question, not the immediate project priority.
- The development control plane and lifecycle supervisor are documented as proposed architecture only.

## Outstanding tasks and blockers

- Define the first implementation milestone for the portable platform foundation.
- Resolve the verification-authority question for plan completion in a user-configurable allowlist environment.
- Repeat live coding-agent acceptance after provider/model reliability and allowlist configuration are addressed.
- Define and implement the development control plane only after design review.
- Define lifecycle supervisor architecture only after the current coding-agent milestone closes.

## Next recommended discussion or engineering decision

Before further implementation, GPT-6 should define the first implementation milestone for the platform foundation, using the entity model in `docs/ARCHITECTURE.md`, while preserving the existing Evo assistant and Evo Lab capabilities. The next engineering decision should be the smallest coherent foundation that supports independent AI configurations, software projects, workspaces/sessions, and experiments without prematurely implementing the full control plane.
