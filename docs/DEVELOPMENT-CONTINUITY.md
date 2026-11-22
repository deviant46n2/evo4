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
- HEAD before the architecture-readiness documentation commit: `7b5d78dd5d5be2ed8dc7153681c3c50deefec127` (parent of `d4f5fb497b38fa02b6cd54678f2cabe7dee37205`).
- Architecture-readiness documentation commit: `d4f5fb497b38fa02b6cd54678f2cabe7dee37205`.
- Latest Registry specification/continuity reconciliation commit: `dcff06f49c8015ecd4b178465c12292e3ee9bef0`.
- Subsequent continuity-only cleanup commit: `a7577506453a8ee8fbb79b0677fe990b7d524308`.
- Original approved Registry design baseline remains `be32d766b5fde3c0e8bc7662a43856859b378d9b`.
- Tracked working tree was clean before this documentation task. Pre-existing untracked files remain untouched: `desktop/dist/`, `desktop/tsconfig.tsbuildinfo`, `diagnostics/coding-acceptance-direct-1ab0d44c.md`, and `diagnostics/coding-acceptance-plan-33ebabb2.md`.
- Platform Registry v1 design baseline is approved at commit `be32d766b5fde3c0e8bc7662a43856859b378d9b`.
- `docs/ARCHITECTURE.md` is the authoritative cross-cutting architecture, including platform-wide design principles and engineering contracts.
- `docs/ARCHITECTURE-READINESS-REVIEW.md` is the Registry readiness decision record. It finds no blocking incompatibility, but Milestone 1 remains unauthorized and no Registry implementation has started.
- `docs/PLATFORM-REGISTRY-V1-IMPLEMENTATION-PLAN.md` defines the approved implementation sequence.
- Platform Registry v1 implementation plan is now recorded in `docs/PLATFORM-REGISTRY-V1-IMPLEMENTATION-PLAN.md`.
- Verified baseline in this worktree:
  - Python tests: 263 passed using the main repository virtual environment because this worktree has no `.venv`.
  - Python compile check: passed.
  - Desktop production build: not run successfully; `desktop/node_modules` and `package-lock.json` are absent and `tsc` is unavailable. No environment changes were made.
- Implemented and validated in this branch: agent lifecycle reconciliation, verified background coding, build identity, truncated-response safety, malformed-tool-call recovery, verification completion guards, and documentation reconciliation.
- Identity, architecture, roadmap, and development-continuity documentation has been reconciled with the revised Evo platform vision.
- Historical coding-agent acceptance evidence:
  - An earlier live coding-agent attempt failed because the model produced malformed tool-call JSON. No files were written.
  - A later attempt failed because the model hit its completion-token limit twice, including one bounded continuation. Truncated tool-call content was not executed and no successful file writes occurred.
- A separate plan-first acceptance run created files but could not run verification because the configured allowlist did not include `python test_calculator.py`. The plan was marked completed despite failed verification commands. This is historical evidence for the verification-authority concern, not the current top-level project priority.
- The development control plane and lifecycle supervisor are documented as proposed architecture only.
- No Platform Registry implementation code has been written.

## Outstanding tasks and blockers

- Milestone 1 (persistence foundation and migration) is the recommended first code milestone but is not yet authorized or started.
- Verification-authority question for plan completion in a user-configurable allowlist environment remains open.
- Repeat live coding-agent acceptance after provider/model reliability and allowlist configuration are addressed.
- Define and implement the development control plane only after design review.
- Define lifecycle supervisor architecture only after the current coding-agent milestone closes.

## Next recommended engineering decision

GPT-6 should review the committed architecture deliverables, including `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-READINESS-REVIEW.md`, and the Registry baseline, and determine whether any blocking issue remains. Milestone 1 is not authorized until that review is complete. No Registry implementation has started.
