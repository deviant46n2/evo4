# Evo Platform Registry v1 — Implementation Plan

**Status:** Planning baseline — not implementation authorization  
**Baseline:** `docs/PLATFORM-REGISTRY-V1-IMPLEMENTATION-DESIGN.md` at commit `be32d766b5fde3c0e8bc7662a43856859b378d9b`  
**Authority:** GPT-6 technical lead; Kilo/Beam local implementation and validation  
**Scope:** Persistent management of AI configurations, software projects, local checkouts, and workspaces.

This plan is an engineering sequence derived from the approved design. It does not itself authorize implementation.

## A. Scope and boundaries

### v1 outcome

Platform Registry v1 delivers:

- Persistent AI configurations with independent identities.
- Immutable AI configuration revisions with deterministic canonicalization, schema versioning, and SHA-256 content hashes.
- Independent software projects.
- Registered local project checkouts with canonical paths and availability states.
- Workspaces that connect a project to an exact AI configuration revision, optionally through a checkout.

### Preserved behavior

Implementation must preserve:

- Existing assistant behavior.
- Existing coding-agent behavior.
- Memory systems.
- Runtime configuration behavior.
- Workspace path containment, sensitive-file protection, command allowlist, and approval protections.
- Evo Lab behavior.

### Excluded scope

Platform Registry v1 does not include:

- Experiment registry.
- Artifact storage service.
- Full agent orchestration.
- Distributed execution scheduling.
- Resource allocation or quota management.
- Autonomous self-modification.
- Multi-user authentication or collaboration.
- Automatic project execution or dependency installation.
- Automatic runtime reconfiguration when registry definitions change.

The data model and interfaces must not prevent these future capabilities.

### Authorization boundary

This document is a plan only. Implementation requires explicit approval and must follow the engineering rules in section C.

## B. Dependency-ordered implementation milestones

### Milestone 1 — Persistence foundation and migration

**Deliverable:** Registry schema and migration integrated with the existing `EvoStore`, with persistence-level invariants and tests.

**Dependencies:** None beyond the approved design and existing `EvoStore`.

**Work:**

- Integrate with the existing `EvoStore` connection and `threading.RLock`.
- Add the registry schema through a separate explicit migration transaction.
- Do not create another database or connection.
- Do not place registry entities in `ResultsDB`.
- Use `BEGIN IMMEDIATE`, individual DDL statements, migration-record insertion, commit, and rollback.
- Preserve existing base-schema initialization and `ResultsDB` behavior.
- Validate composite foreign keys, immutable revision triggers, and checkout/workspace relationship constraints directly at the database level.

**Required tests/evidence:**

- Migration on a database containing existing application and Evo Lab data.
- Migration rollback on injected failure.
- Repeat initialization.
- Foreign-key enforcement enabled and verified.
- Current-revision invariant, including direct SQL insertion attempts that bypass the service layer.
- Composite foreign-key behavior for configuration/revision ownership and project/checkout ownership.
- Revision immutability through UPDATE and DELETE triggers.
- Checkout/workspace relationship constraints.
- Multiple workspaces sharing one checkout.

**Completion gate:** All persistence-level invariant tests pass, migration is idempotent, and existing `EvoStore`/`ResultsDB` behavior remains intact.

**Must remain unchanged:** Existing `EvoStore` base schema, `ResultsDB`, assistant, coding agent, memory, runtime, workspace security, and Evo Lab behavior.

### Milestone 2 — AI configuration lifecycle

**Deliverable:** AI configuration creation, immutable revision history, restoration, and lifecycle management.

**Dependencies:** Milestone 1.

**Work:**

- Create configurations with an initial immutable revision.
- Generate configuration and initial revision IDs before insertion.
- Use the deferred composite foreign key for configuration-first insertion.
- Implement strict JSON validation, schema-version handling, deterministic canonicalization, and SHA-256 content hashes.
- Implement revision history, new-revision updates, restoration by creating a new revision, optimistic concurrency, and archive/reactivation.
- Keep provider-specific extensions and secret references.

**Required tests/evidence:**

- Atomic configuration creation and rollback.
- Immutable revision behavior.
- Revision restoration by new revision.
- Content hash consistency.
- Invalid and unsupported definitions.
- Stale-version conflicts leaving no partial revision.
- Archive/reactivation using optimistic concurrency.

**Completion gate:** Configuration and revision invariants pass, including direct database-level checks.

**Must remain unchanged:** Existing runtime configuration behavior and model/provider integrations.

### Milestone 3 — Project and checkout lifecycle

**Deliverable:** Independent projects and registered local checkouts with canonical paths and availability states.

**Dependencies:** Milestone 1.

**Work:**

- Implement independent project identity and metadata.
- Support multiple checkouts per project.
- Validate canonical paths, enforce uniqueness, and manage availability states.
- Implement explicit availability refresh using the stored canonical path.
- Implement metadata-only unregister.
- Never delete filesystem contents or execute project code during registration.
- Apply the canonical path policy: resolve to target, reject broken symlinks and invalid paths, preserve `Workspace` protections.

**Required tests/evidence:**

- Project registration and metadata updates.
- Multiple checkouts for one project.
- Checkout/project relationship integrity.
- Canonical path uniqueness and missing paths.
- Symlink/canonical-path behavior.
- Duplicate canonical paths.
- Referenced-checkout restrictions.
- Unregister blocked when referenced.

**Completion gate:** Project and checkout invariants pass at the database and service levels.

**Must remain unchanged:** Existing workspace security boundaries, path containment, sensitive-file protections, command allowlist, and approval protections.

### Milestone 4 — Workspace lifecycle

**Deliverable:** Workspaces connecting projects to exact configuration revisions, optionally through checkouts.

**Dependencies:** Milestones 1, 2, and 3.

**Work:**

- Implement workspace creation and relationship validation.
- Pin exact configuration revisions; do not silently follow current revisions.
- Validate checkout ownership and availability.
- Support archive/reactivation with optimistic concurrency.
- Preserve existing workspace security boundaries.

**Required tests/evidence:**

- Workspace creation and relationship validation.
- Cross-configuration revision references.
- Cross-project checkout references.
- Archived entities.
- Unavailable checkouts.
- Shared checkouts.
- Optimistic concurrency conflicts.

**Completion gate:** Workspace invariants pass at the database and service levels.

**Must remain unchanged:** Existing workspace behavior and security boundaries.

### Milestone 5 — Backend API

**Deliverable:** Typed Pydantic request/response models and thin `/api/v1` route handlers.

**Dependencies:** Milestones 1 through 4.

**Work:**

- Add typed request and response models.
- Keep domain invariants in the registry service.
- Implement essential routes.
- Implement stable 404, 409, 422, and 500 behavior.
- Support archived-entity reactivation through existing PATCH endpoints.

**Required tests/evidence:**

- API validation.
- Response contracts.
- Error mapping.
- Existing API regressions.

**Completion gate:** API contract tests pass and existing API behavior remains intact.

**Must remain unchanged:** Existing API conventions and route behavior outside `/api/v1` registry endpoints.

### Milestone 6 — Desktop management interface

**Deliverable:** Platform management views in the existing desktop application.

**Dependencies:** Milestone 5.

**Work:**

- Add a Platform area without replacing existing navigation or capabilities.
- Support configuration creation, detail, and revision history.
- Support project registration, checkout inspection, and workspace management.
- Follow existing React/Vite conventions.
- Do not add dependencies without a demonstrated need and explicit review.

**Required tests/evidence:**

- Desktop production build when dependencies are available.
- Honest frontend validation approach; do not claim a frontend test framework exists if it does not.

**Completion gate:** Desktop build passes and existing navigation remains intact.

**Must remain unchanged:** Existing Chat, Agents, Memory, Hardware, and Experiments views.

### Milestone 7 — Integration and acceptance

**Deliverable:** Final validation and documentation reconciliation.

**Dependencies:** Milestones 1 through 6.

**Work:**

- Run the complete Python test suite.
- Run the Python compile check.
- Run the desktop production build when dependencies are available.
- Verify existing assistant, agent, memory, workspace, lifecycle, and Evo Lab behavior remains intact.
- Verify persistence across application restarts.
- Review the final diff.
- Update architecture and continuity documentation with implemented facts only.

**Required tests/evidence:**

- Complete test suite result.
- Compile check result.
- Desktop build result.
- Persistence restart verification.
- Final diff review.

**Completion gate:** All required validation passes and documentation reflects implemented facts.

**Must remain unchanged:** All existing behavior and security boundaries.

## C. Engineering rules

- GPT-6 is technical lead and final engineering reviewer.
- Kilo/Beam implement and validate locally.
- Use deterministic model-free tests. No real provider or model connection is a prerequisite.
- Keep changes small and reviewable. Do not combine all milestones into one implementation pass.
- Do not weaken tests or security boundaries.
- Do not use destructive Git operations, cleanup, resets, or changes to unrelated/untracked files.
- Do not restart services, deploy, or reconfigure runtime.
- Every code-changing pass must run relevant tests, compile checks, and rebuild affected runnable artifacts as required by `AGENTS.md`.
- Report unavailable validation honestly.

## D. First implementation milestone recommendation

Start with Milestone 1 only.

Schema correctness, migration atomicity, and persistence-level invariants are the foundation for all subsequent work. AI configurations, projects, checkouts, and workspaces all depend on the relational model and migration behavior being correct before service or API code is added.

Milestone 1 implementation is not authorized or started by this plan.

## E. Risks and decision gates

Known risks:

- SQLite deferred composite foreign-key behavior under transaction load.
- Migration compatibility with existing `EvoStore` data.
- Optimistic concurrency conflict semantics.
- Filesystem canonicalization and TOCTOU behavior.
- Desktop validation limitations due to the absence of an evident frontend test framework.

Resolved design decisions should not be reopened without new source evidence. Implementation-time verification is expected for SQLite behavior, migration behavior, security boundaries, and API contracts.

Non-blocking refinements may be finalized during implementation without reopening settled design decisions.
