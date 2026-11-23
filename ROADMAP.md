# Evo4 Roadmap

Evo exists to make cooperating AIs and tools more capable together than any of them could be independently.

Evo is a portable, model-agnostic platform for cooperative intelligence. Its purpose is to provide the infrastructure, coordination, context, delegation, verification, evaluation, governance, and resource management that allow heterogeneous models, agents, and tools to produce better combined results than any participant could produce alone.

The long-term ambition is to pursue increasingly capable, potentially superintelligent AI systems through software engineering rather than foundation-model engineering. The personal assistant and coding experience are the initial practical product through which the broader cooperative-intelligence purpose is realized.

This roadmap is provisional. Dependencies and acceptance criteria must be refined before implementation. The roadmap is the authoritative development sequence; `docs/ARCHITECTURE.md` carries architectural detail, and `docs/PRODUCT-REDESIGN-PLAN.md` carries target user-experience detail.

## Agreed principles

- Evo is not a foundation-model trainer or general-purpose ML laboratory.
- Models and external frameworks are replaceable components, not architectural foundations.
- Evo owns its interfaces, integration contracts, experiment records, evaluation criteria, and orchestration.
- Real models are integration targets and experimental subjects, not prerequisites for development.
- GitHub remains the immediate shared engineering workspace and permanent source of truth.
- Human steering, accountability, provider compliance, and safety constraints remain mandatory.
- Every task has one accountable owner.
- Routine, reversible, authorized work may eventually become autonomous; consequential actions require safeguards and authorization.
- Evo must not declare its own improvements successful without independent evidence.
- Cooperation is an architectural principle, not merely a feature.
- More agents or parallelism do not automatically improve results; collaboration must be measured.
- Provider terms, licensing, API permissions, automation restrictions, and data-handling rules must be respected.

## Unified roadmap

1. **Governance, baseline, and architecture reconciliation.** Document the current implementation, accepted decisions, boundaries, and development process. This documentation task is the current authorized work. Status: in progress.
2. **Reliable project, workspace, and execution scope.** Build on Registry v1. Make project/task/workspace identity, ownership, instructions, filesystem access, permissions, lifecycle, and isolation reliable. Provisioning and deletion must be safe and verifiable. This is foundational for cooperation. Status: partially implemented; Registry v1 through M5 is implemented and validated, while provisioning, deletion safeguards, and project-scoped instructions/memory remain incomplete.
3. **Cooperation contracts and participant integration.** Define the minimum common contracts for participants, capabilities, assignments, task ownership, messages, context envelopes, permissions, handoffs, and evidence. Support current workflows and integrations through legitimate interfaces. Avoid premature universal abstractions. Status: designed in part; not implemented as a common contract.
4. **First cooperative vertical slice.** Demonstrate a real, useful task in which distinct participants contribute complementary work, exchange findings, challenge or review work, and produce a verifiable result. Use the GPT-6/Kilo workflow as the initial practical reference, without falsely claiming Evo already orchestrates these sessions directly. Preserve Git as the current engineering handoff. Status: not started.
5. **Durable orchestration and execution.** Extend existing run/plan/background-task infrastructure toward durable task lifecycle, communication, progress, interruption, resumption, approvals, failure recovery, bounded delegation, and concurrency. Build only what the first validated workflow requires, then generalize. Status: partially implemented; agent runs, plans, approval, cancellation, background tasks, and recovery exist, but full cooperative orchestration does not.
6. **Shared context and persistent memory.** Establish global/project/task scope, provenance, retrieval, context reconstruction, inspectability, correction, and cross-participant access without scope leakage. Status: partially implemented; memory retrieval, candidate review, and context budgeting exist, but global/project/task scoping and full provenance-driven context reconstruction need further work.
7. **Evaluation, reproducibility, and resource intelligence.** Strengthen independent verification, comparative evaluation, experiment records, artifact provenance, resource admission, scheduling, and cost/latency/quality trade-offs. Resource constraints must inform orchestration before large-scale parallelism. Status: partially implemented; experiment registry and evaluation exist, but comparative collaboration evaluation and resource-aware scheduling remain incomplete.
8. **Product experience evolution.** Refine the existing chat-first desktop around proven cooperative workflows: conversation continuity, projects, inline activity, task controls, memory, and configuration. Improve usability incrementally where necessary; do not postpone all usability work until a late phase. Do not prioritize a complete visual redesign over working capabilities. Status: partially implemented; chat and workspaces exist, but redesign remains planning only.
9. **Cyberdeck and system observability.** Design and implement the visual configuration/runtime view after actual component identities, relationships, lifecycle, and runtime-state contracts exist. It must reflect real system state, not decorative or fictional nodes. Status: not implemented.
10. **Progressive autonomy and self-improvement.** Add increasingly independent research, experiment design, development, validation, and controlled improvement only after reliable scopes, orchestration, evaluation, recovery, and authorization are demonstrated. Status: long-term.

Dependencies and sequencing:
- Phase 1 must come first because it establishes governance and baseline.
- Phase 2 is foundational for cooperation and must precede cross-project or cross-participant work.
- Phase 3 defines the contracts needed by Phase 4 and Phase 5.
- Phase 4 validates whether cooperation actually works before broader orchestration investment.
- Phase 5 generalizes only after Phase 4 demonstrates value.
- Phase 6 should strengthen measurement before large-scale parallelism.
- Phase 8 can proceed incrementally alongside Phases 2-7 where it supports validation.
- Phase 9 depends on Phases 3 and 5.
- Phase 10 depends on all earlier phases.

Safe parallel work includes documentation, tests, small UX improvements that support validation, and independent review. Continuous quality activities include tests proportionate to risk, independent review for consequential work, evidence-based capability claims, reproducible experiment records, documentation alignment, provider compliance, and resource limits.

The first implementation milestone after the current documentation task must be explicit, small enough to validate, and useful. It must not be started by this documentation task.

## Mapping of original roadmap phases

Original phase 0, architectural reconciliation and development governance: retained as Phase 1 and substantially in progress.
Original phase 1, portable application foundation, persistent storage, and entity management: retained as Phase 2 baseline; Registry v1 M5 is implemented and validated.
Original phase 2, independent software-project and AI-configuration management: retained as part of Phase 2 and Phase 3; Registry v1 provides initial capabilities.
Original phase 3, Git integration, version histories, branching, and workspace isolation: retained as part of Phase 2 and Phase 6; Git and workspace isolation are partially implemented.
Original phase 4, provider/model/agent integration contracts and execution adapters: retained as Phase 3; integration exists but common contracts are incomplete.
Original phase 5, resource discovery and resource-aware execution management: retained as Phase 7; only basic resource monitoring exists.
Original phase 6, persistent experiment registry, artifacts, evaluation, and reproducibility: retained as Phase 7; experiment registry and evaluation exist.
Original phase 7, agent lifecycle, communication, and orchestration: retained as Phases 3, 4, and 5; partial implementation exists.
Original phase 8, memory, context, retrieval, and intelligence experimentation: retained as Phase 6; partial implementation exists.
Original phase 9, autonomous research and increasingly capable software development: retained as Phase 10; not implemented.
Original phase 10, controlled self-improvement and more advanced autonomous development: retained as Phase 10; not implemented.

No original phase is obsolete. Several are merged or resequenced to reflect the cooperative-intelligence purpose and the need to validate collaboration before broad orchestration.

## Product redesign track

The product redesign plan is recorded in `docs/PRODUCT-REDESIGN-PLAN.md`. It is a planning document, not implementation authorization.

The redesign concerns the primary user experience and interaction model. It must preserve Evo's platform identity and existing safety boundaries. It is a prerequisite to further feature expansion, subject to user authorization and the active stabilization freeze.

## Current implementation status

Implemented capabilities are described in `README.md` and existing docs. Registry v1 through M5 is implemented and validated. Proposed later architecture is described in `docs/ARCHITECTURE.md` and `docs/DEVELOPMENT-CONTROL-PLANE.md`. Nothing in this roadmap should be read as claiming that proposed later capabilities are already implemented.

## Stabilization and Gemini Audit Remediation

Feature development is frozen until all confirmed serious audit findings have been fixed, tested, reviewed, and accepted.

Canonical audit ledger: `docs/GEMINI-AUDIT-LEDGER.md`.

### Priority 1: Provider streaming reliability — completed and accepted
- Problem: SSE error frames without choices are silently ignored.
- Affected subsystem: Provider streaming.
- Required remediation: Detect and raise provider errors from error frames; do not accept empty successful responses silently.
- Required tests: Provider streaming tests for error frames and empty choices.
- Acceptance criteria: Provider errors surface to callers; no silent empty success.

### Priority 2: Tool-call argument validation — completed and accepted
- Problem: Non-dict tool arguments can crash downstream dispatch.
- Affected subsystem: Coding agent.
- Required remediation: Validate parsed arguments are dictionaries before dispatch.
- Required tests: Malformed/non-dict argument recovery.
- Acceptance criteria: Malformed tool calls are recorded and recovered without crashing.

### Priority 3: Workspace filesystem boundary hardening — completed and accepted
- Problem: Traversal, sensitive-file exposure, silent search truncation, command-argument/env boundaries.
- Affected subsystem: Workspace and coding agent.
- Required remediation: Restrict traversal, exclude sensitive/internal files, communicate truncation, document command/env behavior.
- Required tests: Sensitive file exclusion, traversal, truncation, command boundary tests.
- Acceptance criteria: Sensitive files are not exposed; truncation is communicated.

### Priority 4: Untrusted retrieved context isolation — completed and accepted
- Problem: Retrieved memory/lesson content is not clearly isolated as untrusted.
- Affected subsystem: Assistant context.
- Required remediation: Delimit retrieved context as untrusted while preserving `_fit_context`.
- Required tests: Context-budget and injection-resistance tests.
- Acceptance criteria: Retrieved content cannot masquerade as system instructions.

### Priority 5: Experiment lifecycle interruption — completed and accepted
- Problem: KeyboardInterrupt can leave experiment rows running.
- Affected subsystem: Evo Lab runner.
- Required remediation: Finalize interrupted runs consistently.
- Required tests: Interruption finalization test.
- Acceptance criteria: No running rows remain after interruption.

### Priority 6: ResourceMonitor shutdown race — completed and accepted
- Problem: Monitor join timeout can race with database closure.
- Affected subsystem: Evo Lab monitoring.
- Required remediation: Ensure shutdown completes before database closure or document the limitation.
- Required tests: Monitor shutdown lifecycle test.
- Acceptance criteria: No database access after shutdown.

### Partially confirmed / needs investigation
None. Residual limitations for accepted priorities are documented in `docs/GEMINI-AUDIT-LEDGER.md`.

### False positives
- Evaluation false positive: disproved by `evaluate_task`.
- Unbudgeted context: disproved by `_fit_context`.
