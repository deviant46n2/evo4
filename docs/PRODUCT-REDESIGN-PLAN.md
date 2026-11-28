# Evo4 Product Redesign Plan

Status: **Authorized and scheduled.** The user has authorized implementation of the broader redesign. Per `ROADMAP.md`, it is the next product priority immediately after Phase 4 acceptance and before Phase 5 is considered user-facing complete. The current Phase 4 task-launch usability gap is being addressed as part of Phase 4 closure; the broader chat-first redesign follows as a dedicated milestone.

This document records the target product experience and UX requirements for Evo4. It is not a development roadmap; implementation order, dependencies, milestone scope, and acceptance gates are governed exclusively by `ROADMAP.md`.

## 1. Product vision and guiding principles

Evo4's immediate product is a local-first AI workbench and development system: a practical assistant and coding environment that makes the user's existing hardware more useful through local execution and resource-aware model/runtime management. Local operation must not depend on paid cloud services. The longer-term platform remains model/provider/agent/tool-agnostic and may support increasingly capable cooperative systems, but advanced cooperation is not the immediate UX or implementation priority. This document defines the user-facing experience; `ROADMAP.md` alone determines implementation sequence.

Guiding principles:

- Chat is the primary interaction surface for most user activity.
- Other application areas are visual representations or windows into backend capabilities, not separate applications or mandatory workflows.
- The backend platform remains authoritative for projects, configurations, workspaces, memory, experiments, local execution, and runtime/resource state.
- Natural-language intent routing should initially use deliberately engineered workflows. More automatic intent recognition can be introduced as reliability improves.
- Project scope, instructions, memory, filesystem access, and active task scope must never silently cross-contaminate.
- Reliability, isolation, security, and data integrity are gates, not aspirations.
- Functional reliability, safe local execution, hardware visibility, and usability take priority over visual effects.
- Proposed future behavior must be clearly distinguished from implemented behavior.

## 2. Target interaction model

- Evo opens directly into a chat interface.
- Chat follows a familiar multi-conversation model: multiple conversations, persistent history, new conversations, and reopening previous conversations.
- The sidebar remains relatively minimal.
- Coding and agent activity appear inline in chat as expandable activity items showing status and progress.
- Expansion must work reliably and show relevant agent activity, file changes, tool operations, test results, and task outcomes.
- Users can continue chatting while longer-running agent work proceeds in the background.
- New instructions and interruptions are handled through orchestration design rather than unnecessarily forcing the user to wait.
- Autonomy, interruption, queued decisions, and concurrency are configurable in AI/PAI configuration.
- Ordinary chat should eventually be sufficient to initiate coding and other tasks without requiring a special mode, but only as reliability permits.

## 3. Application information architecture

Primary areas:

- Chat: default landing area and primary interaction surface.
- Projects: independent project list and project lifecycle.
- Memory: persistent, searchable, inspectable, editable context.
- AI Configuration / Cyberdeck: visual configuration of components and relationships.
- Hardware/runtime, task execution, evidence, experiments, and supporting platform areas: exposed as needed, with visual representations of real backend capabilities.

Application areas should remain windows into backend capabilities rather than separate mandatory workflows.

## 4. Projects and workspace experience

- Provide a Projects area listing independent projects.
- Each project has an easily inspectable and editable local filesystem location.
- Default project creation creates a new dedicated folder, initializes Git with `git init`, and provisions a complete initial project framework.
- A project has its own instructions, memory, configuration, and supporting resources.
- Global instructions and project-specific instructions coexist, following a familiar OpenCode-like model.
- Projects remain independent by default rather than being blended into multi-project workspaces.
- A new project can explicitly consult other projects as prior art without merging identity, instructions, memory, or workspace boundaries.
- Project deletion removes project-owned files, Git history, and Evo-managed project resources, with verified cleanup and safeguards against deleting unrelated or shared resources.
- Existing Platform Registry architecture supports independently identifiable projects, configurations, checkouts, and workspaces. The user-facing default project workflow and underlying entity model must be reconciled rather than conflated.
- Automatic project selection and switching are reliability-gated. Until reliability criteria are met, use explicit project selection and/or separate project-specific conversations.
- Active work must not silently change project scope.

## 5. Agent activity and orchestration experience

- Coding and agent activity appear inline in chat.
- For a single-participant run, use a compact expandable activity item showing task status and progress.
- For cooperative tasks, provide an inspectable collaboration view showing participant identities and task-scoped roles, specialist handoffs, isolated parallel attempts, synthesis decisions, adversarial challenges, unresolved disagreements, adjudication, deterministic verification evidence, resource use, and final outcomes.
- Show which participant produced each artifact or claim, which evidence supports it, what was accepted/rejected/combined, and why. Do not flatten disagreement into a single untraceable assistant answer.
- Users can continue chatting while longer-running agent work proceeds.
- New instructions and interruptions are handled through orchestration design.
- Interruption behavior, queued decisions, autonomy, and concurrency are configurable in AI/PAI configuration.
- Distinguish actual supported runtime behavior from proposed future capabilities.

## 6. Memory experience

- Memory becomes a persistent context system that reduces the need for users to repeat information or remember old conversations.
- This is achieved through retrieval, context reconstruction, persistent records, and conversation history, not by eliminating model context-window limits.
- Memory automatically identifies potentially useful information from interactions, while preserving provenance, confidence, and appropriate review controls.
- Global memory and project-specific memory are clearly distinguished.
- Global instructions and preferences apply across projects; project instructions and memories are scoped to their projects.
- Memory is searchable, inspectable, editable, and understandable.
- Preserve provenance and relationships between records.
- Functional reliability and usability take priority over elaborate visual effects.
- Once the functional experience is established, the Memory area should receive substantial visual-design attention.
- A mechanical/spider-like visual metaphor was explored but is not a committed design decision.

## 7. AI configuration / Cyberdeck experience

- AI configuration has a node-based visual canvas inspired by the user's Cyberdeck concept.
- Nodes represent actual components such as agents, models, memory systems, and processes.
- Connections represent real relationships, communication, or dependencies.
- The visualization reflects actual backend configuration and runtime state; it is not a decorative diagram disconnected from the system.
- Users can understand the system at a glance and inspect individual components for detailed settings.
- Status indicators eventually distinguish relevant states such as active, idle, waiting, and error.
- Whether users construct or rearrange configurations directly through drag-and-drop remains undecided. Do not prematurely commit to that interaction.

## 8. Configurable behavior and preferences

- Visual embeds and generated visual components in chat are configurable.
- Potential settings include automatic presentation, presentation only when useful, or text unless explicitly requested.
- Do not impose one behavior on every user or every conversation.

## 9. Reliability, isolation, security, and data-integrity requirements

- Project instructions, memory, filesystem access, and active task scope must never silently cross-contaminate projects.
- Active work must not silently change project scope.
- Significant automated testing must demonstrate reliable isolation before automatic switching is enabled.
- Until that standard is met, use explicit project selection and/or separate project-specific conversations.
- Do not promise seamless automatic project switching before reliability criteria are satisfied.
- Project deletion must include verified cleanup and safeguards against deleting unrelated or shared resources.
- Retrieved context remains untrusted reference data, not instructions.
- Workspace and command boundaries remain governed by existing safety controls.

## Relationship to the authoritative development roadmap

The phase sequence in Sections 10–12 is retained as a historical product-planning reference describing how UX requirements were originally grouped. It is not an active implementation sequence and must not override `ROADMAP.md`. The unified roadmap is the only authority for development priorities, sequencing, dependencies, implementation milestones, phase status, and acceptance gates. Where this document's phase labels or dependencies conflict with the unified roadmap, `ROADMAP.md` takes precedence. The inventory below is a capability/gap reference, not authorization to implement any listed item.

The wholesale redesign is now explicitly scheduled by `ROADMAP.md` as the next product milestone after Phase 4 acceptance. It is not optional polish. Phase ordering and acceptance remain governed by `ROADMAP.md`.

## Existing Capability vs. Redesign Gap Inventory

This inventory is based on inspection of the current implementation, routes, components, services, persistence, and tests. It distinguishes existing capabilities from redesign gaps and identifies what should be reused.

### Phase 0 — Product redesign specification and architecture reconciliation

- Existing implementation: Product direction, platform identity, registry, and stabilization status are documented in `README.md`, `ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT-CONTINUITY.md`, `docs/PLATFORM-REGISTRY-V1-SPEC.md`, and this plan. The platform entity model is implemented through Registry v1 (M5) and exercised by `tests/test_workspaces_api.py`, `tests/test_project_checkouts_api.py`, and related tests.
- Status: Partially implemented.
- Redesign gap: Reconcile the chat-first UX direction with the existing platform architecture without conflating UI navigation with entity ownership.
- Backend gap: None expected; this is documentation and architecture reconciliation.
- Preservation and reuse: Preserve existing platform architecture and registry.
- Validation: Documentation consistency checks and existing test suite.

### Phase 1 — Chat-first interface and navigation

- Existing implementation: `desktop/src/App.tsx` already implements a chat-first layout with conversation list, search, create, open, rename, delete, streaming chat, and switching between workspaces. Conversation APIs exist at `/api/v1/conversations` and `/api/v1/conversations/{id}/messages` in `src/evo_core/api.py`.
- Status: Implemented.
- Redesign gap: Navigation and visual polish may need refinement, but the core chat/conversation capability exists.
- Backend gap: None identified beyond existing APIs.
- Preservation and reuse: Reuse conversation persistence and streaming chat implementation.
- Validation: Desktop build and existing API tests; no dedicated frontend tests exist.

### Phase 2 — Project lifecycle, provisioning, and isolation

- Existing implementation: Platform Registry v1 implements AI configurations (`src/evo_core/ai_configurations.py`), software projects and checkouts (`src/evo_core/project_checkouts.py`), workspaces (`src/evo_core/workspaces.py`), and registered-workspace execution boundaries (`src/evo_core/api.py`). Backend project/workspace scope now exists for conversations, messages, memories, candidates, lessons, research, tasks, plans, command policy, and assistant context assembly. Desktop workspaces exist in `desktop/src/ProjectsWorkspace.tsx`, `desktop/src/WorkspaceRegistryWorkspace.tsx`, and `desktop/src/Workspaces.tsx`.
- Status: Backend scope isolation substantially implemented; project UX integration and full acceptance verification remain.
- Redesign gap: Default project creation should create a dedicated folder, initialize Git, and provision an initial framework. Project deletion with verified cleanup is not yet implemented. Project-specific instruction/memory scoping needs UX integration and end-to-end verification.
- Backend gap: New backend functionality is required for provisioning deletion safeguards and complete project-scoped UX integration. Core project/workspace scope isolation is implemented in source.
- Preservation and reuse: Reuse existing project, checkout, configuration, and workspace entities and validation.
- Validation: `tests/test_project_checkouts_api.py`, `tests/test_workspaces_api.py`, `tests/test_workspace_execution_boundary.py`, `tests/test_scope_integrity.py`, `tests/test_retrieval_isolation.py`, `tests/test_milestone3_api_integration.py`.

### Phase 3 — Agent interaction, background execution, and interruption

- Existing implementation: `AgentsWorkspace` in `desktop/src/Workspaces.tsx` supports run history, detail, approval, cancellation, and plan management. Backend supports agent runs, plans, approval, execution, cancellation, background tasks, events, and worker revalidation in `src/evo_core/api.py` and `src/evo_core/background_agent.py`. Interruption and finalization behavior is covered by `tests/test_experiment_interruption.py` and agent tests.
- Status: Partially implemented.
- Existing execution infrastructure: run creation, claiming, cancellation, approval, background event history, and terminal finalization are implemented.
- Target orchestration not yet demonstrated: continuing ordinary chat while agent work runs, submitting new instructions against active work, safe interruption/redirect, queued decisions, configurable concurrency, autonomy, and interruption policy. These are backend orchestration requirements, not only UI integration.
- Redesign gap: Agent activity needs inline chat presentation with reliable expandable details. The current Agents workspace is a separate view rather than inline chat activity.
- Backend gap: New or extended backend functionality is required for conversation continuation during active work, instruction queuing/redirect, and configurable concurrency/autonomy. Existing execution and approval infrastructure should be reused.
- Preservation and reuse: Reuse agent run, plan, approval, cancellation, background-task, and event-history infrastructure.
- Validation: `tests/test_verification_approval.py`, `tests/test_coding_agent.py`, `tests/test_workspace_execution_boundary.py`. These tests establish execution and approval behavior, not the complete target orchestration experience.

### Phase 4 — Persistent memory and context experience

- Existing implementation: Memory workspace in `desktop/src/Workspaces.tsx` supports listing, search/recall preview, add, archive, supersede, candidate review, duplicate scan, and provenance display. Backend memory APIs and `_build_messages`/`_fit_context` exist in `src/evo_core/assistant.py`. Retrieved context is isolated as untrusted in a separate user-role message.
- Status: Partially implemented.
- Redesign gap: Memory UX needs stronger search, inspection, editing, and global/project distinction. The mechanical/spider visual metaphor is exploratory and not committed.
- Backend gap: Some extension may be needed for global/project scoping and metadata; core persistence and retrieval exist.
- Preservation and reuse: Reuse memory storage, retrieval, candidate review, and context-fitting logic.
- Validation: `tests/test_evo_core.py`, `tests/test_hardening_features.py`, including `RetrievedContextTrustBoundaryTests`.

### Phase 5 — AI configuration and Cyberdeck

- Existing implementation: Configuration workspace in `desktop/src/ConfigurationsWorkspace.tsx` and APIs in `src/evo_core/ai_configurations.py` support configuration creation, immutable revisions, archiving and reactivation of configuration records, and Registry association. Reactivation changes archived status only; it is not runtime activation or provider selection. Configuration-to-provider runtime binding and provider selection are not implemented. Workspace Registry links configurations to projects and checkouts. Configuration definitions use top-level `components` objects, but no explicit connection or dependency graph is defined in the inspected implementation.
- Status: Partially implemented.
- Redesign gap: Node-based visual canvas, component inspection, and status indicators are not implemented.
- Backend gap: Missing backend requirements include an explicit component graph or relationship model, runtime-state queryability for components, and status reporting. Existing configuration entities and revisions should be reused, but a generic component configuration is not already a complete executable or observable graph.
- Preservation and reuse: Reuse configuration and revision entities; extend rather than replace them.
- Validation: Configuration API tests and workspace tests; no test currently demonstrates a live component graph or runtime status.

### Phase 6 — Integration, visual polish, accessibility, usability, and reliability validation

- Existing implementation: Desktop build, backend APIs, tests, and stabilization work exist. No dedicated frontend test framework is present in `desktop/package.json`.
- Status: Partially implemented.
- Redesign gap: Integration polish, accessibility review, and dedicated frontend tests are needed.
- Backend gap: Mostly validation and UI work.
- Preservation and reuse: Existing build and validation commands.
- Validation: `npm run build`, Python test suite, compileall, `git diff --check`.


## 10–12. Historical planning note

The former product-only phase outline is retired to avoid a competing phase hierarchy. Its useful UX requirements remain in Sections 1–9 and 13–14. Implementation sequence, dependencies, and phase gates are defined exclusively in `ROADMAP.md`.

## 13. Explicitly open design decisions

- Whether users will construct or rearrange Cyberdeck configurations through drag-and-drop.
- Exact project provisioning framework and templates.
- Exact deletion verification and cleanup safeguards.
- Exact reliability thresholds and test suites required before automatic project switching.
- Exact handling of cross-project consultation and permissions.
- Exact memory capture, review, and confidence thresholds.
- Exact visual design of the Memory area.
- Exact visual embed configuration defaults and controls.
- Whether the mechanical/spider-like memory metaphor will be used.

## 14. Definition of target UX completion

The redesign is complete when the chat-first experience, project lifecycle, agent activity, memory experience, configuration visualization, and reliability requirements are implemented, integrated, tested, and independently accepted, while preserving Evo's platform identity and existing safety boundaries.

Project Provisioning v1 has been implemented on this branch under explicit user authorization. The user has now also authorized the broader redesign; implementation is scheduled according to `ROADMAP.md`.