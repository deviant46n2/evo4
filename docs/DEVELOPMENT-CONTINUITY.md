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
- Portability is a design requirement: single-user and local-first initially, with future export/import and multi-user support.
- Subsystems should be independently replaceable where practical, but exact boundaries remain an implementation question.
- Evo may eventually participate extensively in its own development, constrained by safety, authorization, demonstrated reliability, and available resources; it must not declare its own improvements successful without independent evidence.
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

- Storage choices, migration strategy, and schema evolution for experiment records and other persistent entities outside the approved Registry v1 baseline.
- Portability mechanisms for project/configuration definitions and secrets.
- Subsystem boundaries and how independently replaceable individual subsystems should be.
- Detailed optimization priorities and tradeoffs.
- Exact implementation and sequencing of autonomous self-development.
- Development control plane implementation details and acceptance criteria.
- Whether plan completion should require successful verification when verification is configured.
- Whether an explicit `blocked` verification status is needed when no permitted command is available.

## Current development state
- Branch: `agent-lifecycle-reconciliation-v1`
- Verified baseline HEAD before this stabilization pass: `bdfed18ec0fade94b2c634aac97b1e5b4ed16cb4`. The final resulting commit SHA is supplied in the engineering handoff; this document intentionally does not claim to contain its own final commit hash.
- Platform Registry v1 has been implemented through M5: AI configurations, software projects, project checkouts, workspaces, and the registered-workspace execution boundary are implemented and validated.
- Registered-workspace execution boundary: implemented and accepted. API execution requires an active registered `workspace_id`; direct and plan-backed workers re-resolve before constructing `CodingAgent`; legacy plans fail closed.
- Desktop `AgentsWorkspace` selection race correction: implemented and accepted.
- The codebase is in a stabilization phase. The final GPT-6 review is complete and Priorities 1-6 are accepted; the stabilization freeze remains active until the user explicitly lifts it.
- Canonical audit ledger: `docs/GEMINI-AUDIT-LEDGER.md`.
- Canonical roadmap stabilization section: `ROADMAP.md`.
- Latest validation reported on this branch: 525 Python tests passed; compileall passed; `git diff --check` passed; no desktop build was run for the Priority 6 follow-up.

## Outstanding stabilization tasks

None. Priorities 1-6 are accepted; the stabilization freeze remains active until the user explicitly lifts it.

Accepted:
- Provider streaming reliability (Priority 1).
- Tool-call argument validation (Priority 2).
- Workspace filesystem boundary hardening (Priority 3).
- Untrusted retrieved context isolation (Priority 4).
- Experiment lifecycle interruption (Priority 5).
- ResourceMonitor shutdown race (Priority 6).

Latest reported validation for this branch: 525 Python tests passed; compileall passed; `git diff --check` passed; no desktop build was run for the Priority 6 follow-up. Validation was reported by Kilo implementation runs, not independently rerun by GPT-6.

See `docs/GEMINI-AUDIT-LEDGER.md` and `ROADMAP.md`.

## Accepted product direction

- Evo's underlying identity remains the existing model-agnostic AI development and experimentation platform.
- The accepted user-experience direction is chat-first, with other application areas acting as windows into backend capabilities.
- Projects are independent and must not blend instructions, memory, filesystem access, or task scope by default.
- Automatic project selection/switching is reliability-gated and requires demonstrated isolation before enablement.
- Project provisioning includes a dedicated folder, `git init`, and a complete initial framework.
- Project deletion must remove project-owned files, Git history, and Evo-managed resources with verified cleanup and safeguards.
- Global and project-specific instructions/memory are distinct.
- Memory is a persistent context system with provenance, confidence, review, search, inspection, and editing.
- AI configuration/Cyberdeck visualization must reflect actual backend configuration and runtime state.
- Chat visuals are configurable rather than fixed.
- Agent activity appears inline with reliable expansion; background orchestration and configurable autonomy/interruption are required goals.

## Product redesign planning status

- Redesign planning document: `docs/PRODUCT-REDESIGN-PLAN.md`.
- No redesign implementation has been authorized.
- The stabilization freeze remains active.
- The redesign track is a prerequisite to further feature expansion, subject to user authorization and completion of stabilization review.
