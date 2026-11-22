# Evo4 Product Redesign Plan

Status: **Planning only.** No redesign implementation has been authorized. The stabilization freeze remains active.

This document records the accepted product direction for Evo4's primary user experience and a phased roadmap for reconciling that direction with the existing platform architecture.

## 1. Product vision and guiding principles

Evo's underlying identity remains the existing model-agnostic AI development and experimentation platform. The redesign changes the primary user experience and interaction model, not that identity.

Guiding principles:

- Chat is the primary interaction surface for most user activity.
- Other application areas are visual representations or windows into backend capabilities, not separate applications or mandatory workflows.
- The backend platform remains authoritative for projects, configurations, workspaces, memory, experiments, and execution.
- Natural-language intent routing should initially use deliberately engineered workflows. More automatic intent recognition can be introduced as reliability improves.
- Project scope, instructions, memory, filesystem access, and active task scope must never silently cross-contaminate.
- Reliability, isolation, security, and data integrity are gates, not aspirations.
- Functional reliability and usability take priority over visual effects.
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
- Experiments and supporting platform areas: exposed as needed, with visual representations of backend capabilities.

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
- Use an OpenCode-like expandable activity item showing task status and progress.
- Expanded details show relevant agent activity, file changes, tool operations, test results, and task outcomes.
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

## 10. Phased implementation roadmap

- Phase 0: Product redesign specification and architecture reconciliation.
- Phase 1: Chat-first interface and navigation foundation.
- Phase 2: Project lifecycle, provisioning, and isolation.
- Phase 3: Agent interaction, background execution, and interruption handling.
- Phase 4: Persistent memory and context experience.
- Phase 5: AI configuration and Cyberdeck visualization.
- Phase 6: Integration, visual polish, accessibility/usability, and reliability validation.

Refine dependencies where justified, but do not turn this into a detailed task breakdown for every future implementation.

## 11. Dependencies and sequencing rationale

- Phase 0 must reconcile the redesign with the existing platform architecture before implementation.
- Phase 1 establishes the primary chat surface that later phases build on.
- Phase 2 must establish project isolation before automatic project selection or cross-project consultation is enabled.
- Phase 3 depends on the chat-first surface and must preserve existing approval and execution-safety controls.
- Phase 4 depends on project scoping to avoid memory cross-contamination.
- Phase 5 depends on real backend configuration and runtime state.
- Phase 6 validates integrated behavior and cannot be replaced by visual polish alone.

## 12. Acceptance criteria for each phase

### Phase 0
- Redesign plan and architecture reconciliation are documented.
- Confirmed decisions, proposed approaches, and open questions are clearly separated.
- No implementation is implied by planning documents.

### Phase 1
- Evo opens into chat.
- Users can create, reopen, and switch conversations.
- Other application areas are reachable without becoming mandatory workflows.

### Phase 2
- Users can create, inspect, edit, and delete independent projects.
- Default project creation provisions a dedicated folder, Git repository, and initial framework.
- Global and project-specific instructions coexist without blending project identity.
- Project isolation has automated test coverage.

### Phase 3
- Agent activity appears inline in chat.
- Activity expansion works reliably and shows relevant details.
- Background work does not unnecessarily block chat.
- Existing approval and command authorization remain intact.

### Phase 4
- Memory is searchable, inspectable, editable, and understandable.
- Provenance and relationships are preserved.
- Global and project memory are clearly distinguished.

### Phase 5
- Cyberdeck visualization reflects actual backend configuration and runtime state.
- Component inspection works.
- Status indicators are meaningful rather than decorative.

### Phase 6
- Integrated flows pass reliability and usability validation.
- Accessibility and usability review is complete.
- No unresolved serious defects block the redesign.

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

## 14. Definition of redesign completion

The redesign is complete when the chat-first experience, project lifecycle, agent activity, memory experience, configuration visualization, and reliability requirements are implemented, integrated, tested, and independently accepted, while preserving Evo's platform identity and existing safety boundaries.

No redesign implementation is authorized by this plan alone. Implementation requires user authorization and completion of the active stabilization freeze.