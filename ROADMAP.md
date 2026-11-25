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
2. **Project, workspace, instruction, and context isolation — accepted (2026-11-24).** Phase 2 formal acceptance covers project/workspace scope, checkout isolation, command-policy intersection, context retrieval boundaries, and task/plan scope continuity through interruption and restart recovery. Automatic replay/resumption remains disabled; continuation requires a new task with fresh scope validation. Project deletion and durable pause/resume remain deferred.
3. **Participant contracts and runtime integration — P3.1–P3.6 accepted; P3.7 remains.** The executable configuration contract, revision-pinned runtime, provider adapter, deterministic verifier, resource-admission design, authorization/admission gate, and read-only participant inspection APIs/UI are accepted. P3.6 was validated at `4e048af7978730890c47ee840d36e8d0b73866ea` (919/919 tests, compileall, diff-check, and desktop production build) and merged through PR #4 at `0fde8e812efc79edc6cc20aa5d99b05fe1fcd51d`. P3.7 must complete the cumulative independent review and record final acceptance evidence. Dispatch remains disabled by default; acceptance does not enable it.
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

### Phase 2 implementation status and formal acceptance (accepted)

Phase 2 objective: make project, workspace, instruction, and context boundaries explicit and enforceable without fragmenting existing capabilities.

Required architectural invariants:
- A project is an independent Evo-managed identity, not merely a folder path.
- A workspace is a filesystem execution boundary and must remain associated with one project.
- Global context and project context are distinct scopes.
- Project-specific instructions and memory cannot silently override global safety or authority constraints.
- Project-specific data cannot leak into unrelated projects through retrieval, search, tool execution, or context assembly.
- Uncertain project selection must not silently cause work in the wrong project.
- Trusted Evo-managed project metadata/instructions are distinct from repository-provided files, which remain untrusted input.
- Tasks and agent plans carry explicit scope. A task or plan must not inherit scope from whichever workspace is active when it executes.
- Command permissions are resolved as the intersection of global policy and project policy. Project policy may only restrict global permissions; it cannot expand them. Missing, invalid, or ambiguous project policy must not silently grant broader access.

Global versus project context defaults:
- Project-specific memories, lessons, research, conversations, and other records remain project-scoped.
- Project-specific information does not automatically become global.
- Global user context may be available to project execution where appropriate.
- Project-specific information cannot enter another project's context through retrieval, search, task handoff, or context reconstruction.
- Cross-project consultation is out of scope unless separately authorized and auditable.

Current verified implementation:
- Project Provisioning v1 creates a dedicated folder, starter files, Git repository, project, and checkout. Source: `src/evo_core/project_provisioning.py`, `src/evo_core/project_checkouts.py`, `desktop/src/ProjectsWorkspace.tsx`.
- Project Provisioning v1 is implemented, reviewed, accepted, and closed. Registry v1 and the registered-workspace execution boundary are existing foundations to reuse. Project deletion remains deferred. No genuinely incomplete provisioning capability is known beyond deferred deletion and later project-scoped context work.
- Registry v1 stores configurations, projects, checkouts, and workspaces. Source: `src/evo_core/platform_registry.py`, `src/evo_core/workspaces.py`.
- The accepted Phase 3.2 runtime factory constructs the complete workspace-bound assistant runtime from the exact immutable configuration revision and routes workspace chat, plan proposal, and coding-agent execution through that binding. Registry-bound calls do not silently fall back to the global TOML provider. The global TOML path remains separate for non-Registry callers. See the P3.2 acceptance record and `docs/PHASE-3-TECHNICAL-PLAN.md` for exact validation evidence.
- Conversations carry `project_id` and `workspace_id`; messages inherit that scope through their parent conversation rather than storing duplicate scope columns. Store/API access applies scope visibility checks. Source: `src/evo_core/store.py`, `src/evo_core/api.py`.
- Memories, memory candidates, lessons, research documents, and tasks carry project/workspace scope fields and scope-aware retrieval/listing paths. Source: `src/evo_core/store.py`, `src/evo_core/assistant.py`, `src/evo_core/api.py`.
- Assistant context assembly resolves the conversation scope and filters repository instructions, memories, lessons, research, and message history by the authorized project/workspace scope. This is not evidence that every task, background-agent, or tool-execution path has passed the full isolation gate. Source: `src/evo_core/assistant.py`.
- Agent plans carry nullable `project_id` and `workspace_id` fields and validate supplied scope; legacy/global plans remain possible. Scope continuity is accepted through approval/execution boundaries, cancellation, and restart recovery. Recovery preserves scope/history and marks unfinished work interrupted; automatic replay/resumption is intentionally unsupported. Continuing requires a new task with fresh scope validation. Source: `src/evo_core/orchestration.py`, `src/evo_core/background_agent.py`.
- **Phase 2 implementation and regression validation are complete; formal acceptance is recorded below.** The exact candidate revision `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31` passed the full 824-test suite, compileall, and diff-check. Independent review reconciled scope continuity: interruption and restart recovery preserve scope and history, but automatic resumption/replay is intentionally unsupported. Continuing work requires a new task with fresh scope validation. This is a documented capability boundary, not an acceptance failure.

Original milestones and current source status (implementation presence is not the same as acceptance):

| Milestone | Current source evidence | Acceptance status |
|---|---|---|
| Scope and authority contract | Shared scope validation and visibility helpers; scope integrity/persistence tests. | Implemented in source; retain as part of the full isolation gate. |
| Project-scoped conversations | Conversation rows carry project/workspace scope; messages inherit through the parent conversation; API filters reads and mutations. | Implemented in source; covered by backend tests. |
| Task and agent-plan scope | Tasks and plans carry scope fields; plans validate supplied scope; API applies scope visibility and workspace checks. Background tasks persist first-class project/workspace scope through cancellation and restart recovery; malformed metadata is never used to infer scope. | Accepted for Phase 2: scope is preserved through approval/execution boundaries, cancellation, and restart recovery. Interrupted work is not automatically resumed or replayed; a new task must revalidate scope. Durable pause/resume remains a later orchestration capability. |
| Command-policy enforcement | Project command prefixes are intersected with the operator's global allowlist. Workspace plan proposal generation and validation receive the effective workspace runtime allowlist; missing project policy fails closed; per-action approvals remain. | Accepted for Phase 2: the effective project/global intersection is applied to workspace plan proposals and validation as well as execution. This is an allowlist boundary, not an OS sandbox. |
| Project-scoped memory and retrieval | Memories, candidates, lessons, research, and retrieval paths carry/filter project/workspace scope. | Implemented in source; keep cross-scope leakage tests in the acceptance gate. |
| Project instructions and configuration | Trusted Evo-managed instructions are resolved by scope; repository instruction files remain untrusted; Registry configurations/workspaces pin revisions. | Implemented in source; full precedence/trust-boundary evidence remains part of acceptance. |
| Project selection and switching UX | Projects and Workspaces UI components exist in the desktop app. | UI implementation exists; end-to-end selection/uncertain-scope behavior still needs review. No dedicated frontend test framework is currently present. |
| Isolation verification | Scope, retrieval, workspace execution, provisioning, background-task lifecycle, and API integration tests; Project Provisioning v1 previously accepted. | Accepted on candidate revision `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31`: 824 tests passed; compileall and diff-check passed; independent regression review found no remaining blockers. |

Phase 2 acceptance reconciliation (2026-11-24):
- CLI/API scope-sensitive behavior: accepted through the explicitly privileged and documented local-only CLI mode (`--i-understand-local-only`); it is not represented as Registry-scoped equivalence.
- Instruction trust/precedence: accepted by source review and existing tests; repository-provided instructions remain untrusted and cannot override global policy.
- Checkout overlap, symlink, and canonical-path protections: accepted by adversarial-path tests and source review.
- Task/plan scope continuity: accepted through approval/execution boundaries, cancellation, and restart recovery. Recovery preserves scope/history and marks unfinished work interrupted. **Automatic resumption or replay is explicitly unsupported and disabled** because external side effects may have completed immediately before interruption. A user who wants to continue must create a new task, which undergoes fresh scope validation. Durable pause/resume is deferred to Phase 5.
- Cross-project retrieval and execution isolation: accepted by the scoped-record, API, and execution-boundary regression tests.

**Phase 2 formal acceptance — ACCEPTED (2026-11-24).** Exact candidate revision: `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31`. Independent detached-worktree validation reported `python -m compileall -q src tests` exit 0; `python -m unittest discover -s tests -v` passed 824 tests with zero failures, errors, or skips; `git diff --check d11cb1de0b39d8a0367cb4d7098782da4354b006..HEAD` exit 0. The regression count improved from 823 tests with 8 failures and 3 errors to 824 passing tests. The original user checkout remained unchanged at `local-demo-ready-v1` / `a8ab59324caceab5b6fb2e5c674276c5ba96d072`; 32 pre-existing worktrees were preserved.

Acceptance scope is limited to Phase 2 project/workspace/instruction/context isolation and its documented privileged local-only CLI boundary. It does not imply durable task resumption: unfinished tasks are interrupted on restart, never silently replayed, and continuation requires a new scope-validated task. It does not authorize Phase 3 live dispatch or merge into the user's original checkout.

Original milestones and design detail:
1. Scope and authority contract.
   - Define minimum global/project/task scope fields and ownership rules.
   - Likely files: `src/evo_core/store.py`, `src/evo_core/orchestration.py`, architecture docs.
   - Tests: schema migration tests and scope-filter unit tests.
   - Acceptance: a documented, migration-safe scope contract exists; no silent cross-scope access.
2. Project-scoped conversation association.
   - Add optional project/workspace association to conversations without breaking existing conversations.
   - Likely files: `src/evo_core/store.py`, `src/evo_core/api.py`, `desktop/src/Workspaces.tsx` or Projects UI.
   - Tests: conversation create/open/list with and without project scope.
   - Acceptance: existing conversations remain valid; project association is explicit and inspectable.
2a. Task and agent-plan scope.
   - Associate tasks and agent plans with project, workspace, conversation, and execution context.
   - Mandatory when a project/workspace is supplied; optional only for explicitly global tasks.
   - Legacy global tasks remain readable and are represented as explicitly global, not as project work.
   - Preserve scope through approval, execution, interruption, recovery, and resumption.
   - Reject execution when the requested project/workspace does not match the authorized execution context.
   - Likely files: `src/evo_core/orchestration.py`, `src/evo_core/store.py`, `src/evo_core/api.py`, `src/evo_core/background_agent.py`.
   - Tests: task/plan creation, scope persistence, approval/execution mismatch rejection, recovery.
   - Acceptance: no task executes against an unauthorized or mismatched project/workspace.

2b. Command-policy enforcement.
   - Resolve effective command policy as the intersection of global and project policy.
   - Backend execution boundary enforces the resolved policy; UI restrictions are advisory only.
   - Likely files: `src/evo_core/workspace.py`, `src/evo_core/coding_agent.py`, `src/evo_core/workspaces.py`, configuration APIs.
   - Tests: permission expansion rejection, missing/invalid/ambiguous policy, project switching, wrong project/workspace execution.
   - Acceptance: project policy cannot broaden global permissions, and execution uses the resolved policy.

3. Project-scoped memory and retrieval.
   - Add scope to memory, lessons, and research; filter retrieval by active scope.
   - Likely files: `src/evo_core/store.py`, `src/evo_core/assistant.py`, memory APIs/UI.
   - Tests: retrieval isolation and global availability where intended.
   - Acceptance: project-specific records do not leak into unrelated project context.
4. Project-scoped instructions and configuration.
   - Distinguish trusted Evo-managed project instructions from repository files.
   - Bind runtime policy to Registry configuration where appropriate.
   - The command-policy model is already settled in milestone 2b: effective permissions are the intersection of global and project permissions. This milestone integrates and tests that model; it does not reopen it.
   - Likely files: `src/evo_core/workspaces.py`, `src/evo_core/coding_agent.py`, `src/evo_core/ai_configurations.py`, configuration APIs.
   - Tests: instruction precedence and command-policy enforcement.
   - Acceptance: repository files remain untrusted; trusted project policy cannot grant unauthorized capabilities.
5. Explicit project selection and switching UX.
   - Make active project explicit and inspectable; no silent switching.
   - Likely files: `desktop/src/ProjectsWorkspace.tsx`, `desktop/src/Workspaces.tsx`, `desktop/src/App.tsx`.
   - Tests: frontend build plus backend API tests; no dedicated frontend test framework currently exists.
   - Acceptance: uncertain project identity prevents implicit scope changes.
6. Isolation verification.
   - Add tests proving context, files, commands, and execution authority cannot leak across project boundaries.
   - Likely files: tests only, using existing temporary database/workspace fixtures.
   - Acceptance: cross-project retrieval and execution tests pass.

Out of scope for Phase 2:
- Project deletion or recursive cleanup.
- Automatic project selection or switching.
- Cross-project context consultation.
- Configuration-to-provider runtime binding beyond explicit validation.
- Cooperative multi-agent orchestration.
- New frontend frameworks or a wholesale UI redesign.

Risks and unresolved decisions:
- Whether project scope should be nullable for legacy global conversations.
- Whether global memory should be readable in every project by default.
- Whether project instructions should be editable through Evo or only repository files.
- How trusted project instructions are reviewed, versioned, and revoked.

Command policy is settled: effective permissions are the intersection of global and project permissions. Project policy can only restrict global permissions and cannot expand them. Missing, invalid, or ambiguous project policy must not silently grant broader access. Milestone 2b implements and enforces this model; milestone 4 tests instruction precedence and command-policy behavior against the already settled model.

**Phase 3 — Participant contracts and runtime binding**
**Phase 3 implementation status (2026-11-25; updated after P3.3 acceptance):**
- P3.1 executable configuration/contract foundations: accepted.
- P3.2 Registry-driven runtime binding, API-boundary invocation snapshots, and fail-closed worker continuity: **accepted**. Exact implementation validation target `7c50ff666b7cd684cf21f373a82badc3dad5627c`; 843 tests passed, compileall passed, and the only documentation whitespace finding was corrected in `11b173d7d7405c80f1ec6c5acb9087b5e1382646`. Later cumulative P3.3/P3.4/P3-R4 validations also passed.
- P3.3 OpenAI-compatible participant adapter: accepted at exact candidate 30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1; independent validation passed 863/863 tests, compileall, and cumulative diff-check. Formal evidence is recorded below.
- P3.4 deterministic verifier: implementation in progress. A bounded local-only verifier adapter is being integrated into revision-pinned Registry runtime construction; independent validation and acceptance are pending.
- P3.5 remains the first milestone permitted to enable live Registry-bound dispatch. No production dispatch authorizer is installed; no live provider dispatch or external provider calls are enabled.
- P3-R4 resource-admission design and telemetry freshness: accepted as the P3.5 design prerequisite; implementation belongs to P3.5.

- Runnable AI Configuration components use an explicit, versioned typed schema; legacy opaque schema-version 1 definitions remain readable but are not executable by default. Existing schema-1 workspaces require explicit migration preview, a new immutable schema-2 revision, and version-checked workspace rebind; no silent auto-migration.
- The first runtime integration proves that the exact immutable workspace-pinned configuration revision constructs and controls the complete assistant runtime for every workspace-bound entrypoint: chat turns, agent-plan proposal generation, and coding-agent/approved-plan execution. Creating a newer configuration revision does not invalidate an older revision already pinned by a workspace. The global TOML assistant remains a separate legacy path only for callers without a Registry-bound workspace; no silent fallback is permitted.
- The pinned revision determines provider/model, generation settings, context/memory/history budgets, persona guidance, and project command policy. Operator-owned global command ceilings and code-owned safety policy remain authoritative.
- Provider destinations and secrets are governed by operator-owned origin and environment-variable allowlists; non-loopback provider endpoints require HTTPS, and cross-origin redirects/embedded credentials are rejected. Provider compliance approval is separate and explicit per exact origin, adapter/interface, and use; endpoint allowlisting or health checks do not constitute compliance approval.
- At least two genuinely distinct production participant implementations can be registered and invoked through common, versioned contracts. A deterministic verifier is a distinct non-model participant; it does not count as an independent model judgment source. If Phase 4 requires independent model judgment, two independently addressable model endpoints are required.
- Secret resolution, cancellation semantics, and resource admission are explicit and bounded; missing secrets, unknown required capacity/quota, and unsupported components fail closed. Initial admission uses a durable atomic single-flight lease rather than an advisory telemetry endpoint or process-local semaphore.
- Participant identity, declared capabilities, availability, compliance status, trust evidence, role eligibility, and authorization are separate fields/concepts.
- Assignment/task ownership, permission attenuation, context envelopes, message provenance, handoff schemas, verification contracts, and bounded dispatch are explicit.
- Each dispatch is admitted against local resource reserves, concurrency caps, and provider quota/rate/token budgets; unknown required capacity or quota fails closed in the initial implementation. The initial concurrency control is a durable global single-flight lease; abandoned leases block new dispatch until safe recovery is established.
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

Use `README.md` for user-facing implemented behavior and `docs/ARCHITECTURE.md` for the evidence-based architecture inventory. Phase 2 is formally accepted. Phase 3 P3.1–P3.6 are accepted; P3.6 exact validation target is `4e048af7978730890c47ee840d36e8d0b73866ea`, merged through PR #4 at `0fde8e812efc79edc6cc20aa5d99b05fe1fcd51d`. The P3.6 corrective revalidation passed compileall, 43 focused API tests, the full 919-test suite, `git diff --check`, and the desktop TypeScript/Vite production build. P3.7 independent cumulative review and formal Phase 3 closure remain. `dispatch.enabled` remains false by default; no live provider calls were part of P3.6 acceptance. Evo-managed cooperative execution is not yet demonstrated. Existing agent runs/plans/background tasks, memory, experiment, and resource features are partial foundations; they must not be described as the target cooperative control plane.

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


### P3.3 OpenAI-compatible participant adapter — ACCEPTED (2026-11-25)

**Disposition: ACCEPTED at candidate `30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1`.** Independent detached-worktree validation verified the exact SHA, its parent `9227983befe938b9bd605acd9f54400861869def`, and cumulative base `6c12cf467cde61166be74e1e501e58de1c8decf6`.

Acceptance evidence supplied by the independent local validator:
- `python -m compileall -q src tests`: exit 0.
- Focused adapter, endpoint, provider/runtime/workspace/API/contract tests: 148 passed, zero failures/errors.
- `python -m unittest discover -s tests -v`: 863 passed, zero failures/errors/skips.
- `git diff --check 6c12cf467cde61166be74e1e501e58de1c8decf6..HEAD`: exit 0, no findings.
- The CRLF regression test contains actual CR/LF control characters; injection is rejected and ordinary JSON content type is accepted. Worker start ordering, pre-cancel behavior, cancellation event suppression, timeout bounds, and complete provenance fixtures were verified.
- Security review confirmed pinned Registry transport, TLS/peer/origin/DNS/redirect/proxy protections, bounded parsing and timeouts, secret non-disclosure, no Registry provider-factory injection, and no network activity during runtime construction.
- No API or worker path reaches live provider dispatch. No live provider calls were made.
- Original checkout remains `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072`, status unchanged; all 32 pre-existing worktrees preserved.

GPT-6 reviewed the cumulative change inventory and the current adapter/transport sources. The two defects found by the first independent validation (literal CR/LF validation and worker start after generator yield), plus the incomplete test fixtures, were corrected. The follow-up regression-test literal defect and whitespace finding were also corrected before this clean validation. No remaining P3.3 acceptance finding is recorded.

Acceptance is limited to P3.3 adapter implementation and its tested security/contract behavior. P3.2 and P3-R4 are separately accepted. P3.5 remains the first milestone permitted to enable live dispatch; no live dispatch or external provider calls are enabled.


### P3.4 deterministic verifier — formal acceptance (2026-11-25)

**Disposition: ACCEPTED** at exact candidate `ad04198b95708df58aae1ff07e0b38380671b574`, on `agent-plan-verification-hardening-v1`. P3.4 base: `30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1`; previous validation target: `781a0459d358532a3c71faa679d10128127207b5`; cumulative diff base: `6c12cf467cde61166be74e1e501e58de1c8decf6`.

Independent detached-worktree validation of the exact accepted SHA reported:
- `python -m compileall -q src tests`: exit 0.
- `python -m unittest tests.test_deterministic_verifier -v`: 14 tests passed.
- `python -m unittest tests.test_participant_contracts tests.test_runtime_binding -v`: 21 tests passed.
- `python -m unittest discover -s tests -v`: 877 tests passed, zero failures, errors, or skips.
- `git diff --check 6c12cf467cde61166be74e1e501e58de1c8decf6..HEAD` and `git diff --check 30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1..HEAD`: both exit 0.
- The final semantic correction was verified: the deterministic verifier's local completion self-test reports `transport_reachable=True`, `model_advertised=None`, and `completion_verified=True`.
- Source review confirmed bounded local JSON validation, shape-only evidence references (maximum 128 valid references), no reference resolution or truth claims, no shell/network/secret capability, immutable revision-specific binding, and no production invocation authorizer. Invocation fails closed without authorization; workspace configurations without a verifier remain compatible.
- No API or worker route can invoke either participant before P3.5. P3-R4 design is accepted; P3.5 implementation remains outstanding. No live provider calls or dispatch were enabled.
- The original checkout remained `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072`, with identical status; all 32 pre-existing worktrees were preserved. No tests were weakened or removed.

Acceptance is limited to P3.4's deterministic verifier implementation, exact-revision runtime binding, and the tested inert/fail-closed behavior. P3.2 and P3-R4 are separately accepted. P3.5 remains the first milestone permitted to enable live dispatch; no external provider calls are enabled.


### P3-R4 resource-admission design and telemetry freshness — ACCEPTED (2026-11-25)

**Disposition: ACCEPTED** at validated candidate `85b9f933a32dc45b72492dfee136edaad5c882fd` on `agent-plan-verification-hardening-v1`. Previous telemetry-fix candidate: `e13f3b2a3ee55a12d7c7afe16e0a35a29ed25810`; P3.4 accepted base: `ad04198b95708df58aae1ff07e0b38380671b574`; cumulative validation base: `6c12cf467cde61166be74e1e501e58de1c8decf6`.

Independent detached-worktree validation of the exact SHA reported:
- `python -m compileall -q src tests`: exit 0.
- `python -m unittest tests.test_telemetry -v`: 5 tests passed.
- `python -m unittest discover -s tests -v`: 879 tests passed, zero failures/errors/skips.
- `git diff --check ad04198b95708df58aae1ff07e0b38380671b574..HEAD`: exit 0.
- `git diff --check 6c12cf467cde61166be74e1e501e58de1c8decf6..HEAD`: exit 0.
- GPU-path regression proves exact order: GPU probe, GPU-process probe, then timestamp. The fixture was manually verified to parse as an available NVIDIA GPU with VRAM values.
- No-NVIDIA path retains valid CPU/RAM telemetry and a completion timestamp. The sampler assigns `sampled_at` after all collection probes and records nonnegative monotonic collection duration with UTC `Z` formatting.
- Existing telemetry fields remain intact; only the additive duration field and timestamp placement changed.
- No P3.5 admission or live dispatch was added or enabled. No unrelated behavior changed.
- Original checkout remained `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072`, status unchanged; all 32 pre-existing worktrees were preserved.

The initial independent challenge findings were addressed: timestamp completion semantics, CPU-utilization pressure handling, reserve/thermal scaling caveats, residency-attestation risk, unsupported GPU behavior, CPU-count unknown handling, adapter contract versioning, and scheduler separation are documented in the accepted contract. The first telemetry test's impossible assertion and a documentation whitespace issue were corrected; the final exact-SHA validation reports no findings.

Acceptance closes P3-R4's resource-admission design and telemetry-freshness prerequisite for P3.5 planning. It does **not** implement or accept P3.5 or authorize live dispatch/provider calls. P3.5 remains the first milestone that may enable live dispatch and still requires its authorization, budgets, durable atomic admission, and invocation lifecycle gates.


## P3.2 Registry-driven runtime binding — formal acceptance

**ACCEPTED — 2026-11-25.** Exact implementation validation target: `7c50ff666b7cd684cf21f373a82badc3dad5627c`; documentation-only whitespace correction: `11b173d7d7405c80f1ec6c5acb9087b5e1382646`.

Independent detached-worktree validation of the exact implementation target: compileall passed; full unittest suite passed (843 tests, zero failures/errors/skips); focused runtime, workspace-boundary, invocation-snapshot, and orchestration tests passed (100 tests). The sole review finding was trailing whitespace in documentation, corrected in the documentation-only follow-up; no application code or tests changed in that cleanup. Subsequent cumulative validation for P3.3 (863 tests), P3.4 (877 tests), and P3-R4 (879 tests) also passed, with cumulative diff checks clean.

Source review found no remaining P3.2 implementation blocker: workspace chat, plan proposal, plan execution, and coding-agent entrypoints create typed invocation snapshots; worker continuity verifies the exact pinned runtime and fails closed on revision drift; assistant turns persist invocation identity on both messages. Runtime construction remains inert and cannot dispatch to a live provider before P3.5. This acceptance covers P3.2 runtime binding and invocation-snapshot continuity only; it does not implement or accept P3.5, enable live dispatch, or imply that external provider calls occurred.


## P3.5 dispatch integration — formal acceptance (2026-11-25)

**Disposition: ACCEPTED.** Exact validated implementation target: `922051067fa41ecd75038714aafe96e514333f28` on `agent-p35-dispatch-admission-v1`; integration PR #3 merged into `agent-lifecycle-reconciliation-v1` at `ab01f90547c435ed158dc914583dbb21485e221f`.

Independent detached-worktree validation reported:
- `python -m compileall -q src tests`: exit 0.
- Focused seven-module suite: 117/117 passed.
- Full unittest suite: 916/916 passed; zero failures, errors, or skips.
- `git diff --check 3ab42edac54a46a28ae09112b24cf61f10d9a871..HEAD`: exit 0.
- Independent source/security review: no remaining findings; workspace-bound provider execution crosses authorization/admission before provider worker startup; budgets, approvals, resource checks, snapshots, leases, cancellation, timeout, recovery, and secret-safe diagnostics were reviewed.
- The three findings from the preceding validation were corrected and revalidated.
- Original checkout remained `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072`, status unchanged; all 32 pre-existing worktrees were preserved.

The user formally accepted P3.5 on 2026-11-25. No external provider calls were performed. `dispatch.enabled` remains false by default; acceptance does not enable live dispatch or change the operator's local configuration. P3.6 was subsequently accepted and merged through PR #4. P3.7 is the only remaining Phase 3 milestone.

## P3.6 participant inspection API — formally accepted (2026-11-25)

**ACCEPTED** at exact corrective implementation SHA `4e048af7978730890c47ee840d36e8d0b73866ea`, merged into `agent-lifecycle-reconciliation-v1` through PR #4 at `0fde8e812efc79edc6cc20aa5d99b05fe1fcd51d`.

Independent detached-worktree corrective revalidation verified the exact target SHA and preserved the original checkout (`local-demo-ready-v1`, HEAD `a8ab59324caceab5b6fb2e5c674276c5ba96d072`) and all 32 pre-existing worktrees. `python -m compileall -q src tests` passed; the focused API suite passed 43/43; the full unittest suite passed 919/919 with zero failures/errors/skips; `npm run build` in `desktop/` passed (`tsc -b && vite build`); and `git diff --check ab01f90..HEAD` passed. The only finding from the preceding candidate was the missing `component_key` and `component_version` fields in the frontend descriptor type; the direct correction resolved both TypeScript errors.

The accepted surface is read-only: exact-revision participant descriptors and bounded, ephemeral metadata preflight. It rejects unknown participant IDs, does not call `probe_completion`, does not create invocation records or leases, does not persist probe evidence, and does not leak provider exception text or secrets. A positive model-list result does not verify completion capability. Frontend checks are explicit user actions and stale responses are guarded. P3.6 does not bypass P3.5 admission or enable dispatch.

## P3.7 — remaining Phase 3 gate

P3.7 must independently review the cumulative accepted implementation and record the exact reviewed merge/base SHA, full Python validation, compile checks, frontend build, diff checks, migration coverage, deterministic participant contract results, local endpoint smoke-test availability/results, security findings, and explicit live-provider tests not performed. Any material finding must be corrected and revalidated before Phase 3 is closed. Phase 4 remains gated on this acceptance.
