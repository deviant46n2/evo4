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

Phase status is evidence-based. "Designed" is not implemented; "implemented" is not necessarily tested; "tested" is not independently reviewed; and none of these alone means accepted. Phase 1 remains **in progress** until this critique is reconciled and the resulting document set is independently reviewed and accepted.

1. **Governance, baseline, and architecture reconciliation — in progress.** Reconcile current implementation facts, accepted decisions, security boundaries, document authority, and development governance. This pass is a substantial revision, not phase completion.
2. **Project, workspace, instruction, and context isolation — partially implemented.** Complete the Registry-based project/workspace boundary; provision safe project checkouts; enforce path and checkout isolation; establish minimum global-versus-project scoping for conversations, memories, lessons, research, instructions, tasks, and command policy. This phase establishes the trust boundaries required before multi-participant work.
3. **Participant contracts and runtime integration — designed in part, not implemented as a common runtime contract.** Define provider/model/agent/tool/human participant identity, capabilities, availability, compliance, trust evidence, scoped assignments, permissions, context envelopes, messages, handoffs, and verification. Explicitly bind versioned AI Configuration definitions to concrete runtime adapters and dispatch. Establish minimal per-dispatch resource admission and provider budgets before any cooperative execution.
4. **First Evo-managed cooperative vertical slice — not started.** Execute a bounded benchmark task end-to-end inside Evo using at least two distinct Evo-connected participants and the Phase 3 contracts. Demonstrate complementary contributions, synthesis, challenge, adjudication, deterministic verification where available, and inspectable outcomes. GPT-6/Kilo is design inspiration and a human-mediated development workflow only; it is not the Phase 4 runtime test.
5. **Durable, bounded orchestration — partially implemented foundations.** Generalize only what the vertical slice proves necessary: durable task/assignment state, typed communication, validated handoffs, interruption/cancellation propagation, resumption, recovery, approval, concurrency controls, and resource admission. Enforce least privilege and budgets at every execution boundary.
6. **Advanced shared context and persistent memory — partially implemented foundations.** Build on Phase 2's minimum scope partitioning with provenance, epistemic status, context reconstruction, correction/supersession, retrieval evaluation, and explicit user-controlled cross-project consultation. This phase may improve memory quality; it must not be the first point at which project isolation exists.
7. **Evaluation, reproducibility, and resource intelligence — partially implemented foundations.** Establish robust comparative experiments, artifact provenance, task-class reliability profiles, scheduler evaluation, resource forecasting, and quality/cost/latency trade-offs. Participant reliability evidence may inform role eligibility and assignment recommendations only through explicit, inspectable policy; it does not silently grant permissions.
8. **Product experience evolution — partially implemented.** Evolve the existing chat-first desktop to make projects, participant activity, collaboration patterns, handoffs, evidence, disagreement, approvals, resource state, and outcomes understandable and controllable. Improve usability incrementally where it supports validated workflows; introduce automated frontend and end-to-end tests before relying on complex integrated UX.
9. **Cyberdeck and system observability — not implemented.** Build the visual configuration/runtime view only after actual component identities, dependencies, task relationships, lifecycle, and runtime-state contracts exist. Display real state, including unknown and unavailable states, rather than decorative or inferred certainty.
10. **Progressive autonomy and controlled self-improvement — long-term.** Add increasingly independent research, experiment design, development, validation, and controlled improvement only after scoped execution, orchestration, evaluation, resource controls, recovery, and authorization are demonstrated.

### Dependency rules

- Phase 1 establishes the governance and evidence standard; it is not permission to begin implementation.
- Phase 2 must establish minimum project and context isolation before any cross-project or multi-participant work.
- Phase 3 must make AI Configurations executable through explicit participant/runtime adapters. Registry records alone do not make a model or agent runnable.
- Minimal resource admission, provider rate/token budgets, and bounded dispatch are Phase 3 prerequisites for the first cooperative execution. Phase 5 adds durable orchestration and safe concurrency; it must not be the first time resource admission exists.
- Phase 4 must run through Evo's own runtime contracts. A human-mediated GPT-6/Kilo workflow can inform design but cannot validate Evo orchestration.
- Phase 5 generalizes only patterns shown useful by Phase 4.
- Phase 6 advances memory quality after Phase 2 establishes scope boundaries.
- Phase 7 closes the evaluation loop: measured task-class reliability can inform participant eligibility/recommendations under user-approved policy.
- Phase 8 proceeds incrementally alongside Phases 2–7 when usability work is necessary for validation.
- Phase 9 depends on real component and runtime-state contracts from Phases 3 and 5.
- Phase 10 depends on all prior safety, isolation, recovery, and evaluation foundations.

### First implementation milestone after stabilization

**Project Provisioning v1** is implemented, reviewed, accepted, and closed at commit `d0b56afee86b208aab738994cee8a13c63bff107`. It was authorized by the user as the first implementation milestone after the stabilization freeze was lifted for that milestone.

Scope:
- Create a new, dedicated project directory. Never silently adopt, overwrite, move, or modify unrelated existing data.
- Canonicalize and validate paths; reject traversal, unsafe roots, symlink escapes, and ancestor/descendant checkout overlaps with already registered projects. The policy for intentional nested projects must be explicit rather than accidental.
- Initialize Git and create a minimal initial commit.
- Provision only a language-neutral starter skeleton: a README, a clearly marked starter `EVO_PROJECT.md` file treated as untrusted repository content, and a conservative .gitignore. Do not create trusted project policy by copying repository files into privileged context; trusted Evo-managed project instructions require a separate scoped Registry record delivered by Phase 2. Do not generate language/build-system scaffolds, install dependencies, or infer a technology stack in v1.
- Register the project and checkout through Registry v1 with explicit ownership/provenance for created files.
- A workspace requires a real AI Configuration and immutable revision under the current Registry schema. If the user selects an existing configuration/revision, create the workspace binding. If none exists, provision the project and checkout without inventing a default configuration or creating a misleading workspace; show the project as not yet bound to an execution configuration. Workspace binding is a follow-up action once a valid configuration exists.
- Keep secrets out of generated files, tracked config, and project instructions.
- Make the operation recoverable: use a durable provisioning record or equivalent staged state so interruption cannot report success while leaving incomplete registry/filesystem state. Roll back only resources proven to have been created by this operation; otherwise record an explicit recoverable partial failure.
- Test successful provisioning, invalid/canonicalized paths, symlink and ancestor/descendant conflicts, pre-existing data, Git initialization, interrupted/partial failures, registry consistency, and absence of unauthorized workspace bindings.

Explicit exclusions:
- Project deletion and destructive cleanup. Deletion is a separate future milestone, not a Phase 2 acceptance prerequisite. It requires ownership manifests, preview/dry-run, explicit confirmation, shared-resource protection, verified cleanup, and a recovery strategy.
- Automatic project inference/switching, cross-project context consultation, template marketplaces, dependency installation, and wholesale UI redesign.

**Exit gate:** a language-neutral project is created without damaging pre-existing data, has a valid Git history and accurate Registry records, and is either explicitly bound to a selected valid configuration revision or clearly unbound. Invalid/interrupted provisioning cannot leave false-success state. This milestone may begin only after explicit freeze-lift authorization.

### Phase acceptance gates

A phase is complete only when the required evidence is recorded, independently reviewed in proportion to risk, and accepted. Distinguish implemented, tested, reviewed, and accepted.

**Phase 1 — Governance and baseline**
- Current, partial, proposed, and long-term capabilities are separated using source-backed evidence.
- Document authority is unambiguous; contradictions across canonical documents are resolved.
- Security/isolation gaps and persistence boundaries are honestly documented.
- The freeze and authorization boundary are explicit.
- An independent review has been reconciled; no unresolved critical/high factual or architectural contradiction remains.

**Phase 2 — Project/workspace/context isolation**
- Project, checkout, workspace, task, and configuration relationships have explicit ownership and authorization semantics.
- Project Provisioning v1 passes its full safety/recovery test set.
- Minimum global/project scope partitioning exists for all context-bearing records used in project-specific execution, including conversations/messages, memories, lessons, research, instructions, tasks, and command policy.
- Trusted Evo-managed project metadata/instructions are distinct from repository-provided instruction files, which remain untrusted input unless separately reviewed and explicitly trusted.
- Filesystem checkout policy rejects unsafe ancestor/descendant overlaps and symlink escapes; CLI and API entry points enforce equivalent boundaries or clearly label and gate any intentionally privileged local-only mode.
- Tests prove that context, files, commands, and execution authority cannot leak across project boundaries.
- Project deletion is explicitly deferred and is not required to pass this phase.

**Phase 3 — Participant contracts and runtime binding**
- At least two distinct participant implementations can be registered and invoked through common, versioned contracts without hardcoding provider names as roles.
- AI Configuration revisions are resolved into actual runtime adapters; tests prove that different revisions produce the expected distinct model/provider/policy behavior.
- Participant identity, declared capabilities, availability, compliance status, trust evidence, role eligibility, and authorization are separate fields/concepts.
- Assignment/task ownership, permission attenuation, context envelopes, message provenance, handoff schemas, verification contracts, and bounded dispatch are explicit.
- Each dispatch is admitted against local resource reserves, concurrency caps, and provider quota/rate/token budgets; unknown capacity fails closed or requires an explicit policy override.
- Registration does not grant execution permission.

**Phase 4 — First cooperative vertical slice**
- The complete task executes inside Evo using at least two Evo-connected participants; manual copying between external chat sessions does not count.
- At least one defined cooperation pattern is demonstrated: specialist decomposition, independent parallel attempts in isolated workspaces, or implementer plus adversarial challenger.
- Outputs are synthesized against explicit acceptance criteria; competing results and disagreements are retained with provenance.
- Deterministic tests/tools are preferred as verification oracles when available. A model review is not a substitute for an available deterministic check.
- Disagreements follow bounded adjudication; unresolved conflicts reach a visible disputed/escalated terminal state or human decision, not an unbounded loop.
- Compare against a single-participant baseline on a predeclared reproducible task suite. A positive result requires measurable improvement on at least one declared task class without a material correctness or safety regression. A tie or loss is a valid experimental finding, but does **not** justify expanding cooperative orchestration; preserve the negative result and revise or stop the pattern.
- Failures, cost, latency, resource use, and human intervention are recorded.

**Phase 5 — Durable orchestration**
- Task/assignment state, ownership, handoffs, approvals, evidence, and adjudication survive restart.
- Child permissions are strict subsets of the parent's authorized scope; delegation cannot increase authority.
- Cancellation, timeout, and revocation propagate to descendants; late child results cannot silently complete a cancelled parent.
- Malformed/incomplete handoffs are rejected with actionable reasons and do not advance task state.
- Concurrent code contributions use isolated worktrees/branches or another proven conflict-isolation mechanism; shared dirty working trees are not treated as safe parallel workspaces.
- Concurrency, retries, delegation depth, time, tokens, compute, and provider quotas are bounded and enforced.
- Recovery, idempotency, partial failure, and provider unavailability are tested.

**Phase 6 — Advanced context and memory**
- Global, project, and task scopes build on Phase 2 isolation; cross-project consultation is explicit, authorized, and auditable.
- Provenance, timestamps, epistemic status, correction/supersession history, and source references are preserved.
- Users can inspect, correct, supersede, export, and constrain retained context.
- Retrieval is evaluated on a held-out representative query set, including cross-scope leakage attempts and adversarial retrieved content.

**Phase 7 — Evaluation, reproducibility, and resource intelligence**
- Individual and cooperative runs are reproducible from task, inputs, participant/config revisions, environment, policy, and verification artifacts.
- Task-class reliability profiles record sample counts, confidence/uncertainty, deterministic verification outcomes, failure classes, and recency.
- Participant role eligibility and assignment recommendations consume these profiles only through explicit, inspectable, user-governed policy; no score silently grants permissions or autonomously promotes trust.
- Scheduler/admission tests cover reserve protection, GPU/CPU/RAM constraints, provider rate/token budgets, concurrency, deferral, unknown estimates, and overload behavior.
- A reproducible A/B evaluation compares quality/correctness, latency, tokens/compute, cost, failure rate, and human intervention. Negative and neutral results are retained.
- Collaboration is enabled for a workload only when evidence supports net benefit or the user explicitly authorizes a bounded experiment.

**Phase 8 — Product experience**
- Users can inspect projects, active scope, participants, roles, task ownership, handoffs, parallel attempts, synthesis, challenges, disagreements, adjudication, verification evidence, and outcomes.
- UI reflects backend state and uncertainty; it does not invent completion or trust status.
- Frontend component tests and end-to-end tests cover the critical chat/project/agent/cooperation flows; integrated usability and reliability are demonstrated, not asserted.
- Authorization and isolation are enforced by backend contracts, not UI visibility.

**Phase 9 — Cyberdeck**
- Nodes map to real registered components or are explicitly marked conceptual.
- Edges represent real configured dependencies, communication, assignment, or ownership.
- Active, idle, waiting, failed, unavailable, and unknown are distinct.
- Configuration changes are versioned, previewable, and cannot silently mutate unrelated running components.

**Phase 10 — Progressive autonomy**
- Each autonomous action class has explicit scope, permissions, budgets, and approval policy.
- Changes occur in isolated workspaces and receive deterministic verification where available plus independent review.
- Failure recovery, rollback, and human escalation are demonstrated before consequential autonomy.
- Promotion/deployment never relies solely on the modifying participant's self-assessment.
- Autonomy expands only through measured reliability and explicit user authorization.

## Mapping of original roadmap ambitions

Original phases 0–10 are retained, merged, or resequenced rather than discarded:
- Architectural reconciliation/governance → Phase 1.
- Portable application, persistence, and entity management → existing foundation plus Phases 2 and 5.
- Project and AI-configuration management → Phase 2, with configuration-to-runtime binding in Phase 3.
- Git histories, branching, and workspace isolation → Phase 2 and Phase 5 (safe parallel worktree coordination).
- Provider/model/agent contracts and execution adapters → Phase 3.
- Resource discovery and resource-aware execution → minimum admission in Phase 3, durable concurrency enforcement in Phase 5, advanced intelligence in Phase 7.
- Experiment registry, artifacts, evaluation, reproducibility → Phase 7.
- Agent lifecycle, communication, and orchestration → Phases 3–5.
- Memory, context, retrieval, intelligence experimentation → minimum scope isolation in Phase 2; advanced capabilities in Phase 6; comparative evaluation in Phase 7.
- Autonomous research, increasingly capable development, and controlled self-improvement → Phase 10.

No original ambition is declared obsolete. Existing implementations are foundations, not proof that the intended cooperative platform is complete.

## Product redesign track

The target user experience is specified in `docs/PRODUCT-REDESIGN-PLAN.md`. It is subordinate to this roadmap. Incremental usability work may support validated capabilities; a wholesale visual redesign is not a prerequisite to all feature development.

## Current implementation status

Use `README.md` for user-facing implemented behavior and `docs/ARCHITECTURE.md` for the evidence-based architecture inventory. The Registry is implemented through M5, but configuration-to-runtime binding, project-scoped context, common participant dispatch, and Evo-managed cooperative execution are not yet implemented. Existing agent runs/plans/background tasks, memory, experiment, and resource features are partial foundations; they must not be described as the target control plane.

## Stabilization and Gemini Audit Remediation

Feature development for the broader redesign remains unauthorized. The six stabilization audit priorities are implemented and accepted. The stabilization freeze was lifted for the explicitly authorized Project Provisioning v1 milestone, which is complete and accepted. Broader redesign and subsequent implementation still require explicit user authorization.

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
