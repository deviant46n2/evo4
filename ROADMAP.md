# Evo4 Roadmap

## Mission and priorities

Evo4 is a local-first, model-agnostic AI workbench and development system. Its immediate job is to make the user's existing computer more useful: run and manage local AI workloads efficiently, provide dependable local tools and execution, and let the user work with capable models without requiring paid cloud services.

The near-term product is a reliable personal assistant and coding/development environment that can use local models, local tools, and optional external providers. It should progressively take over the local inspection, editing, command execution, testing, build, and evidence-gathering work currently performed by Kilo, while keeping Kilo available as a useful implementation partner, independent challenger, and fallback. GPT-6 remains the current external reasoning and technical-lead partner. These are current operating roles, not permanent architectural dependencies.

The long-term ambition is broader: a user-controlled substrate for increasingly capable AI systems, potentially including superintelligence, developed through software engineering, memory, context, orchestration, tools, evaluation, and controlled research. That ambition is distant and is not a claim about current capability. Evo must earn each expansion through measured usefulness and reliability.

**Priority order:** useful local execution → effective hardware/runtime management → a dependable GPT-6-to-Evo development loop → measured local intelligence → stronger memory and evaluation → advanced cooperation and controlled self-improvement.

## Binding principles

- Local usefulness must not depend on a paid cloud subscription, paid model API, or a particular provider. Optional cloud providers and free tiers may extend capability but cannot be required for core operation.
- Optimize for the user's actual machine and workload first. Preserve desktop responsiveness and reserve enough CPU, RAM, VRAM, and I/O for the operating system and interactive use.
- Reuse existing implementations and data. Extend the current Registry, workspaces, managed worker, hardware telemetry, scheduler, agent, memory, and experiment foundations rather than replacing them without evidence.
- Deterministic software and tools should do deterministic work. Use models where reasoning, language understanding, code synthesis, diagnosis, or other measured capabilities add value.
- Select the least expensive reliable capability for each task. A larger or more numerous model/agent configuration is not automatically better.
- Keep local and external model/provider integrations interchangeable. No single model family, agent framework, or runtime is a permanent architectural foundation.
- Preserve user control, project isolation, least privilege, provider compliance, and explicit authorization at execution boundaries.
- GPT-6 owns technical leadership and architectural coherence in the current development workflow. Kilo remains a valuable local engineering partner; do not disable, remove, or artificially restrict it.
- A capability is not complete because it is designed or because an agent reports success. Record reproducible evidence and distinguish implemented, tested, reviewed, and accepted.
- Do not make autonomous self-modification, self-deployment, or open-ended background research a prerequisite for the useful local product.

## Document authority and phase status

This file is the sole authority for development sequence, priorities, dependencies, phase status, and acceptance gates. `docs/ARCHITECTURE.md` defines durable architecture and boundaries. `docs/PRODUCT-REDESIGN-PLAN.md` defines UX requirements. `docs/DEVELOPMENT-CONTROL-PLANE.md` defines proposed cooperative-development semantics. None of those documents may create a competing implementation sequence.

Phase status is evidence-based. Designed is not implemented; implemented is not tested; tested is not independently reviewed; and none of these alone means accepted.

## Unified roadmap

### Phase 1 — Governance, baseline, and architecture reconciliation
**Status: in progress.**

Reconcile the canonical documents with the user's current priorities, actual source state, security boundaries, and accepted decisions. This roadmap revision is a substantial correction of direction, not Phase 1 acceptance.

**Exit gate**
- Mission, near-term product, and long-term ambition are clearly distinguished.
- Document authority is unambiguous and dependent documents agree.
- Current, partial, proposed, and long-term capabilities are accurately separated.
- Security, recovery, authorization, and local/cloud dependency boundaries are explicit.
- Independent review finds no unresolved critical/high factual or architectural contradiction; user accepts closure.

### Phase 2 — Project, workspace, instruction, and context isolation
**Status: accepted (2026-11-24).**

Formal acceptance covers project/workspace scope, checkout isolation, command-policy intersection, context retrieval boundaries, and task/plan scope continuity through interruption and restart recovery. Automatic replay/resumption remains disabled; continuation requires a new task with fresh scope validation. Project deletion and durable pause/resume remain deferred.

### Phase 3 — Participant contracts and runtime integration
**Status: accepted (2026-11-25).**

P3.1–P3.7 are formally accepted. The cumulative independent P3.7 review passed at exact target `e65e69afa8e074e52d73b7949b8702eaecd653b5`. Registry-bound runtime construction, participant adapters, deterministic verification, dispatch admission, and participant inspection are established foundations. Dispatch remains disabled by default; acceptance did not enable live dispatch or establish that every provider/model can complete work.

### Phase 4 — Local execution bridge
**Status: priority next phase; not accepted.**

Turn Evo's existing workspace, managed-worker, coding-agent, approval, and task foundations into a dependable local execution capability. The objective is not merely to launch an allowlisted command: Evo must become able to take a bounded task from intent through local repository inspection, proposed edits, execution, verification, and a reviewable result.

**Scope**
- Workspace-bound local filesystem inspection and safe file operations, with explicit scope and provenance.
- Isolated task workspaces/worktrees for code changes; never silently operate in a dirty or unrelated checkout.
- A structured execution contract for commands, working directory, environment, timeout, output limits, resource budget, and expected artifacts.
- User-visible approval for consequential writes and commands; argv-based execution rather than shell-string construction.
- Managed process lifecycle for processes Evo starts: start, observe, bounded logs, timeout, cooperative cancellation, terminal-state recording, and safe recovery.
- Reliable test/build invocation, exit-code capture, artifact collection, and truthful reporting.
- Background execution while the user continues chatting; clear task state and safe interruption boundaries.
- A local CLI/API path for diagnosis and recovery that does not depend on the desktop or an AI provider.

**Exit benchmark**
Given a GPT-6-authored, bounded repository task and an explicitly selected workspace, Evo can inspect the correct source revision, prepare and apply an authorized change, run the specified checks, collect a diff and bounded logs/artifacts, and return an accurate result. A reviewer can reproduce the result. No unrelated checkout, process, or user data is modified.

**Boundaries**
- Kilo remains available throughout this phase and afterward.
- Evo may supervise only processes it starts and owns. It must not attach to, signal, kill, or reconfigure unrelated processes or an existing inference server.
- No autonomous merge, deployment, destructive cleanup, or privilege expansion.
- The existing Phase 4 cooperative-experiment ledger/accounting work is retained as reusable evaluation infrastructure. The live multi-participant benchmark is deferred; it is not a prerequisite for local execution.

### Product UX milestone — Chat-first redesign
**Status: scheduled next, immediately after Phase 4 acceptance and before Phase 5 is considered user-facing complete.**

The redesign is an explicit product priority, not optional polish. The goal is to make Evo feel like one coherent assistant/workbench rather than a collection of disconnected subsystem screens. Preserve the existing backend, Registry, execution, approval, and evidence foundations; redesign how users reach and understand them.

**Scope**
- Chat is the primary home and task-launch surface. A user working in a project can start a task in that project without hunting through the Agents area or manually understanding Registry internals.
- Agent/task activity appears inline in chat with status, progress, approvals, cancellation, and links to detailed evidence.
- Projects provide clear project context, instructions, workspace readiness, and a direct “new task” action. Missing prerequisites must be explained with a clear next step.
- Memory, hardware/runtime, configurations/Cyberdeck, experiments, and supporting capabilities become coherent views accessible from a minimal, consistent navigation structure.
- Visual hierarchy, responsive layout, accessibility, empty/error/loading states, and interaction consistency receive a deliberate pass.
- Preserve project/workspace isolation, explicit approvals, least privilege, and truthful capability status. The redesign must not bypass backend safety controls.
- Reuse current APIs and components where sound; redesign is not permission for an unnecessary backend rewrite.

**Acceptance**
- A user can enter a project, start a bounded task, follow it in chat, approve/reject consequential actions, and inspect its final review/evidence without navigating an unrelated subsystem.
- Project/workspace/task scope is visible and remains correct throughout the workflow.
- Primary navigation and core workflows are coherent, keyboard-accessible, and validated by desktop build plus focused frontend/integration tests.
- The user reviews the working experience before the redesign is accepted.

### Phase 5 — Hardware and model-runtime management
**Status: planned; depends on Phase 4 execution lifecycle.**

Make local compute use observable, predictable, and efficient without making the desktop unusable.

**Scope**
- Accurate CPU, RAM, GPU, VRAM, temperature, power, process, and runtime telemetry with explicit unknown/stale states.
- Model/runtime inventory, compatibility metadata, context/KV-cache estimates, and measured load profiles.
- Resource admission and scheduling that account for interactive desktop reserves, competing workloads, provider limits, and uncertainty.
- Managed lifecycle for runtimes Evo explicitly launches: start, readiness checks, health, bounded logs, stop, timeout, and recovery.
- Runtime profiles and model selection based on measured quality, latency, memory, throughput, and workload needs.
- Safe context/concurrency selection and graceful defer/reject behavior when capacity is insufficient.
- User-visible recommendations and reversible controls before any setting is applied.

**Exit benchmark**
For representative local workloads, Evo can recommend and execute an authorized runtime configuration, explain expected and observed resource use, avoid oversubscription, and preserve an agreed desktop-responsiveness reserve. Results are measured against a documented baseline.

**Boundaries**
- Telemetry and recommendations are not proof of hard resource isolation.
- Runtime control applies only to processes Evo owns or to integrations with an explicit supported control contract and user authorization.
- No GPU clock/power modification, driver changes, or arbitrary process termination in this phase.

### Phase 6 — GPT-6 ↔ Evo local development loop
**Status: planned; depends on Phases 4 and 5.**

Make Evo the dependable local execution partner for the current GPT-6-led engineering workflow. Direct integration with an external ChatGPT session is not assumed; begin with explicit, inspectable task and artifact handoffs.

**Scope**
- A task package containing objective, source revision, workspace, scope, acceptance criteria, permitted actions, resource/time budgets, and expected outputs.
- Evo inspects the local repository and reports relevant source/context before acting.
- GPT-6 can provide a plan, patch, or bounded implementation instructions; Evo applies or implements only within the approved task scope.
- Evo runs tests/builds, gathers logs and artifacts, and returns exact revisions, diffs, and evidence.
- User can inspect, interrupt, redirect, approve, or reject work without losing task history.
- Kilo can independently inspect, implement alternatives, challenge assumptions, or reproduce validation. It is not removed from the workflow.
- Handoffs are durable and provider-agnostic; Git remains a supported bridge.

**Exit benchmark**
Across a representative task suite, Evo reliably completes the local-hands portion of tasks that currently require Kilo: repository discovery, scoped editing, command/test/build execution, artifact capture, and accurate reporting. Measure completion rate, defects, rework, time, resource cost, and human intervention. Do not claim parity based on a single successful task.

### Phase 7 — Useful local intelligence
**Status: planned; depends on reliable execution and hardware management.**

Use local models where they provide measurable value, without forcing every operation through an LLM.

**Scope**
- Local model routing by task class and measured capability.
- Repository exploration, code understanding, bounded implementation, log analysis, test-failure diagnosis, summarization, and memory retrieval.
- Model/runtime profiles that record context limits, quality, speed, memory footprint, failure modes, and uncertainty.
- Tool-first workflows with model assistance at explicit reasoning boundaries.
- Optional free/cloud providers as replaceable fallbacks or additional capability; paid cloud access remains optional.
- Evaluation against deterministic baselines and human-reviewed task outcomes.

**Exit benchmark**
Local-model-assisted workflows improve a declared task class over deterministic/tool-only or existing baselines without unacceptable correctness, latency, resource, or safety regressions. Neutral or negative results are retained and do not justify more complexity.

### Phase 8 — Persistent memory and context effectiveness
**Status: planned; existing memory foundations are reusable.**

Build reliable continuity and retrieval across long-running work without depending on stuffing entire histories into a context window.

**Scope**
- User-controlled, provenance-preserving records with timestamps, source, confidence/epistemic status, and correction/supersession history.
- Retrieval across large archives through multiple complementary passes, with explicit scope and access controls.
- Project/task context reconstruction and compact, updateable working-state summaries.
- Retrieval evaluation on representative held-out queries, including exact recall, contradiction, stale facts, and cross-project leakage.
- Inspectable retrieval evidence and user correction; uncertain retrieval must remain uncertain.

**Exit benchmark**
A defined recall/evaluation suite demonstrates reliable retrieval and correct scope handling at increasing archive sizes. Do not claim near-perfect recall without measured evidence.

### Phase 9 — Evaluation and reusable capability library
**Status: planned; evaluation foundations exist.**

Make improvements measurable and preserve what works.

**Scope**
- Reproducible experiment/task records pinned to code, configuration, model/runtime, environment, inputs, and policies.
- Quality/correctness, latency, throughput, tokens/compute, RAM/VRAM, energy/power where measurable, cost, failures, and human intervention.
- Task-class reliability profiles with sample counts and uncertainty.
- Reusable, versioned workflows, tools, prompts, adapters, runtime profiles, and evaluation suites.
- Explicit policy for using reliability evidence in recommendations; scores never silently grant permissions.

**Exit benchmark**
A third party can reproduce a reported improvement from retained artifacts and compare it against a declared baseline. Negative and inconclusive results remain accessible.

### Phase 10 — Cooperative intelligence and advanced orchestration
**Status: deferred until earlier phases establish practical value and safety.**

Resume the proposed cooperative vertical slice only when it answers a concrete need that cannot be met more simply by one model plus tools. Reuse the existing experiment design and accounting work.

**Scope**
- Specialist decomposition, independent attempts, or implementer/challenger patterns through Evo's own runtime contracts.
- Distinct participant identities and revision-pinned configurations.
- Durable assignments, handoffs, provenance, synthesis, bounded disagreement, cancellation, recovery, and permission/resource attenuation.
- Isolated workspaces for concurrent code changes.
- A matched, predeclared comparison against a single-participant baseline, accounting for compute, latency, cost, and human intervention.

**Exit benchmark**
A reproducible task suite shows net benefit for a declared task class without material correctness or safety regression. A tie or loss is a valid finding and does not justify expanding coordination.

### Phase 11 — Progressive autonomy and controlled system research
**Status: long-term; no present authorization for autonomous self-modification or deployment.**

Only after execution, recovery, evaluation, memory, and authorization are demonstrated may Evo progressively conduct bounded research, design isolated experiments, propose changes, and validate improvements. Each action class requires explicit scope, budget, rollback, independent evidence, and user-governed authorization. Self-assessment alone never promotes a change.

## Cross-cutting product and UX work

The desktop remains chat-first. The dedicated Chat-first redesign milestone above is the required next product priority after Phase 4 acceptance; it is not optional polish. Projects, memory, runtime state, tasks, approvals, execution evidence, and experiments should appear as coherent views into real backend capabilities. Frontend and end-to-end test coverage should grow with workflow complexity.

## Dependency rules

- Phase 1 document reconciliation does not authorize unsafe implementation or close itself.
- Phase 2 isolation and Phase 3 runtime contracts are accepted prerequisites for scoped local and model execution.
- Phase 4 establishes safe local filesystem/command/process execution. Phase 5 builds resource/runtime management on that lifecycle.
- Phase 6 integrates GPT-6-authored work with Evo's local execution; it does not require direct access to a ChatGPT session.
- Phase 7 uses the execution and resource controls from Phases 4–5; local model use must be measured.
- Phase 8 improves continuity and retrieval but cannot weaken Phase 2 scope isolation.
- Phase 9 evaluates capabilities introduced by all earlier phases.
- Phase 10 reuses the experiment ledger and design but is not a gate for local usefulness.
- Phase 11 depends on all preceding safety, recovery, evaluation, memory, and authorization foundations.

## Current disposition of earlier cooperative roadmap work

The Phase 4 cooperative-experiment design, participant/handoff contracts, and experiment accounting implementation are retained. The latest accounting correction at `591126548d08b40e1112690443a9b2688158eb05` passed independent Kilo validation: focused tests 58/58, full tests 978/978, compileall, desktop production build, and diff-check. This validates that accounting change only; it does not accept Phase 4 as a whole or demonstrate live cooperative execution. The cooperative benchmark is deliberately resequenced to Phase 10.

## Current accepted foundation

- Phase 2 project/workspace/context isolation: accepted 2026-11-24.
- Phase 3 participant contracts and runtime integration: accepted 2026-11-25.
- Project Provisioning v1: implemented, reviewed, accepted, and closed at `d0b56afee86b208aab738994cee8a13c63bff107`.
- Existing managed workload execution, hardware telemetry/advisory admission, background agent tasks, plans/approvals/cancellation, memory retrieval, experiment records, and Registry/runtime integration are partial foundations. Consult `README.md` and subsystem specifications for exact current behavior; none should be overstated as a complete local execution or hardware management system.
- Dispatch remains disabled by default unless separately configured and authorized.
