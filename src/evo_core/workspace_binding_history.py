"""Version-checked workspace binding changes with append-only provenance.

This module changes only the Registry binding. It never constructs or dispatches
a provider. Runtime snapshots and invocation admission are separate boundaries.
"""
import uuid

from .store import utc_now
from . import workspaces


MIGRATION_NAME = "workspace_binding_history_v1"


def initialize_workspace_binding_history(store):
    db = workspaces._store_db(store)
    with store.lock:
        if db.in_transaction:
            raise RuntimeError("unexpected active transaction on EvoStore connection")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS workspace_binding_history (
                    history_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
                    from_version INTEGER NOT NULL,
                    to_version INTEGER NOT NULL,
                    old_configuration_id TEXT NOT NULL,
                    old_revision_id TEXT NOT NULL,
                    new_configuration_id TEXT NOT NULL,
                    new_revision_id TEXT NOT NULL,
                    old_checkout_id TEXT,
                    new_checkout_id TEXT,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    CHECK (to_version = from_version + 1)
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_workspace_binding_history_workspace
                ON workspace_binding_history(workspace_id, to_version)
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS workspace_binding_history_no_update
                BEFORE UPDATE ON workspace_binding_history
                BEGIN
                    SELECT RAISE(ABORT, 'workspace binding history is append-only');
                END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS workspace_binding_history_no_delete
                BEFORE DELETE ON workspace_binding_history
                BEGIN
                    SELECT RAISE(ABORT, 'workspace binding history cannot be deleted');
                END
            """)
            applied = db.execute(
                "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
            ).fetchone()
            if not applied:
                db.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                    (MIGRATION_NAME, utc_now()),
                )
            db.commit()
            return "already-initialized" if applied else "initialized"
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise


def rebind_workspace(
    store,
    workspace_id,
    *,
    configuration_id,
    configuration_revision_id,
    checkout_id=None,
    expected_version,
    actor="operator",
    reason,
):
    """Atomically replace a workspace's pinned config/revision/checkout.

    Callers must supply the observed workspace version. A stale edit is rejected;
    there is no last-writer-wins behavior. Passing checkout_id=None deliberately
    removes the checkout and therefore makes the workspace non-executable.
    """
    expected_version = workspaces._expected_version(expected_version)
    workspace_id = workspaces._text(workspace_id, "workspace_id", required=True)
    configuration_id = workspaces._text(configuration_id, "configuration_id", required=True)
    configuration_revision_id = workspaces._text(
        configuration_revision_id, "configuration_revision_id", required=True
    )
    actor = workspaces._text(actor, "actor", required=True)
    reason = workspaces._text(reason, "reason", required=True)
    if checkout_id is not None:
        checkout_id = workspaces._text(checkout_id, "checkout_id", required=True)

    def operation(db):
        current = workspaces._workspace_row(db, workspace_id)
        if current["version"] != expected_version:
            raise workspaces.WorkspaceConflictError("stale workspace version")
        if current["status"] != "active":
            raise workspaces.WorkspaceRelationshipError("workspace must be active to rebind")
        project = workspaces._project_row(db, current["project_id"])
        if project["status"] != "active":
            raise workspaces.WorkspaceRelationshipError("project must be active")
        configuration = workspaces._configuration_row(db, configuration_id)
        if configuration["status"] != "active":
            raise workspaces.WorkspaceRelationshipError("configuration must be active")
        workspaces._revision_row(db, configuration_id, configuration_revision_id)
        if checkout_id is not None:
            checkout = workspaces._checkout_row(db, checkout_id)
            if checkout["project_id"] != current["project_id"]:
                raise workspaces.WorkspaceRelationshipError(
                    "checkout does not belong to the workspace project"
                )
            if checkout["availability_status"] != "available":
                raise workspaces.WorkspaceRelationshipError("checkout is not available")
        target = (configuration_id, configuration_revision_id, checkout_id)
        previous = (
            current["configuration_id"],
            current["configuration_revision_id"],
            current["checkout_id"],
        )
        if target == previous:
            raise workspaces.WorkspaceValidationError("workspace binding is unchanged")
        now = utc_now()
        cursor = db.execute(
            """UPDATE workspaces
               SET configuration_id=?, configuration_revision_id=?, checkout_id=?,
                   updated_at=?, version=?
               WHERE workspace_id=? AND version=?""",
            (
                configuration_id, configuration_revision_id, checkout_id, now,
                expected_version + 1, workspace_id, expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise workspaces.WorkspaceConflictError("stale workspace version")
        db.execute(
            """INSERT INTO workspace_binding_history (
                history_id, workspace_id, from_version, to_version,
                old_configuration_id, old_revision_id,
                new_configuration_id, new_revision_id,
                old_checkout_id, new_checkout_id, actor, reason, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), workspace_id, expected_version, expected_version + 1,
                current["configuration_id"], current["configuration_revision_id"],
                configuration_id, configuration_revision_id,
                current["checkout_id"], checkout_id, actor, reason, now,
            ),
        )
        return workspaces._workspace_row(db, workspace_id)

    return workspaces._write(store, operation)


def list_workspace_binding_history(store, workspace_id):
    workspaces._text(workspace_id, "workspace_id", required=True)

    def operation(db):
        workspaces._workspace_row(db, workspace_id)
        return [
            dict(row) for row in db.execute(
                """SELECT * FROM workspace_binding_history
                   WHERE workspace_id=? ORDER BY to_version, history_id""",
                (workspace_id,),
            ).fetchall()
        ]

    return workspaces._read(store, operation)
