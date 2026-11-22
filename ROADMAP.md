# Evo4 Roadmap

Evo is a portable, model-agnostic AI development and experimentation platform. Its purpose is to assemble, configure, evaluate, experiment with, coordinate, and continuously improve increasingly capable AI systems using existing models, agents, memory systems, tools, frameworks, and execution infrastructure.

The long-term ambition is to pursue increasingly capable, potentially superintelligent AI systems through software engineering rather than foundation-model engineering. The personal assistant and coding-agent experiences are configurations built on this platform, not its fundamental identity.

This roadmap is provisional. Dependencies and acceptance criteria must be refined before implementation.

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

## Proposed roadmap

0. Architectural reconciliation and development governance.
1. Portable application foundation, persistent storage, and entity management.
2. Independent software-project and AI-configuration management.
3. Git integration, version histories, branching, and workspace isolation.
4. Provider/model/agent integration contracts and execution adapters.
5. Resource discovery and resource-aware execution management.
6. Persistent experiment registry, artifacts, evaluation, and reproducibility.
7. Agent lifecycle, communication, and orchestration.
8. Memory, context, retrieval, and intelligence experimentation.
9. Autonomous research and increasingly capable software development.
10. Controlled self-improvement and more advanced autonomous development.

Do not treat this order as immutable. Refine dependencies where architecture justifies it. Avoid building elaborate orchestration before simpler GitHub-first foundations are proven.

## Platform Registry status

Registry v1 capabilities through M5 are implemented and validated: AI configurations, software projects, project checkouts, workspaces, and the registered-workspace execution boundary. The full specification is in `docs/PLATFORM-REGISTRY-V1-SPEC.md`. Later registry capabilities remain proposed.

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

### Priority 3: Workspace filesystem boundary hardening
- Problem: Traversal, sensitive-file exposure, silent search truncation, command-argument/env boundaries.
- Affected subsystem: Workspace and coding agent.
- Required remediation: Restrict traversal, exclude sensitive/internal files, communicate truncation, document command/env behavior.
- Required tests: Sensitive file exclusion, traversal, truncation, command boundary tests.
- Acceptance criteria: Sensitive files are not exposed; truncation is communicated.

### Priority 4: Untrusted retrieved context isolation — remediation implemented; pending GPT-6 review
- Problem: Retrieved memory/lesson content is not clearly isolated as untrusted.
- Affected subsystem: Assistant context.
- Required remediation: Delimit retrieved context as untrusted while preserving `_fit_context`.
- Required tests: Context-budget and injection-resistance tests.
- Acceptance criteria: Retrieved content cannot masquerade as system instructions.

### Priority 5: Experiment lifecycle interruption — remediation implemented; pending GPT-6 review
- Problem: KeyboardInterrupt can leave experiment rows running.
- Affected subsystem: Evo Lab runner.
- Required remediation: Finalize interrupted runs consistently.
- Required tests: Interruption finalization test.
- Acceptance criteria: No running rows remain after interruption.

### Priority 6: ResourceMonitor shutdown race
- Problem: Monitor join timeout can race with database closure.
- Affected subsystem: Evo Lab monitoring.
- Required remediation: Ensure shutdown completes before database closure or document the limitation.
- Required tests: Monitor shutdown lifecycle test.
- Acceptance criteria: No database access after shutdown.

### Partially confirmed / needs investigation
- Untrusted retrieved context isolation details.
- Workspace traversal and sensitive-file exposure scope.

### False positives
- Evaluation false positive: disproved by `evaluate_task`.
- Unbudgeted context: disproved by `_fit_context`.
