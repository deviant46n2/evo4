import sqlite3
from datetime import datetime, timezone

MIGRATION_NAME = "platform_registry_v1"

PLATFORM_REGISTRY_DDL = (
    """CREATE TABLE IF NOT EXISTS ai_configurations (
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
)""",
    """CREATE TABLE IF NOT EXISTS ai_configuration_revisions (
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
)""",
    """CREATE TRIGGER IF NOT EXISTS ai_configuration_revisions_no_update
BEFORE UPDATE ON ai_configuration_revisions
BEGIN
    SELECT RAISE(ABORT, 'AI configuration revisions are immutable');
END""",
    """CREATE TRIGGER IF NOT EXISTS ai_configuration_revisions_no_delete
BEFORE DELETE ON ai_configuration_revisions
BEGIN
    SELECT RAISE(ABORT, 'AI configuration revisions cannot be deleted');
END""",
    """CREATE TABLE IF NOT EXISTS software_projects (
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
)""",
    """CREATE TABLE IF NOT EXISTS project_checkouts (
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
)""",
    """CREATE TABLE IF NOT EXISTS workspaces (
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
)""",
    "CREATE INDEX IF NOT EXISTS idx_ai_configurations_status ON ai_configurations(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_ai_configuration_revisions_configuration ON ai_configuration_revisions(configuration_id, revision_number)",
    "CREATE INDEX IF NOT EXISTS idx_software_projects_status ON software_projects(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_project_checkouts_project ON project_checkouts(project_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_workspaces_project ON workspaces(project_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_workspaces_configuration ON workspaces(configuration_id, configuration_revision_id)",
)


def initialize_platform_registry(store):
    if store is None:
        raise ValueError("store is required")
    db = store.db
    lock = store.lock
    with lock:
        if getattr(db, "in_transaction", False):
            raise RuntimeError("unexpected active transaction on EvoStore connection")
        foreign_keys = db.execute("PRAGMA foreign_keys").fetchone()[0]
        if foreign_keys != 1:
            raise RuntimeError("foreign keys must be enabled on the EvoStore connection")
        db.execute("BEGIN IMMEDIATE")
        try:
            applied = db.execute(
                "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
            ).fetchone()
            if not applied:
                for statement in PLATFORM_REGISTRY_DDL:
                    db.execute(statement)
                db.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                    (MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
                )
            db.commit()
        except Exception:
            if getattr(db, "in_transaction", False):
                db.rollback()
            raise

    # Separate additive migration: run even when the original Registry schema
    # was already initialized on an earlier application version.
    from .workspace_binding_history import initialize_workspace_binding_history
    initialize_workspace_binding_history(store)
    from .runtime_invocation_snapshots import initialize_runtime_invocation_snapshots
    initialize_runtime_invocation_snapshots(store)
    return "initialized" if not applied else "already-initialized"
