# Evo — Platform Registry v1 Technical Specification

**Status:** Proposed engineering baseline — not yet implementation-approved  
**Version:** 0.1  
**Scope:** Persistent management of AI configurations, software projects, local checkouts, and workspaces.

## 1. Purpose

The Platform Registry establishes the persistent foundation for managing the systems Evo works with and the AI systems Evo can assemble.

It provides structured, versioned records for:

- Reusable AI system configurations.
- Independent software projects.
- Local checkouts of those projects.
- Workspaces that connect an AI configuration to an authorized project and checkout.

This is foundational platform infrastructure, not a replacement for the existing assistant, coding agent, memory system, or Evo Lab.

The design must support Evo's longer-term ambition as a portable, model-agnostic AI development and experimentation platform. It must work initially as a single-user, local-first installation while remaining extensible to remote execution, multiple machines, cloud providers, and agent swarms.

## 2. Design principles

1. **Independent identity:** AI configurations, software projects, and workspaces are separate domain entities.
2. **Explicit relationships:** Connections between entities must be represented and validated, not inferred from names or filesystem paths.
3. **Versioned definitions:** AI configurations must have persistent, independently addressable revisions.
4. **Reproducibility:** A workspace must be able to identify the exact configuration revision it uses.
5. **Persistence:** Registry state must survive application restarts and be queryable through stable interfaces.
6. **Portability:** Definitions and metadata should not depend on one machine's absolute paths or runtime state.
7. **Security:** Secrets, permissions, and execution boundaries must not be weakened by registry functionality.
8. **Incremental implementation:** Build a useful foundation without prematurely implementing the entire future platform.
9. **Backward compatibility:** Existing Evo capabilities must continue working.
10. **Model independence:** No specific model, provider, agent framework, or execution location may become a foundational dependency.

## 3. Domain model

The following entities must remain conceptually and structurally distinct.

### A. AI Configuration

A reusable definition of an AI system that Evo can instantiate or use.

It may describe:

- Model and provider selections.
- Agent roles and responsibilities.
- Memory architecture and namespaces.
- Retrieval and context-management settings.
- Tools and integrations.
- Orchestration and delegation policies.
- Execution preferences.
- Resource requirements and limits.
- Permissions and safety policies.
- Dependencies and compatibility requirements.

An AI configuration is not a software project. It must be independently created, versioned, branched, compared, restored, and promoted.

### B. AI Configuration Revision

An immutable snapshot of an AI configuration definition.

Each revision must have:

- A unique identity.
- Its parent configuration identity.
- A revision number or equivalent ordering.
- A validated definition payload.
- A content hash.
- Creation timestamp.
- Optional description/change summary.
- Optional provenance metadata.

Editing a configuration creates a new revision. Existing revisions must not be silently overwritten.

Restoring an older revision should create a new revision containing the restored definition, preserving history.

### C. Software Project

An independent development target.

A project may represent Evo itself or an unrelated software project.

It should contain stable identity and descriptive metadata, including:

- Project ID.
- Name and description.
- Optional Git remote.
- Default branch or reference.
- Project type/language metadata where useful.
- Creation and update timestamps.
- Optional archived status.

A project must not be owned by an AI configuration.

### D. Project Checkout

A local or otherwise registered working copy of a software project.

One project may have multiple checkouts, including separate working directories, branches, or isolated worktrees.

A checkout should record:

- Checkout ID.
- Parent project ID.
- Local path.
- Optional Git branch/reference.
- Optional last-known commit.
- Registration and update timestamps.
- Availability/status metadata.

A checkout is not the project itself. Its location is environment-specific and must not define project identity.

### E. Workspace

A persistent association between an AI configuration revision and a software project, optionally using a specific registered checkout.

A workspace should record:

- Workspace ID.
- Name and description.
- Project ID.
- Optional checkout ID.
- AI configuration ID.
- Exact AI configuration revision ID.
- Creation/update timestamps.
- Status.
- Optional workspace-specific metadata.

A workspace does not own the project or configuration.

The model must permit:

- One AI configuration to be used across multiple projects.
- Multiple AI configurations to work on the same project.
- Multiple workspaces to exist independently.
- Different workspaces to use different revisions of the same configuration.
- A workspace to exist without a registered checkout where appropriate.

Do not assume one configuration equals one project or one running agent.

## 4. Definition payload and validation

AI configuration definitions should use a structured, versioned JSON representation.

The format must support schema evolution. Include an explicit schema version so future versions can migrate or reject incompatible definitions safely.

Validation must distinguish:

- Structural validity.
- Required fields.
- Supported provider/model identifiers where applicable.
- Invalid or contradictory settings.
- Unsupported schema versions.
- Missing dependencies.
- Secret references and permissions.

Do not place API keys, passwords, tokens, or other credentials directly into exported configuration definitions or ordinary Git-tracked metadata.

Secret values must be managed separately through an appropriate secret-storage mechanism. Definitions may refer to named secret references.

Do not prematurely constrain the schema to currently installed providers or agents. Unknown provider-specific configuration should be representable without compromising validation of the common structure.

## 5. Lifecycle and invariants

### AI configurations

- Create.
- Read/list.
- Update by creating a new revision.
- Compare revisions.
- Restore by creating a new revision.
- Archive.
- Export/import, subject to the scope decision below.

Revision history must remain intact.

### Projects

- Register.
- Read/list.
- Update metadata.
- Archive.
- Associate with multiple checkouts.

### Checkouts

- Register.
- Read/list.
- Update registration metadata.
- Mark unavailable.
- Unregister without deleting the underlying project or filesystem contents.

Registration must not silently execute project code or alter the checkout.

### Workspaces

- Create.
- Read/list.
- Update permitted relationships and metadata.
- Archive.
- Resolve the exact configuration revision and project/checkout relationship.

Important invariants:

1. A workspace's configuration revision must belong to its stated configuration.
2. A workspace's checkout, when present, must belong to its stated project.
3. A configuration revision cannot be modified after creation.
4. Deleting or unregistering a checkout must not delete its project.
5. Archiving a project must not silently delete configurations or experiment history.
6. Invalid relationships must be rejected transactionally.
7. Registry operations must not silently change active runtime configuration.

## 6. Persistence and SQLite

Use the existing Evo persistence infrastructure where practical rather than introducing an unnecessary second database.

Inspect the actual `EvoStore`, `ResultsDB`, and existing database initialization/migration code before designing the migration.

The registry should use explicit tables for:

- `ai_configurations`
- `ai_configuration_revisions`
- `software_projects`
- `project_checkouts`
- `workspaces`

A minimal append-only `workspace_events` table is recommended if it can be introduced without expanding the initial implementation substantially. It could record relationship changes and important lifecycle events.

Use:

- Stable primary keys.
- Foreign-key constraints.
- Unique constraints.
- Appropriate indexes.
- Timestamps.
- Explicit schema migrations.
- Transactions for multi-step operations.

### Critical relational integrity requirements

- A configuration's `current_revision_id` must reference a revision belonging to that same configuration.
- A workspace's `(configuration_id, configuration_revision_id)` must reference a revision belonging to that configuration.
- A workspace's `(project_id, checkout_id)` must reference a checkout belonging to that project when a checkout is specified.

Do not rely exclusively on application-level checks for these relationships.

Resolve the SQLite composite foreign-key strategy before implementation. One possible approach is to expose unique composite keys on the referenced tables and use composite foreign keys, with an appropriate deferred constraint or transactional insertion strategy for the configuration/current-revision relationship.

The final migration SQL must be reviewed for actual SQLite behavior. Any illustrative SQL in this specification is not approved production migration code.

Use atomic transactions and appropriate concurrency control. Consider `BEGIN IMMEDIATE` for multi-step write operations where necessary.

## 7. Backend service architecture

Keep persistence operations separate from API routing.

Recommended conceptual separation:

- Domain models and validation.
- Registry persistence/repository layer.
- Registry service layer implementing lifecycle rules and invariants.
- API request/response schemas.
- API routes.
- Desktop client integration.

The service layer should be the authoritative enforcement point for domain rules. API handlers should not duplicate business logic.

Operations should return structured results and predictable errors.

Avoid coupling registry services directly to model inference, active agent processes, or the existing runtime configuration loader.

## 8. API design

Follow existing Evo API conventions and namespace the new endpoints under `/api/v1`.

Proposed endpoint families:

### AI configurations

- `GET /api/v1/configurations`
- `POST /api/v1/configurations`
- `GET /api/v1/configurations/{configuration_id}`
- `PATCH /api/v1/configurations/{configuration_id}`
- `GET /api/v1/configurations/{configuration_id}/revisions`
- `GET /api/v1/configurations/{configuration_id}/revisions/{revision_id}`
- `POST /api/v1/configurations/{configuration_id}/revisions`
- `POST /api/v1/configurations/{configuration_id}/restore/{revision_id}`

### Projects

- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/archive`

### Checkouts

- `GET /api/v1/projects/{project_id}/checkouts`
- `POST /api/v1/projects/{project_id}/checkouts`
- `PATCH /api/v1/projects/{project_id}/checkouts/{checkout_id}`
- `DELETE /api/v1/projects/{project_id}/checkouts/{checkout_id}`

### Workspaces

- `GET /api/v1/workspaces`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `PATCH /api/v1/workspaces/{workspace_id}`
- `POST /api/v1/workspaces/{workspace_id}/archive`

These are proposed route shapes, not a requirement to implement every endpoint in the first pass. Match existing naming, response, error, and dependency-injection conventions after inspecting the codebase.

Use typed request and response models. Define stable error responses for missing entities, invalid relationships, validation failures, conflicts, and unsupported schema versions.

Use optimistic concurrency where concurrent updates could otherwise overwrite newer metadata or relationships.

## 9. Export and import

Recommended capability: export an AI configuration definition and its revision history without secret values.

Import should:

- Validate the schema.
- Preserve provenance where possible.
- Create a new local configuration identity rather than silently overwriting an existing one.
- Record source identity and import metadata.
- Reject unsupported or unsafe content.

Whether this belongs in v1 implementation is an explicit scope decision. Do not let export/import delay the foundational registry if it materially expands the milestone.

## 10. Desktop application

Add a **Platform** area to the existing desktop navigation.

Initial management views should support:

- Listing and creating AI configurations.
- Inspecting configuration details and revision history.
- Listing and registering software projects.
- Viewing project checkouts.
- Creating and managing workspaces.
- Inspecting the configuration revision and project/checkout relationship associated with a workspace.

Keep the initial interface focused on management, not a full visual orchestration designer.

Use existing desktop architecture and styling conventions. Do not replace existing Chat, Agents, Memory, Hardware, or Experiments functionality.

## 11. Integration boundaries

The registry must be designed to integrate with existing Evo systems without conflating their current responsibilities.

In particular:

- Existing `EvoConfig` is runtime configuration and must not be casually renamed or treated as the new versioned AI configuration domain model.
- Existing filesystem `Workspace` security/access class must not be confused with the persistent platform Workspace entity.
- Existing assistant, coding agent, memory, provider integrations, and Evo Lab must continue operating.
- The registry should eventually provide configuration and workspace resolution to those systems through explicit adapters.
- Creating or editing a registry definition must not automatically reconfigure a running model or agent.

Do not replace or rename existing Evo Lab inference experiments as part of this milestone.

## 12. Experiment registry boundary

A broader persistent experiment registry is part of Evo's long-term architecture, but it is not the same thing as this Platform Registry milestone.

Future experiment records should capture:

- Hypothesis and objectives.
- Exact AI configuration revision.
- Exact project commit.
- Model/provider identity.
- Environment and dependencies.
- Methodology and test inputs.
- Resource usage.
- Results, measurements, and failures.
- Conclusions and decisions.
- Reproducibility and artifact references.

Preserve failed experiments and unexpected findings.

For this milestone, do not build a generic experiment framework merely because the platform will eventually need one. Keep the registry interfaces compatible with that future capability.

## 13. Security and filesystem safety

- Registry registration is not permission to execute project code.
- Project paths must be validated and canonicalized.
- Symlink behavior and path escape risks must be explicitly addressed.
- A checkout registration must not grant broader filesystem access than the existing security model allows.
- Never store secrets in ordinary configuration JSON, logs, or Git-tracked files.
- Enforce authorization at the service boundary as the platform evolves.
- Do not execute arbitrary hooks, scripts, or dependencies during registration.
- Preserve existing workspace access restrictions.

## 14. Error handling and operational behavior

Provide predictable, structured failures for:

- Missing entities.
- Duplicate identities or conflicting registrations.
- Invalid configuration definitions.
- Cross-entity relationship violations.
- Unsupported schema versions.
- Unavailable paths.
- Concurrent modification.
- Database and migration failures.

A failed multi-step operation must not leave partially updated relationships.

Archiving and unregistering must have clearly defined semantics and must not cause destructive side effects.

## 15. Testing strategy

Use deterministic tests. A real model or provider must not be required to validate registry functionality.

Tests should cover:

- Database creation and migration.
- Configuration creation and revision history.
- Immutable revision behavior.
- Revision restoration.
- Content hash consistency.
- Invalid configuration definitions.
- Project registration and metadata updates.
- Multiple checkouts for one project.
- Checkout/project relationship integrity.
- Workspace creation and relationship validation.
- Configuration revision ownership enforcement.
- Atomicity and rollback.
- Concurrent update/conflict behavior.
- Export/import and secret exclusion if included.
- API validation and error responses.
- Existing persistence and API regression tests.
- Desktop integration where applicable.

Test invalid cross-entity references at the database level, not only through service methods.

## 16. Performance and scale

The initial implementation is single-user and local-first, but the data model must not assume that all future execution happens on one machine.

Keep registry queries indexed and avoid loading full revision histories when listing configurations.

Avoid unnecessary database connections or duplicated persistence systems.

Large artifacts, logs, datasets, and benchmark results belong in appropriate artifact storage, not in registry rows or Git.

## 17. Implementation sequence

Recommended dependency-aware sequence:

1. Inspect and understand existing persistence, migration, API, and desktop architecture.
2. Finalize domain models and relational integrity constraints.
3. Implement schema migration and persistence tests.
4. Implement AI configuration creation, revisions, and history.
5. Implement project and checkout registration.
6. Implement workspace relationships and invariants.
7. Expose API endpoints and typed schemas.
8. Add desktop Platform management views.
9. Run regression and acceptance tests.
10. Update architecture and continuity documentation with the implemented state.

Do not start implementation until the unresolved schema and scope decisions below have been explicitly resolved.

## 18. Acceptance criteria

The v1 registry foundation is acceptable when:

- AI configurations have independent identities and immutable revision histories.
- Projects exist independently of configurations.
- Multiple checkouts can be registered for a project.
- Workspaces connect configurations to projects and optional checkouts.
- The exact configuration revision is preserved in each workspace.
- Cross-entity relationships are enforced at the persistence level.
- Invalid operations fail atomically.
- Data survives application restarts.
- API access follows existing Evo conventions.
- The desktop application can manage the core entities.
- Existing assistant, agent, memory, runtime, and Evo Lab behavior remains intact.
- No real model connection is required for registry tests.
- Tests demonstrate the required invariants and regression safety.

## 19. Explicitly deferred capabilities

Do not include these in the initial registry implementation unless separately approved:

- Full agent orchestration.
- Distributed execution scheduling.
- Resource allocation and quota management.
- Generic experiment registry.
- Artifact storage service.
- Autonomous self-modification.
- Multi-user authentication and collaboration.
- Full visual AI system designer.
- Automatic project execution or dependency installation.
- Automatic runtime reconfiguration when registry definitions change.

The data model and interfaces should not prevent these future capabilities.

## 20. Decisions requiring resolution before implementation

Record these as open design decisions rather than silently treating proposals as final:

1. **Composite foreign keys:** Exact SQLite implementation for same-configuration revision ownership and same-project checkout ownership.
2. **Workspace events:** Whether the minimal append-only event table belongs in v1.
3. **Export/import:** Whether secret-free configuration export and import are included in v1 or deferred.
4. **Definition schema:** Exact JSON schema, versioning, validation, and forward-compatibility behavior.
5. **Concurrency:** Exact optimistic concurrency token and conflict response semantics.
6. **Checkout safety:** Canonicalization, symlink handling, unavailable paths, and registration rules.
7. **API details:** Exact request/response contracts and route conventions after inspection of the current API.
8. **Persistence integration:** Exact relationship between existing `EvoStore` and `ResultsDB`, including transaction and migration behavior.

These decisions must be resolved using the actual source code, not assumptions.
