# Evo Platform Registry v1 — Implementation Design

**Status:** Proposed engineering baseline — not implementation-approved  
**Version:** 0.1  
**Authority:** GPT-6 technical design, derived from `docs/PLATFORM-REGISTRY-V1-SPEC.md` and the read-only source audit.  
**Scope:** Persistent management of AI configurations, software projects, local checkouts, and workspaces.

This document is a design only. It is not authorization to implement code.

## 1. Status, authority, and scope

This design implements the scope of `docs/PLATFORM-REGISTRY-V1-SPEC.md` and no more. It deliberately excludes full agent orchestration, distributed execution scheduling, resource allocation, generic experiment registry, artifact storage service, autonomous self-modification, multi-user authentication, full visual AI system designer, automatic project execution, and automatic runtime reconfiguration.

GPT-6 is the technical design authority. Any genuine contradiction between this document and the specification or inspected source must be recorded as an unresolved design issue rather than silently resolved.

The design preserves existing Evo assistant, coding agent, memory, provider, runtime, workspace, and Evo Lab behavior.

## 2. Source architecture findings and integration boundaries

Verified source facts:

- `EvoStore` and `ResultsDB` both use `config.database` (`src/evo_core/api.py:151-152`).
- They use separate SQLite connections (`src/evo_core/store.py:20`, `src/evo_experiments/db.py:18`).
- Both enable foreign keys and a 30-second busy timeout (`src/evo_core/store.py:25-26`, `src/evo_experiments/db.py:19-20`).
- `EvoStore` enables WAL and `synchronous=NORMAL` (`src/evo_core/store.py:27-28`); `ResultsDB` sets `synchronous=NORMAL` but does not itself execute `journal_mode=WAL` (`src/evo_experiments/db.py:21`).
- `create_app()` constructs stores and initializes profiles, scheduler, execution, background tasks, orchestration, recovery, and lifecycle reconciliation (`src/evo_core/api.py:149-176`).
- Routes use Pydantic `BaseModel` classes and are registered directly on FastAPI (`src/evo_core/api.py:69-144`).
- Blocking provider calls run in `ThreadPoolExecutor` (`src/evo_core/api.py:180-182`).
- Runtime configuration is a frozen `EvoConfig` dataclass loaded from TOML (`src/evo_core/config.py`).
- `Workspace` resolves paths, excludes sensitive files, protects test writes, and enforces configured command prefixes (`src/evo_core/workspace.py`).
- Desktop navigation uses views in `App.tsx` and workspace components in `Workspaces.tsx` (`desktop/src/App.tsx`, `desktop/src/Workspaces.tsx`).

Design decisions:

- Registry persistence belongs in the existing `EvoStore` SQLite database and uses its existing connection and `threading.RLock`.
- Do not create a third database or independent registry connection.
- Do not place registry entities in `ResultsDB`.
- Do not make registry operations depend on inference, assistant turns, agent workers, or Evo Lab.
- Implement persistence/repository and service functionality in a dedicated module, preferably `src/evo_core/platform_registry.py`.
- The registry service receives the existing `EvoStore` instance and uses its connection and lock. It must not open the database independently.
- Initialize the registry in `create_app()` after `EvoStore` exists, using the same pattern as existing `initialize_*` calls.
- Preserve existing `EvoStore`, `ResultsDB`, assistant, and Evo Lab behavior.
- The registry uses `EvoStore` only and does not operate across `EvoStore` and `ResultsDB`; no cross-database transaction semantics are introduced in v1.

## 3. Final domain model

The fundamental entities remain distinct:

- Evo: platform.
- AI configuration: reusable AI system definition.
- AI configuration revision: immutable snapshot.
- Software project: independent development target.
- Project checkout: registered local working copy.
- Workspace: persistent association between a configuration revision and a project/optional checkout.

Invariants:

1. A workspace's configuration revision must belong to its stated configuration.
2. A workspace's checkout, when present, must belong to its stated project.
3. A configuration revision cannot be modified after creation.
4. Deleting or unregistering a checkout must not delete its project or filesystem contents.
5. Archiving a project must not silently delete configurations or experiment history.
6. Invalid relationships must be rejected transactionally.
7. Registry operations must not silently change active runtime configuration.

One AI configuration may be used across multiple projects. Multiple configurations may work on the same project. Multiple workspaces may exist independently. Different workspaces may use different revisions of the same configuration. A workspace may exist without a registered checkout where appropriate. Multiple workspaces may share a registered checkout.

## 4. Exact SQLite schema

The following SQL is design SQL pending implementation review. It is intended to be internally consistent and syntactically plausible SQLite. The final migration must be reviewed against actual SQLite behavior. Foreign-key clause ordering below has been validated against SQLite: `ON DELETE`/`ON UPDATE` precede `DEFERRABLE`.

```sql
CREATE TABLE IF NOT EXISTS ai_configurations (
    configuration_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    current_revision_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (configuration_id, current_revision_id),
    FOREIGN KEY (configuration_id, current_revision_id)
        REFERENCES ai_configuration_revisions (configuration_id, revision_id)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS ai_configuration_revisions (
    revision_id TEXT PRIMARY KEY,
    configuration_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parent_revision_id TEXT,
    change_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (configuration_id, revision_id),
    UNIQUE (configuration_id, revision_number),
    FOREIGN KEY (configuration_id)
        REFERENCES ai_configurations (configuration_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (configuration_id, parent_revision_id)
        REFERENCES ai_configuration_revisions (configuration_id, revision_id)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TRIGGER IF NOT EXISTS ai_configuration_revisions_no_update
BEFORE UPDATE ON ai_configuration_revisions
BEGIN
    SELECT RAISE(ABORT, 'AI configuration revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ai_configuration_revisions_no_delete
BEFORE DELETE ON ai_configuration_revisions
BEGIN
    SELECT RAISE(ABORT, 'AI configuration revisions cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS software_projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    git_remote TEXT,
    default_ref TEXT,
    project_type TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS project_checkouts (
    checkout_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    canonical_path TEXT NOT NULL,
    branch_or_ref TEXT,
    last_known_commit TEXT,
    availability_status TEXT NOT NULL CHECK (availability_status IN ('available', 'missing', 'unavailable')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (project_id, checkout_id),
    UNIQUE (canonical_path),
    FOREIGN KEY (project_id)
        REFERENCES software_projects (project_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    checkout_id TEXT,
    configuration_id TEXT NOT NULL,
    configuration_revision_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (project_id)
        REFERENCES software_projects (project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (project_id, checkout_id)
        REFERENCES project_checkouts (project_id, checkout_id)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY IMMEDIATE,
    FOREIGN KEY (configuration_id)
        REFERENCES ai_configurations (configuration_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (configuration_id, configuration_revision_id)
        REFERENCES ai_configuration_revisions (configuration_id, revision_id)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY IMMEDIATE
);

CREATE INDEX IF NOT EXISTS idx_ai_configurations_status ON ai_configurations(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_ai_configuration_revisions_configuration ON ai_configuration_revisions(configuration_id, revision_number);
CREATE INDEX IF NOT EXISTS idx_software_projects_status ON software_projects(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_project_checkouts_project ON project_checkouts(project_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_workspaces_project ON workspaces(project_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_workspaces_configuration ON workspaces(configuration_id, configuration_revision_id);
```

Notes:

- `ai_configurations.current_revision_id` is `NOT NULL`. The deferred composite foreign key allows the configuration row to be inserted first with a predetermined revision ID, then the initial revision row, in one transaction; the constraint is checked at commit. The reverse order is not permitted because the revision-to-configuration foreign key is immediate.
- `workspaces.checkout_id` is nullable; a workspace may exist without a registered checkout.
- Multiple workspaces may share a checkout. The redundant `UNIQUE (project_id, checkout_id)` constraint is not present on `workspaces`; the composite foreign key enforcing checkout ownership is retained.
- Composite foreign keys require the referenced composite columns to be unique. The schema above provides those unique constraints.
- `ON DELETE RESTRICT` preserves history and prevents accidental destruction.
- Archiving is the normal lifecycle operation for configurations, projects, and workspaces. No general destructive deletion is provided.

### SQLite validation evidence

The exact complete proposed DDL above was executed in an isolated in-memory SQLite database (`:memory:`) with `PRAGMA foreign_keys=ON`. No Evo database or file was touched.

Full-DDL tests performed:

- PRAGMA verification: `PRAGMA foreign_keys=ON` was executed; `PRAGMA foreign_keys` subsequently returned `1`.
- Schema creation: the complete DDL, including all tables, composite foreign keys, indexes, and triggers, executed successfully via `executescript()` on a fresh database. Result: success, no syntax errors.
- Insertion order: inserting the initial revision before its configuration failed with `FOREIGN KEY constraint failed`; only the configuration-first order is valid.
- Repeated creation was not separately exercised; the DDL uses `CREATE TABLE IF NOT EXISTS` and `CREATE TRIGGER IF NOT EXISTS`, so repeated initialization is structurally supported.
- Configuration creation with predetermined IDs: `BEGIN IMMEDIATE`, insert `ai_configurations` with `current_revision_id` set to a predetermined revision ID, insert the initial `ai_configuration_revisions` row, commit. Result: success; both rows present.
- Deferred FK invariant: inserting `ai_configurations` referencing a non-existent revision and committing without inserting the revision failed with `FOREIGN KEY constraint failed`.
- Cross-configuration revision reference: inserting a workspace whose `configuration_id`/`configuration_revision_id` pair does not match an existing revision failed with `FOREIGN KEY constraint failed`.
- Revision immutability: `UPDATE` on `ai_configuration_revisions` was rejected by `ai_configuration_revisions_no_update` with `AI configuration revisions are immutable`.
- Revision deletion: `DELETE` on `ai_configuration_revisions` was rejected by `ai_configuration_revisions_no_delete` with `AI configuration revisions cannot be deleted`.
- Checkout ownership: inserting a workspace referencing a non-existent `(project_id, checkout_id)` pair failed with `FOREIGN KEY constraint failed`.
- Shared checkout: two workspaces referencing the same checkout were inserted successfully.
- Restrictive deletion: deleting a referenced `software_projects` row failed with `FOREIGN KEY constraint failed`.

All tests above used the exact full DDL. No partial-DDL-only claims are made.

## 5. Migration and transaction design

Registry migration integration (accurate to `src/evo_core/store.py`):

- `EvoStore._initialize()` creates the base schema with `executescript()`, including `schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)`.
- Existing migrations are identified through the `name` column, not a general-purpose migration framework. The current implementation uses a hardcoded migration name (`supersedes_direction_current_to_old_v1`) checked with `SELECT 1 FROM schema_migrations WHERE name=?` and recorded with `INSERT INTO schema_migrations(name, applied_at) VALUES(?, ?)`.
- The registry does not introduce a parallel migration table or an independent database connection. It adds one identifiable migration row (e.g. `platform_registry_v1`) to the existing `schema_migrations` table.
- Registry initialization is a separate operation that runs after `EvoStore` exists, using the existing `EvoStore` connection and `threading.RLock`, following the same pattern as existing `initialize_*` calls in `create_app()`.
- The registry migration uses explicit transaction handling: `BEGIN IMMEDIATE`, individual DDL statements, migration-record insertion, commit on success, rollback on any failure. It must not use `executescript()` inside the transaction.
- Base-schema initialization and `ResultsDB` migration behavior are not changed.
- If the registry migration fails, startup must not register or expose registry routes/services; the application fails closed rather than continuing with a partially initialized registry.

Configuration creation transaction:

1. Generate `configuration_id` and the initial `revision_id` before any insertion.
2. `BEGIN IMMEDIATE`.
3. Insert `ai_configurations` with `current_revision_id` set to the predetermined initial revision ID.
4. Insert the initial `ai_configuration_revisions` row in the same transaction.
5. Commit. The deferred composite foreign key permits the configuration-first insertion order described above; both rows must exist at commit. The reverse order is not permitted because `ai_configuration_revisions.configuration_id` references `ai_configurations` through an immediate foreign key.
6. On any failure, roll back; no configuration or revision is committed.

Revision creation transaction:

1. Read and validate the parent configuration and current state.
2. Require the expected configuration version.
3. `BEGIN IMMEDIATE`.
4. Insert the new immutable revision.
5. Update `ai_configurations.current_revision_id` and `updated_at` if the operation is a normal edit.
6. Commit. Revision insertion and current-pointer update occur atomically.
7. A stale version returns a conflict and leaves no partial revision behind.

Workspace creation transaction:

1. Validate configuration exists.
2. Validate the requested revision belongs to that configuration.
3. Validate project exists.
4. If checkout is provided, validate that it belongs to the project and is available.
5. Insert the workspace.
6. Commit.

All multi-row operations must use transactions. Use `BEGIN IMMEDIATE` where concurrent writes are possible.

Current-revision invariant:

- `ai_configurations.current_revision_id` is `NOT NULL`.
- A configuration's initial revision ID is predetermined, so the configuration row can reference it directly.
- The deferred composite foreign key permits the configuration-first two-row insert order within one transaction; the reverse order is not permitted.
- A configuration cannot be committed without a valid current revision, including when someone bypasses the service layer and attempts direct SQL insertion. An insert of `ai_configurations` referencing a non-existent revision fails the foreign-key constraint at commit.
- The composite foreign key prevents a current revision from belonging to a different configuration.
- Revision creation that updates the current pointer must validate the expected configuration version and perform both inserts/updates atomically. A stale version leaves no partial revision behind.

Archived entities:

- Archiving is reversible in v1 unless a later design explicitly makes it terminal.
- An archived configuration, project, or workspace may be reactivated by changing status from `archived` to `active` using the same optimistic-concurrency rules (for example, via PATCH with `status: active` and a required `expected_version`).
- Archiving must not delete revisions, history, checkouts, or experiment references.
- An archived project's checkouts remain registered. While the project is archived, they are unavailable for new workspace creation. Reactivating the project does not automatically change any checkout's `availability_status`; checkout availability remains independently controlled by its existing state and system checks. No separate checkout reactivation endpoint or capability is provided in v1.
- Unregistering a checkout is distinct from archiving a project and must not delete filesystem contents.

Unavailable checkouts:

- Creating or reassigning a workspace to a checkout whose availability status is not `available` must fail.
- If a registered checkout later becomes `missing` or `unavailable`, existing workspaces remain valid records and retain their pinned configuration revision.
- Those workspaces must not be silently reassigned to another checkout.
- Any operation requiring the checkout must report its unavailable status.

## 6. Definition JSON, canonicalization, and revision integrity

- Definition schema version: `1`.
- Definition must be a JSON object.
- Strictly validate JSON; reject NaN, infinity, malformed JSON, and non-object payloads.
- Canonical serialization must be deterministic: UTF-8, sorted object keys, compact separators, stable Unicode handling, no non-finite numbers.
- Compute SHA-256 over canonical serialized definition bytes.
- Store canonical JSON and hash.
- Preserve unknown provider-specific extension fields rather than rejecting all fields not understood by Evo.
- Minimum common structure for schema version 1:
  - `schema_version`: integer, required, currently `1`.
  - `name`: string, required, non-empty after trimming.
  - `description`: string, optional, default empty.
  - `provider`: object or null, optional.
  - `model`: object or null, optional.
  - `agents`: array of role definitions, optional, default empty.
  - `memory`: object, optional.
  - `retrieval`: object, optional.
  - `tools`: array, optional, default empty.
  - `orchestration`: object, optional.
  - `execution`: object, optional.
  - `resources`: object, optional.
  - `permissions`: object, optional.
  - `dependencies`: array, optional, default empty.
  - `extensions`: object, optional, default empty.
- Provider-specific fields may appear inside `extensions` or other nested objects and must be preserved.
- Common fields must be validated structurally; provider-specific values must not be rejected merely because Evo does not recognize them.
- Secrets must be represented only as named references, never as literal values.
- Validate common structural requirements without hardcoding currently installed models or providers.
- Secrets must never be embedded as values. Definitions may contain named secret references only.
- Reject unsupported schema versions clearly.
- Do not build a general schema migration framework in v1.
- Revisions are immutable after insertion. Enforce this at the persistence/database boundary, not merely by convention.
- Restoring an older revision creates a new revision containing the restored definition, preserving history.
- No hard-delete API is provided for configurations, revisions, projects, checkouts, or workspaces. Archiving is the normal lifecycle operation.

Configuration JSON authority:

- `schema_version` has one authoritative source: the `schema_version` field inside the definition JSON. Request models do not accept a separate `schema_version` parameter. If a caller supplies one, it is not used; the definition's value governs.
- The definition's `name` is authoritative for a configuration's display name. `ai_configurations.name` is a synchronized cache of the current revision's definition name and is updated transactionally when the current revision changes. The service layer must reject or reconcile any mismatch rather than silently storing conflicting values.
- `ai_configurations.description` is likewise synchronized from the current revision's definition description.
- Provider-specific extensions and secret references are preserved as specified above.

## 7. Service/repository contracts

Define a dedicated registry service module, preferably `src/evo_core/platform_registry.py`. It receives the existing `EvoStore` instance and uses its connection and lock. It must not open the database independently.

AI configurations:

- `create_configuration(definition, change_summary="") -> ConfigurationRevisionResult`
- `get_configuration(configuration_id) -> ConfigurationRecord`
- `list_configurations(status=None) -> list[ConfigurationRecord]`
- `update_configuration(configuration_id, updates, expected_version) -> ConfigurationRecord`
- `create_revision(configuration_id, definition, *, parent_revision_id=None, change_summary="", expected_version) -> ConfigurationRevisionResult`
- `get_revision(configuration_id, revision_id) -> RevisionRecord`
- `list_revisions(configuration_id) -> list[RevisionRecord]`
- `restore_revision(configuration_id, revision_id, *, change_summary="", expected_version) -> ConfigurationRevisionResult`
- `archive_configuration(configuration_id, expected_version) -> ConfigurationRecord`

Projects:

- `create_project(name, description="", git_remote=None, default_ref=None, project_type=None) -> ProjectRecord`
- `get_project(project_id) -> ProjectRecord`
- `list_projects(status=None) -> list[ProjectRecord]`
- `update_project(project_id, updates, expected_version) -> ProjectRecord`
- `archive_project(project_id, expected_version) -> ProjectRecord`

Checkouts:

- `register_checkout(project_id, canonical_path, branch_or_ref=None, last_known_commit=None) -> CheckoutRecord`
- `get_checkout(project_id, checkout_id) -> CheckoutRecord`
- `list_checkouts(project_id) -> list[CheckoutRecord]`
- `update_checkout(project_id, checkout_id, updates, expected_version) -> CheckoutRecord`
- `mark_checkout_unavailable(project_id, checkout_id, expected_version) -> CheckoutRecord`
- `refresh_checkout_availability(project_id, checkout_id, expected_version) -> CheckoutRecord`
- `unregister_checkout(project_id, checkout_id, expected_version) -> None`

Workspaces:

- `create_workspace(name, description, project_id, configuration_id, configuration_revision_id, checkout_id=None) -> WorkspaceRecord`
- `get_workspace(workspace_id) -> WorkspaceRecord`
- `list_workspaces(status=None) -> list[WorkspaceRecord]`
- `update_workspace(workspace_id, updates, expected_version) -> WorkspaceRecord`
- `archive_workspace(workspace_id, expected_version) -> WorkspaceRecord`
- `resolve_workspace(workspace_id) -> ResolvedWorkspace`

Transaction boundaries:

- Each public mutating operation owns its transaction.
- Multi-row operations must commit only after all invariants are validated.
- Read operations should not mutate state.
- Registry operations must not change active runtime configuration.

## 8. Lifecycle and concurrency semantics

- Mutable records use integer optimistic concurrency versions.
- Updates require an expected version and use compare-and-swap semantics (`WHERE id=? AND version=?`).
- Version increments atomically.
- Stale versions return a conflict, not silent last-write-wins behavior.
- AI configurations, projects, checkouts, and workspaces support active/archived lifecycle states where applicable.
- Archiving is the normal lifecycle operation and is reversible via the same optimistic-concurrency rules.
- No hard-delete API is provided for core registry entities.
- Revisions are immutable.
- A workspace pins an exact configuration revision and must not silently follow a configuration's current revision.
- Registry operations must not silently change active runtime configuration.

Error mapping:

- Missing entity: HTTP 404.
- Validation failure or invalid relationship: HTTP 422.
- Conflict or stale version: HTTP 409.
- Persistence/database failure: HTTP 500 or a stable internal error response.
- Unsupported schema version: HTTP 422.

Database constraints remain authoritative even if service-level checks are also performed.

Optimistic concurrency:

- Every mutation of an existing mutable record requires an expected version.
- Creating a new independent record does not require an expected version.
- `create_revision()` requires the expected configuration version.
- `restore_revision()` requires the expected configuration version.
- Revision insertion and current-revision pointer update must occur in one transaction.
- A stale version returns a conflict and leaves no partial revision behind.
- Creating a revision that does not update the current pointer still requires the expected configuration version if it modifies configuration metadata or revision history in a way that races with other writers.

## 9. Checkout filesystem security

Registration is not permission to execute project code.

For v1:

- Require the path to be an existing directory.
- Expand the user path and canonicalize with filesystem resolution.
- Store the canonical path, not an unresolved relative path.
- Reject invalid or non-directory paths.
- Check canonical-path uniqueness.
- Registration must not execute arbitrary hooks, scripts, dependencies, or commands.
- Registration must not grant broader filesystem access than the existing security model allows.
- A registered checkout may only be accessed through the existing `Workspace` security boundary.
- Preserve existing path traversal, symlink, sensitive-file, command allowlist, and approval protections.
- Never store secrets in checkout metadata.
- If a registered directory later disappears, mark it unavailable without deleting the record.
- Unregistering removes registry metadata only and must not touch filesystem contents.
- A workspace referencing a checkout must prevent its deletion through the foreign key; return a conflict with a useful explanation.
- Missing directories are detected by explicit availability checks that test whether the canonical path exists and is an accessible directory. If the path does not exist, `availability_status` becomes `missing`; if it exists but is not an accessible directory or cannot be validated, it becomes `unavailable`.
- Availability checks are explicit operations; ordinary registry reads do not perform filesystem checks.
- A checkout transitions back to `available` only through an explicit availability refresh after the path again exists and is an accessible directory. That refresh requires `expected_version`.
- Filesystem operations are limited to path validation during registration and explicit availability checks. Registry lifecycle operations do not otherwise access the filesystem.
- Unregistering a checkout never deletes filesystem contents.

Canonicalization reduces but does not eliminate symlink or TOCTOU risks. Residual filesystem race considerations must be documented and tested.

## 10. API routes and Pydantic contracts

Follow existing Evo API conventions and namespace new endpoints under `/api/v1`.

Use typed Pydantic request and response models. Define stable error responses for missing entities, invalid relationships, validation failures, conflicts, and unsupported schema versions.

API handlers should be thin; the service layer owns lifecycle and invariants.

A minimal consistent route set is preferred over implementing every speculative route. The endpoint families listed in `docs/PLATFORM-REGISTRY-V1-SPEC.md` are proposed shapes, not a requirement to implement every endpoint in the first pass.

Do not silently change active runtime configuration when a registry definition changes.

Archived-entity reactivation uses the existing PATCH endpoints with `status: active` and a required `expected_version`; no separate reactivation route is required.

### Essential v1 route matrix

| Method | Path | Request | Response | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/configurations` | query: `status` optional | `ConfigurationListResponse` | 200 | 400, 500 |
| POST | `/api/v1/configurations` | `ConfigurationCreateRequest`: `definition`, `change_summary` | `ConfigurationRevisionResult` | 201 | 400, 422, 500 |
| GET | `/api/v1/configurations/{configuration_id}` | path ID | `ConfigurationRecord` | 200 | 404, 500 |
| GET | `/api/v1/configurations/{configuration_id}/revisions` | path ID | `RevisionListResponse` | 200 | 404, 500 |
| GET | `/api/v1/configurations/{configuration_id}/revisions/{revision_id}` | path IDs | `RevisionRecord` | 200 | 404, 500 |
| POST | `/api/v1/configurations/{configuration_id}/revisions` | `RevisionCreateRequest`: `definition`, `parent_revision_id`, `change_summary`, `expected_version` | `ConfigurationRevisionResult` | 201 | 404, 409, 422, 500 |
| POST | `/api/v1/configurations/{configuration_id}/restore/{revision_id}` | path IDs, `RestoreRevisionRequest`: `change_summary`, `expected_version` | `ConfigurationRevisionResult` | 201 | 404, 409, 422, 500 |
| PATCH | `/api/v1/configurations/{configuration_id}` | `ConfigurationUpdateRequest`: permitted metadata fields and `expected_version` | `ConfigurationRecord` | 200 | 404, 409, 422, 500 |
| POST | `/api/v1/configurations/{configuration_id}/archive` | `ArchiveRequest`: `expected_version` | `ConfigurationRecord` | 200 | 404, 409, 422, 500 |
| GET | `/api/v1/projects` | query: `status` optional | `ProjectListResponse` | 200 | 400, 500 |
| POST | `/api/v1/projects` | `ProjectCreateRequest`: `name`, `description`, `git_remote`, `default_ref`, `project_type` | `ProjectRecord` | 201 | 422, 500 |
| GET | `/api/v1/projects/{project_id}` | path ID | `ProjectRecord` | 200 | 404, 500 |
| PATCH | `/api/v1/projects/{project_id}` | `ProjectUpdateRequest`: metadata fields and `expected_version` | `ProjectRecord` | 200 | 404, 409, 422, 500 |
| POST | `/api/v1/projects/{project_id}/archive` | `ArchiveRequest`: `expected_version` | `ProjectRecord` | 200 | 404, 409, 422, 500 |
| GET | `/api/v1/projects/{project_id}/checkouts` | path ID | `CheckoutListResponse` | 200 | 404, 500 |
| POST | `/api/v1/projects/{project_id}/checkouts` | `CheckoutRegisterRequest`: `canonical_path`, `branch_or_ref`, `last_known_commit` | `CheckoutRecord` | 201 | 404, 409, 422, 500 |
| PATCH | `/api/v1/projects/{project_id}/checkouts/{checkout_id}` | `CheckoutUpdateRequest`: metadata fields and `expected_version` | `CheckoutRecord` | 200 | 404, 409, 422, 500 |
| POST | `/api/v1/projects/{project_id}/checkouts/{checkout_id}/unavailable` | `AvailabilityUpdateRequest`: `expected_version` | `CheckoutRecord` | 200 | 404, 409, 422, 500 |
| POST | `/api/v1/projects/{project_id}/checkouts/{checkout_id}/availability` | `AvailabilityRefreshRequest`: `expected_version` | `CheckoutRecord` | 200 | 404, 409, 422, 500 |
| DELETE | `/api/v1/projects/{project_id}/checkouts/{checkout_id}` | query: `expected_version` | 204 | 204 | 404, 409, 422, 500 |
| GET | `/api/v1/workspaces` | query: `status` optional | `WorkspaceListResponse` | 200 | 400, 500 |
| POST | `/api/v1/workspaces` | `WorkspaceCreateRequest`: `name`, `description`, `project_id`, `configuration_id`, `configuration_revision_id`, `checkout_id` | `WorkspaceRecord` | 201 | 404, 409, 422, 500 |
| GET | `/api/v1/workspaces/{workspace_id}` | path ID | `WorkspaceRecord` | 200 | 404, 500 |
| PATCH | `/api/v1/workspaces/{workspace_id}` | `WorkspaceUpdateRequest`: permitted fields and `expected_version` | `WorkspaceRecord` | 200 | 404, 409, 422, 500 |
| POST | `/api/v1/workspaces/{workspace_id}/archive` | `ArchiveRequest`: `expected_version` | `WorkspaceRecord` | 200 | 404, 409, 422, 500 |
| GET | `/api/v1/workspaces/{workspace_id}/resolve` | path ID | `ResolvedWorkspace` | 200 | 404, 500 |

### Response model fields

The following defines the concrete fields returned by the essential endpoints above. Field types are JSON-serializable scalars/objects; timestamps are ISO 8601 UTC strings.

- `ConfigurationRecord`: `configuration_id`, `name`, `description`, `status`, `current_revision_id`, `created_at`, `updated_at`, `version`.
- `ConfigurationListResponse`: `items: list[ConfigurationRecord]`, `total: integer`.
- `ConfigurationRevisionResult`: `configuration: ConfigurationRecord`, `revision: RevisionRecord`.
- `RevisionRecord`: `revision_id`, `configuration_id`, `revision_number`, `schema_version`, `definition` (object), `content_hash`, `parent_revision_id` (string or null), `change_summary`, `created_at`, `provenance` (object).
- `RevisionListResponse`: `items: list[RevisionRecord]`, `total: integer`.
- `ProjectRecord`: `project_id`, `name`, `description`, `git_remote` (string or null), `default_ref` (string or null), `project_type` (string or null), `status`, `created_at`, `updated_at`, `version`.
- `ProjectListResponse`: `items: list[ProjectRecord]`, `total: integer`.
- `CheckoutRecord`: `checkout_id`, `project_id`, `canonical_path`, `branch_or_ref` (string or null), `last_known_commit` (string or null), `availability_status`, `created_at`, `updated_at`, `version`.
- `CheckoutListResponse`: `items: list[CheckoutRecord]`, `total: integer`.
- `WorkspaceRecord`: `workspace_id`, `name`, `description`, `project_id`, `checkout_id` (string or null), `configuration_id`, `configuration_revision_id`, `status`, `created_at`, `updated_at`, `version`.
- `WorkspaceListResponse`: `items: list[WorkspaceRecord]`, `total: integer`.
- `ResolvedWorkspace`: `workspace: WorkspaceRecord`, `configuration: ConfigurationRecord`, `revision: RevisionRecord`, `project: ProjectRecord`, `checkout: CheckoutRecord | null`.
- `ArchiveRequest`: `expected_version: integer`.
- `AvailabilityUpdateRequest`: `expected_version: integer`.
- `AvailabilityRefreshRequest`: `expected_version: integer`.
- `ConfigurationCreateRequest`: `definition: object`, `change_summary: string` (default empty).
- `ConfigurationUpdateRequest`: `status: "active" | "archived"` (optional), `expected_version: integer` (required). Name and description are derived from revisions and are not directly mutable here.
- `ProjectCreateRequest`: `name`, `description`, `git_remote`, `default_ref`, `project_type`.
- `ProjectUpdateRequest`: permitted metadata fields, including `status: "active" | "archived"`, plus `expected_version: integer` (required).
- `CheckoutRegisterRequest`: `canonical_path`, `branch_or_ref`, `last_known_commit`.
- `CheckoutUpdateRequest`: permitted metadata fields plus `expected_version: integer`.
- `WorkspaceCreateRequest`: `name`, `description`, `project_id`, `configuration_id`, `configuration_revision_id`, `checkout_id` (nullable).
- `WorkspaceUpdateRequest`: permitted fields, including `status: "active" | "archived"`, plus `expected_version: integer` (required).
- `RevisionCreateRequest`: `definition: object`, `parent_revision_id` (string or null), `change_summary: string`, `expected_version: integer` (required).
- `RestoreRevisionRequest`: `change_summary: string`, `expected_version: integer` (required).

Deferred endpoints include revision comparison, export/import, and workspace events. Restore is an essential v1 endpoint, not deferred.

## 11. Desktop integration

Add a Platform area to the existing desktop navigation without replacing Chat, Agents, Memory, Hardware, or Experiments.

Initial management views should support:

- Listing and creating AI configurations.
- Inspecting configuration details and revision history.
- Listing and registering software projects.
- Viewing project checkouts.
- Creating and managing workspaces.
- Inspecting the configuration revision and project/checkout relationship associated with a workspace.

Keep the initial interface focused on management, not a full visual orchestration designer. Use existing React/Vite conventions. No new frontend framework or dependency is authorized.

There is no evident frontend test framework. State this accurately and propose only proportionate validation for the first UI milestone.

## 12. Deterministic test and regression plan

Use deterministic, model-free tests. No real model or provider connection should be required.

Tests should cover:

- Database creation and migration.
- Migration on a database containing existing EvoStore and ResultsDB tables/data.
- Migration atomic rollback on injected failure.
- Repeat initialization.
- Configuration creation and revision history.
- Immutable revision behavior.
- Revision restoration by new revision.
- Content hash consistency.
- Invalid and unsupported definitions.
- Project registration and metadata updates.
- Multiple checkouts for one project.
- Checkout/project relationship integrity.
- Workspace creation and relationship validation.
- Configuration revision ownership enforcement.
- Current-revision invariant, including direct SQL insertion attempts that bypass the service layer.
- Atomicity and rollback.
- Concurrent update/conflict behavior.
- Canonical path uniqueness and missing paths.
- Checkout unregister blocked when referenced.
- API validation, errors, and HTTP status codes.
- Existing persistence, workspace, lifecycle, and Evo Lab regression coverage.

Invalid cross-entity references must be tested at the database level, not only through service methods.

## 13. Implementation sequence

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

Implementation may proceed once the blocking decision in section 16 is resolved: checkout canonicalization, symlink handling, and unavailable-path behavior. The remaining items are contract refinements to finalize during implementation.

## 14. Acceptance criteria

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

## 15. Explicit deferrals and residual risks

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

Residual risks:

- Symlink and TOCTOU behavior around registered directories.
- SQLite composite foreign-key behavior under deferred constraints.
- Concurrent update conflict semantics.
- Compatibility of registry transaction behavior with existing `EvoStore` behavior.
- Desktop testing limitations due to the absence of an evident frontend test framework.

## 16. Unresolved decisions requiring source-level resolution

1. Exact JSON schema validation strictness and forward-compatibility behavior. The common structure is specified, but strictness, unknown-field handling, and evolution policy remain open.
2. Exact conflict response payload and retry/error semantics for stale optimistic-concurrency versions. Integer versions are chosen, but the response body and client retry guidance remain open.
3. Checkout canonicalization, symlink handling, and unavailable-path behavior. This is security-sensitive and requires source-level inspection of `Workspace`; registration rules themselves are specified in section 9.

Resolved and removed from this section: `workspace_events` inclusion (optional, not required for v1); secret-free export/import (deferred unless separately approved); integer optimistic concurrency model; `Workspace` security boundary and checkout registration rules; `EvoStore`/`ResultsDB` connection and migration architecture; cross-database transaction semantics (the registry uses `EvoStore` only); and API contracts specified in sections 7-10.

## 17. Source references

- `src/evo_core/store.py` — EvoStore schema, migrations, connection, lock, close.
- `src/evo_experiments/db.py` — ResultsDB schema, migrations, connection, lock, close.
- `src/evo_core/api.py` — application initialization, API models, routes, executors.
- `src/evo_core/config.py` — runtime configuration and allowed commands.
- `src/evo_core/workspace.py` — path resolution, exclusions, approvals, command allowlist.
- `desktop/src/App.tsx` — navigation and API client.
- `desktop/src/Workspaces.tsx` — workspace components and patterns.
- `desktop/src/style.css` — styling conventions.
- `tests/test_evo_core.py`, `tests/test_persistence_atomicity.py`, `tests/test_agent_orchestration.py`, `tests/test_verified_coding.py`, `tests/test_agent_lifecycle.py`, `tests/test_workspace.py`, `tests/test_execution_recovery.py`, `tests/test_hardware_*` — relevant persistence, security, lifecycle, and execution coverage.

## 18. Verified facts, design decisions, and assumptions

Verified facts come from inspected source. Design decisions are proposed by this document. Items in section 16 are assumptions or unresolved questions requiring source-level resolution before implementation.

## 19. Final scope statement

This document is an implementation design. It is not authorization to begin implementation. Implementation approval follows source inspection and resolution of the open decisions in section 16.
