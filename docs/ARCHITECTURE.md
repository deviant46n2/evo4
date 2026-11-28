# Evo 4 Architecture

This document describes Evo4's intended architecture. It distinguishes current implementation from designed and long-term capabilities.

## Evo's identity and operating priority

Evo4 is a local-first, model-agnostic AI workbench and development system. Its immediate product objective is to make the user's existing hardware more useful through dependable local execution, resource-aware model/runtime management, and a practical assistant and coding workflow.

Evo should progressively take over local repository inspection, editing, command execution, testing, build, and evidence-gathering work currently performed by Kilo. GPT-6 is the current external reasoning and technical-lead partner; Kilo remains a useful local engineering partner, independent challenger, and fallback. These roles describe the present workflow, not permanent architectural dependencies. Evo does not currently directly control either external session.

Local operation must remain useful without paid cloud services. Models, runtimes, agent frameworks, and external providers are replaceable components. Optional cloud integrations may add capability but must not become hidden requirements.

The long-term ambition is a user-controlled substrate for increasingly capable AI systems, potentially including superintelligence, through software engineering, memory, context, tools, orchestration, evaluation, and controlled research. This is a distant ambition, not a current capability claim.

Evo is not a foundation-model trainer or custom neural-network engineering project. It should use existing models and software as components, and use deterministic tools for deterministic work. Cooperative multi-agent execution is a later capability to be justified by measured benefit, not the immediate product objective.

Provider terms, policies, licensing, supported interfaces, API rules, and data-handling requirements must be respected.

## Fundamental entities

### Evo
The portable application providing shared infrastructure, management, integration interfaces, experimentation, evaluation, orchestration, resource management, and development capabilities.

### AI configurations
Reusable, independently versioned definitions of AI systems. A configuration may specify model/provider assignments, agent definitions and roles, memory architecture and namespaces, retrieval/context strategies, tools and integrations, orchestration strategies, execution preferences, resource requirements and limits, permissions and policies, and component versions/dependencies.

Configurations must be independently developed, versioned, branched, compared, restored, and promoted. They must not belong to a particular software project.

### Software projects
Independent development targets with their own source code, repository references, branches, permissions, dependencies, and history. A project may be Evo itself or unrelated software.

### Workspaces and sessions
Runtime environments connecting an AI configuration to one or more authorized development targets. A workspace establishes actual assignments and access boundaries. One configuration should eventually be usable against multiple projects with independent sessions/workspaces, and multiple configurations should be usable against the same project. The configuration does not own the project, and the project does not own the configuration.

### Experiments
Persistent, identifiable investigations combining a configuration, target, hypothesis, methodology, and evaluation. They must preserve hypothesis/objectives, exact configuration version, exact software-project commit/revision, relevant execution environment, model/provider identities, settings and dependencies, methodology and inputs, resource consumption, results and measurements, failures and incomplete runs, conclusions and decisions, reproducibility information, and references to source changes/artifacts. Failed experiments are valuable engineering knowledge.

### Execution environments
Infrastructure on which models, agents, tools, and experiments execute. The architecture must eventually support local execution, connected machines, external cloud providers, containers/isolated environments, and distributed execution. Execution location must not be hardcoded into the fundamental architecture.

### Resource management
A distinct subsystem responsible for discovering and managing compute, memory, models, endpoints, concurrency, provider quotas, costs, task priorities, reservations, and scheduling. It must accommodate both resource-constrained single-user installations and large distributed deployments. Coordination overhead and available resources must inform scheduling; more agents do not automatically improve results.

### Participants and capabilities
A participant is an independently identifiable source of work or capability that Evo may coordinate. Participant types include model endpoints, agent runtimes, tools, external services, and human contributors. A model is not automatically an agent; an agent may use one or more models and tools; a tool may be invoked directly or by an agent. These distinctions must not be collapsed into provider-specific assumptions.

A participant definition should eventually capture stable identity, type, version, declared capabilities, supported input/output contracts, availability, execution location, resource requirements, provenance, trust/evaluation status, and integration/compliance constraints. Declared capability is not proof of reliability, and registration is not authorization. Runtime availability and authorization are separate states.

Roles such as planner, implementer, researcher, reviewer, or verifier are task-scoped responsibilities assigned to eligible participants. Roles are not permanent identities and must not be hardcoded to GPT-6, Kilo, or any specific provider.

### Tasks, assignments, and collaboration records
A task is a durable unit of work with an objective, scope, acceptance criteria, accountable owner, authorized resources, and lifecycle. A task may contain bounded subtasks and assignments to multiple participants, but exactly one owner remains accountable for the overall task outcome.

Assignments define which participant is responsible for a bounded contribution, under what permissions, inputs, output contract, resource budget, and deadline. Handoffs transfer responsibility for a defined next action; they do not silently transfer authority or expand scope.

Messages, artifacts, observations, decisions, challenges, and verification results are durable collaboration records. They retain authorship, timestamps, task/assignment association, provenance, trust classification, and references to relevant source revisions. Retrieved or participant-supplied content is evidence/data, not privileged instruction. Conflicting claims remain attributable and inspectable rather than being silently merged into one asserted truth.

## Conceptual relationship

```text
Evo provides the platform.
AI configurations define reusable AI systems.
Software projects define development targets.
Workspaces and sessions connect configurations to authorized targets.
Experiments investigate and evaluate combinations of configurations, targets, and execution environments.
The experiment registry and artifact storage preserve results and evidence.
Resource management determines what can execute and where.
```

These entities must be independently identifiable and maintain appropriate histories.

## Cooperation as a long-term architectural capability

Cooperation remains an important long-term architectural capability, but it is not the immediate product or implementation priority. Local execution, hardware/runtime management, and measured local intelligence come first. Evo should support, without prematurely implementing everything:

- Heterogeneous participants: models, agents, tools, external services, and human participants.
- Explicit identities, capabilities, compatibility, availability, and lifecycle for participants.
- Task ownership and bounded delegation.
- Communication, handoffs, challenges, and independent review.
- Shared context with provenance and scope.
- Explicit authority, trust, and permissions.
- Durable task state, evidence, decisions, and history.
- Failure handling, cancellation, timeouts, recovery, and loop prevention.
- Resource-aware admission, scheduling, concurrency, and budgets.
- Provider-compliant adapters and integration boundaries.
- Replaceable participants and roles, with no fixed model-specific architecture.

Governance remains hybrid: hierarchical authority and accountability for consequential decisions, with cooperative deliberation and delegation inside authorized scopes. Every task has one accountable owner. Agents cannot grant themselves permissions.

Cooperation must be evaluated empirically. More agents do not automatically produce better results. Evo must measure whether collaboration improves correctness, quality, reliability, time, resource use, or other task-relevant outcomes compared with individual participants.

## Version control and persistent engineering knowledge

AI configurations and software projects must have independent version histories. The architecture should support independent Git-backed histories and branching without assuming every entity requires a separate physical Git repository.

Use Git for source code, configuration definitions, versioned documentation, and reproducible development states. Use a persistent experiment registry for structured experiment records and searchable findings. Use artifact storage for large logs, datasets, benchmark outputs, and other large files.

Every experiment should reference exact relevant source commits, configuration revisions, and execution environment. Successful approaches, failures, abandoned hypotheses, and unexpected discoveries should be retained. Evo should be able to search historical findings and avoid unknowingly repeating unsuccessful experiments. Git should not become an indiscriminate dumping ground for large binary artifacts.

## Current implementation status

The immediate roadmap priority is the local execution bridge, followed by hardware/model-runtime management and the GPT-6-to-Evo local development loop. See `ROADMAP.md` for sequencing and acceptance gates. Existing telemetry, advisory admission/scheduling, and managed workload execution are useful foundations but do not yet constitute complete hardware/runtime management or a general local development executor.

Implemented capabilities are described in `README.md` and existing docs, especially `docs/AGENT-ORCHESTRATION.md` and `docs/BACKGROUND-AGENT-EXECUTION.md`.

Platform Registry v1 provides AI configurations and immutable revisions, software projects, project checkouts, workspaces, and registered-workspace execution resolution. Phase 2 project/workspace/context isolation and Phase 3 Registry-bound runtime integration are formally accepted; see `ROADMAP.md` and their acceptance records for exact scope. Existing experiment storage/runner/evaluation, hardware telemetry and advisory admission/scheduling, managed workload execution, background agent tasks, plans, approvals, cancellation, recovery, and lifecycle reconciliation are useful but partial foundations. They are not a unified cooperative control plane or a complete local development executor, and the workload scheduler is not a general task execution scheduler.

## Long-term self-development

Evo should eventually participate extensively in its own development: understanding its architecture and history, identifying weaknesses and opportunities, researching solutions, designing and running isolated experiments, implementing improvements in controlled environments, validating changes independently, proposing or integrating approved improvements, and improving its own research and development processes.

Autonomy should increase as reliability is demonstrated. Routine, reversible, authorized work should eventually be autonomous. Consequential operations require safeguards and appropriate approval. Safety, authorization, demonstrated reliability, and available resources constrain autonomy; there is no arbitrary prohibition on self-development.

Evo must not be allowed to declare its own improvements successful without independent evidence.

Self-improvement is a long-term capability, not something required in the initial release.

## Agent collaboration and governance

Retain the hybrid model:

- Hierarchical governance for authority, permissions, accountability, and consequential decisions.
- Cooperative agent-to-agent communication, research, challenges, task delegation, and handoffs within authorized scopes.
- Dynamic, replaceable roles rather than permanent model-specific dependencies.
- One accountable owner per task.
- No requirement for the user to manually relay messages once authorized direct integrations are available.
- Bounded delegation, concurrency, budgets, timeouts, and loop prevention.
- Persistent task history, communication records, evidence, and decisions.
- Explicit capability, trust, and authority separation.
- Progressive agent evaluation and authorization.
- Immediate suspension and revocation capability.
- Provider-specific compliance verification.

Provider terms, licensing, API permissions, automation restrictions, and data-handling rules must be respected. No bypasses or undocumented interfaces.

Agent lifecycle: discovery, evaluation, registration, authorization, availability, assignment, active work, suspension, retirement, and revocation.

A governed development control plane is a long-term platform capability. The immediate product does not depend on heterogeneous multi-agent orchestration; local execution and resource management come first. Any future control plane requires an independent minimal bootstrap and recovery mechanism.

## Development philosophy and implementation strategy

Real AI models are not required to make substantial progress. Use deterministic mocks, simulated agents, fixtures, and conventional tests to develop and validate the platform. Real models become integration targets and experimental subjects.

Build interfaces for eventual capabilities without implementing all of them prematurely. Keep scope focused on improving AI systems through software architecture and engineering. Reuse existing software and research where practical. Preserve useful existing implementation rather than assuming a rewrite is necessary.

Every significant milestone should deliver a reusable capability, an experimentally validated improvement, or a measurable increase in what Evo can support.

## Initial deployment and portability

Initial release: single user, local-first, no mandatory accounts or cloud services, local project/configuration storage, optional cloud providers, secrets stored separately from project/configuration repositories, portable definitions where practical.

Eventually support export/import, reconstruction on another machine, and multi-user authentication. Do not make future multi-user support a prerequisite for initial development. Design for portability without sacrificing immediate optimization for the user's existing hardware.

## Platform Registry

The persistent platform entity model is specified in `docs/PLATFORM-REGISTRY-V1-SPEC.md`. Registry v1 has been implemented through M5; later registry capabilities remain planned.

## Platform-wide design principles and engineering contracts

These principles are binding architectural guidance. They do not require every future subsystem to be implemented immediately. Any justified exception should be explicit, scoped, and documented. Specialized governance details are maintained in `docs/DEVELOPMENT-CONTROL-PLANE.md`.

### 1. Ownership and authority

- Every persistent entity and record has a defined authoritative owner.
- Distinguish authoritative source data from derived, cached, indexed, or replicated data.
- Derived data must not silently override its authoritative source.
- Cross-subsystem ownership and mutation responsibilities must be explicit.

### 2. Component lifecycle

- Define a general lifecycle: discovery → evaluation → registration → authorization → availability → assignment/use → upgrade or replacement → suspension/retirement/revocation.
- Registration is not authorization.
- Components must be replaceable without requiring unrelated subsystems to be redesigned.
- Preserve identity, version, provenance, compatibility, and relevant history through upgrades and replacements.
- This does not prescribe a complete component manager implementation.

### 3. Contracts and integration boundaries

- Evo owns platform-level interfaces and contracts.
- External providers, models, frameworks, agents, and tools integrate through adapters or explicit interfaces.
- Provider-specific details remain behind integration boundaries where practical.
- Optional integrations must not become hidden mandatory dependencies.
- Contract changes must consider compatibility and migration.

### 4. Data integrity and provenance

- Persistent records require stable identity and appropriate timestamps, versions, and provenance.
- Important mutations must be atomic.
- Preserve meaningful history, including failures, supersession, and contradictions where relevant.
- Define explicit ownership and retention rules before introducing destructive operations.
- Use the appropriate store for each domain; do not create duplicate sources of truth.

### 5. Security, trust, and authority

- Capability, trust, and permission are distinct concepts.
- Possessing a capability or being registered does not grant permission to exercise it.
- Access must be scoped to an authorized task, target, and execution context.
- Preserve approval, isolation, path-containment, secret-handling, and command-allowlist boundaries.
- No subsystem may silently expand its own authority.
- Provider terms, licensing, API rules, and automation restrictions remain mandatory.

### 6. Shared resource management

- Resource discovery, ownership, admission, reservations, limits, priorities, and scheduling are platform responsibilities.
- No subsystem may assume exclusive ownership of shared compute, memory, endpoints, or provider quotas without an explicit reservation or policy.
- Resource decisions must account for competing workloads and available headroom.
- More agents or parallelism are not automatically better.
- This defines architectural ownership, not a requirement to implement a scheduler now.

### 7. Evaluation and evidence

- Capability claims require defined acceptance criteria and observed evidence.
- Record relevant configuration/version, software revision, environment, inputs, methodology, and results for reproducibility.
- Distinguish deterministic tests, integration tests, live-model tests, and independent acceptance checks.
- Preserve failures and incomplete runs.
- An agent or subsystem must not be the sole authority validating its own consequential improvements.
- Evaluation rigor should be proportionate to risk and impact.

### 8. Recovery and operational resilience

- Persistence migrations must be transactional and fail safely.
- Important state must have a documented recovery strategy appropriate to its criticality.
- Bootstrap, diagnosis, and minimum recovery capabilities must not depend entirely on the subsystem they are intended to repair.
- Do not mandate a distributed recovery architecture now.

### 9. Progressive autonomy

- Autonomy grows with demonstrated reliability, explicit authorization, safeguards, and available resources.
- Routine reversible authorized operations may eventually be autonomous.
- Consequential operations require appropriate safeguards and approvals.
- Do not impose arbitrary restrictions that prevent future self-development.

### 10. Incremental implementation

- Build the smallest useful capability that satisfies its acceptance criteria.
- Preserve extension points where justified, but do not build speculative abstractions or future infrastructure without a demonstrated need.
- Reuse existing software and research when practical.
- Existing working capabilities must be preserved unless a deliberate, validated replacement is approved.


## Current vs designed vs long-term

1. Current implemented capabilities: described in `README.md` and existing docs.
2. Designed but not yet implemented architecture: this document and `docs/DEVELOPMENT-CONTROL-PLANE.md`.
3. Long-term ambitions: increasingly capable, potentially superintelligent AI systems through software engineering, including controlled self-improvement.

No proposed capability should be described as already implemented.


## Isolation threat model and current gaps

Project isolation is a security boundary, not a UI convention. The target model must prevent accidental or unauthorized cross-project access through every entry point: desktop API, CLI, background worker, tool execution, retrieval, and future participant adapters.

| Boundary | Current evidence/status | Required target behavior |
|---|---|---|
| API coding-agent workspace path | API agent launch resolves a registered workspace and its checkout path before constructing the coding agent. | Retain server-side resolution and validate authorization on every execution boundary. |
| CLI workspace path | `evo code --workspace` accepts a filesystem path directly. | Make CLI and API semantics equivalent, or explicitly isolate a privileged local-only mode with clear warnings and no claim of Registry-enforced isolation. |
| Checkout overlap | Registry enforces unique canonical checkout paths, but the schema does not by itself reject ancestor/descendant overlap. | Reject unsafe overlaps after canonicalization; define a deliberate, auditable exception mechanism if nested checkouts are ever needed. |
| Persistent context | Conversations, messages, memories, memory candidates, lessons, research documents, tasks, and agent plans now carry project/workspace scope fields where applicable. Store and API retrieval/write paths apply scope filters, and assistant context assembly resolves conversation scope. This is implementation evidence; it is not proof that every acceptance gate, adversarial case, or CLI/API equivalence check is closed. | Continue the Phase 2 isolation gate and Phase 3 runtime-binding work. Every retrieval/write path must apply the scope filter, not just the UI. |
| Configuration binding | Registry workspaces reference a configuration and immutable revision, but current agent construction does not resolve that revision into a runtime participant; capabilities report provider selection as unavailable. | Resolve configuration revisions into validated runtime adapters and enforce per-project model/provider/tool/command policy. |
| Command policy | Coding-agent execution applies the workspace configuration's project command prefixes intersected with the global allowlist. Agent-plan proposal generation still uses the global allowlist and does not yet apply that project-specific intersection. | Enforce the effective policy consistently at every relevant boundary, including proposal, approval, and execution. Project policy can only narrow global permissions and cannot expand them; this is a command allowlist boundary, not an OS-level sandbox. |
| Project instructions | Repository files such as README/AGENTS content are treated as untrusted project data by the coding agent. | Keep trusted Evo-managed project instructions/metadata separate from repository-provided instructions. Repository files remain untrusted context and cannot elevate permissions or override platform policy. |
| Context budget composition | Coding-agent policy and command-allowlist text is appended after the assistant message builder has applied its current context fitting. This can cause the final prompt to exceed the budget calculated by that builder. | Include all system policy, retrieved context, history, and tool policy in one final budget calculation; test truncation priority and policy retention. This is a post-freeze implementation finding, not changed by this documentation pass. |

This table describes known boundaries from source inspection, not a complete penetration test. It is a roadmap for closing gaps, not a claim that current projects are fully isolated.

### Instruction trust model

There are three distinct layers:
1. **Platform policy:** trusted Evo-owned system/developer policy. It cannot be overridden by project content or participant messages.
2. **Evo-managed project policy:** user-authored project metadata/instructions stored and versioned by Evo, scoped to a project/workspace, with explicit trust and provenance. It may constrain work but cannot grant capabilities beyond platform authorization.
3. **Repository-provided content:** README, AGENTS.md, comments, build files, generated files, and other checkout contents. Treat as untrusted data. They may describe project conventions but cannot override platform policy, reveal secrets, expand command allowlists, or authorize writes/commands.

A future UI must make the source and trust level of project instructions inspectable. Do not silently promote repository files into trusted Evo-managed policy.

## Persistence and entity reconciliation

The current persistence model is a transitional implementation, not yet the target unified task store:
- `EvoStore` owns conversations/messages, memories and relations/candidates, lessons, research documents, lightweight user tasks, agent runs, tool events, feedback, and platform Registry tables.
- `ResultsDB` owns experiment runs/artifacts metadata, resource samples, workload scheduler jobs, background agent tasks, agent plans/steps, and related execution records.
- The lifecycle subsystem opens the same SQLite database through separate connections. It records durable terminal decisions and reconciliation events because a single SQLite transaction cannot currently span those connections. This is an explicit reconciliation mechanism, not atomic cross-store persistence.
- The existing tables `tasks`, `agent_runs`, `background_tasks`, `agent_plans`, and `workload_jobs` represent different current concepts and must not be casually renamed or collapsed into one generic Task table.

Target conceptual mapping:
- **Task:** durable objective, scope, accountable owner, acceptance criteria, dependencies, and overall lifecycle.
- **Assignment:** a bounded contribution assigned to one participant under attenuated permissions and budgets.
- **Execution/run:** one concrete attempt by a participant/adapter to fulfill an assignment.
- **Plan/step:** an optional decomposition/proposal representation; it is not itself equivalent to a task or execution.
- **Workload job/reservation:** resource scheduling/admission state; it is not a task completion record.
- **Conversation/message:** interaction and evidence context, associated with a task/project only through explicit scoped references.

Before adding new cooperative task schemas, map existing records and lifecycle transitions to these concepts, identify authoritative fields and migration paths, and avoid creating duplicate sources of truth. A future single-connection/transaction boundary may be preferable, but consolidation is a design decision requiring migration/recovery analysis; the current reconciliation ledger must not be silently discarded.



## CLI execution boundary

The direct `evo chat` and `evo code` commands are privileged local-only modes. They use the global TOML provider/configuration and a caller-selected local workspace path; they do not resolve a Platform Registry workspace, enforce Registry project/workspace scope, or load the API's scoped repository-instruction context. They are not equivalent to workspace-scoped API execution and must not be presented as such.

Both commands require the explicit `--i-understand-local-only` acknowledgement and print a warning before starting. Use the loopback desktop API for Registry-bound workspace operations. A future Registry-aware CLI mode may add an explicit workspace identifier and reuse the same runtime-binding and authorization boundary; it must not silently change the semantics of the existing local-only mode.
