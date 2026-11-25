import sqlite3
import uuid
from pathlib import Path

from .store import utc_now
from . import project_checkouts
from .ai_configurations import _decode_row


class WorkspaceNotFoundError(Exception):
    pass


class WorkspaceValidationError(ValueError):
    pass


class WorkspaceConflictError(Exception):
    pass


class WorkspaceRelationshipError(WorkspaceValidationError):
    pass


def _expected_version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkspaceValidationError("expected_version must be a positive integer")
    return value


def _text(value, field, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise WorkspaceValidationError(f"{field} must be a string")
    if required and not value.strip():
        raise WorkspaceValidationError(f"{field} must not be empty")
    return value.strip() if required else value


def _store_db(store):
    if store is None or not hasattr(store, "db") or not hasattr(store, "lock"):
        raise ValueError("a valid EvoStore is required")
    return store.db


def _write(store, operation):
    db = _store_db(store)
    with store.lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            result = operation(db)
            db.commit()
            return result
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise


def _read(store, operation):
    db = _store_db(store)
    with store.lock:
        return operation(db)


def _workspace_row(db, workspace_id):
    row = db.execute(
        "SELECT * FROM workspaces WHERE workspace_id=?", (workspace_id,)
    ).fetchone()
    if row is None:
        raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
    return dict(row)


def _project_row(db, project_id):
    row = db.execute(
        "SELECT * FROM software_projects WHERE project_id=?", (project_id,)
    ).fetchone()
    if row is None:
        raise WorkspaceRelationshipError(f"project not found: {project_id}")
    return dict(row)


def _configuration_row(db, configuration_id):
    row = db.execute(
        "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
    ).fetchone()
    if row is None:
        raise WorkspaceRelationshipError(f"configuration not found: {configuration_id}")
    return dict(row)


def _revision_row(db, configuration_id, revision_id):
    row = db.execute(
        "SELECT * FROM ai_configuration_revisions WHERE configuration_id=? AND revision_id=?",
        (configuration_id, revision_id),
    ).fetchone()
    if row is None:
        raise WorkspaceRelationshipError(
            f"revision not found: {revision_id} for configuration {configuration_id}"
        )
    return _decode_row(row)


def _checkout_row(db, checkout_id):
    row = db.execute(
        "SELECT * FROM project_checkouts WHERE checkout_id=?", (checkout_id,)
    ).fetchone()
    if row is None:
        raise WorkspaceRelationshipError(f"checkout not found: {checkout_id}")
    return dict(row)


def create_workspace(
    store,
    name,
    project_id,
    configuration_id,
    configuration_revision_id,
    *,
    checkout_id=None,
    description="",
):
    name = _text(name, "name", required=True)
    if description is None:
        raise WorkspaceValidationError("description must be a string")
    description = _text(description, "description")
    if not isinstance(project_id, str) or not project_id.strip():
        raise WorkspaceValidationError("project_id must be a non-empty string")
    if not isinstance(configuration_id, str) or not configuration_id.strip():
        raise WorkspaceValidationError("configuration_id must be a non-empty string")
    if not isinstance(configuration_revision_id, str) or not configuration_revision_id.strip():
        raise WorkspaceValidationError("configuration_revision_id must be a non-empty string")
    if checkout_id is not None:
        if not isinstance(checkout_id, str) or not checkout_id.strip():
            raise WorkspaceValidationError("checkout_id must be None or a non-empty string")
    workspace_id = str(uuid.uuid4())
    now = utc_now()

    def operation(db):
        project = _project_row(db, project_id)
        if project["status"] != "active":
            raise WorkspaceRelationshipError("project must be active")
        configuration = _configuration_row(db, configuration_id)
        if configuration["status"] != "active":
            raise WorkspaceRelationshipError("configuration must be active")
        _revision_row(db, configuration_id, configuration_revision_id)
        if checkout_id is not None:
            checkout = _checkout_row(db, checkout_id)
            if checkout["project_id"] != project_id:
                raise WorkspaceRelationshipError("checkout does not belong to the project")
            if checkout["availability_status"] != "available":
                raise WorkspaceRelationshipError("checkout is not available")
        db.execute(
            """INSERT INTO workspaces
               (workspace_id, name, description, project_id, checkout_id,
                configuration_id, configuration_revision_id, status,
                created_at, updated_at, version)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 1)""",
            (
                workspace_id,
                name,
                description,
                project_id,
                checkout_id,
                configuration_id,
                configuration_revision_id,
                now,
                now,
            ),
        )
        return _workspace_row(db, workspace_id)

    return _write(store, operation)


def get_workspace(store, workspace_id):
    return _read(store, lambda db: _workspace_row(db, workspace_id))


def list_workspaces(store, *, project_id=None, configuration_id=None, status=None):
    if status is not None:
        if not isinstance(status, str):
            raise WorkspaceValidationError("status must be a string")
        if status not in {"active", "archived"}:
            raise WorkspaceValidationError("status must be active or archived")
    if project_id is not None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise WorkspaceValidationError("project_id must be a non-empty string")
        _read(store, lambda db: _project_row(db, project_id))
    if configuration_id is not None:
        if not isinstance(configuration_id, str) or not configuration_id.strip():
            raise WorkspaceValidationError("configuration_id must be a non-empty string")
        _read(store, lambda db: _configuration_row(db, configuration_id))

    def operation(db):
        clauses = []
        params = []
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(project_id)
        if configuration_id is not None:
            clauses.append("configuration_id=?")
            params.append(configuration_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        sql = "SELECT * FROM workspaces"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, workspace_id"
        rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    return _read(store, operation)


def archive_workspace(store, workspace_id, *, expected_version):
    expected_version = _expected_version(expected_version)

    def operation(db):
        workspace = _workspace_row(db, workspace_id)
        if workspace["version"] != expected_version:
            raise WorkspaceConflictError("stale workspace version")
        now = utc_now()
        cursor = db.execute(
            """UPDATE workspaces
               SET status='archived', updated_at=?, version=?
               WHERE workspace_id=? AND version=?""",
            (now, expected_version + 1, workspace_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise WorkspaceConflictError("stale workspace version")
        return _workspace_row(db, workspace_id)

    return _write(store, operation)


def reactivate_workspace(store, workspace_id, *, expected_version):
    expected_version = _expected_version(expected_version)

    def operation(db):
        workspace = _workspace_row(db, workspace_id)
        if workspace["version"] != expected_version:
            raise WorkspaceConflictError("stale workspace version")
        project = _project_row(db, workspace["project_id"])
        if project["status"] != "active":
            raise WorkspaceRelationshipError("project must be active")
        configuration = _configuration_row(db, workspace["configuration_id"])
        if configuration["status"] != "active":
            raise WorkspaceRelationshipError("configuration must be active")
        if workspace["checkout_id"] is not None:
            checkout = _checkout_row(db, workspace["checkout_id"])
            if checkout["project_id"] != workspace["project_id"]:
                raise WorkspaceRelationshipError("checkout does not belong to the project")
            if checkout["availability_status"] != "available":
                raise WorkspaceRelationshipError("checkout is not available")
        now = utc_now()
        cursor = db.execute(
            """UPDATE workspaces
               SET status='active', updated_at=?, version=?
               WHERE workspace_id=? AND version=?""",
            (now, expected_version + 1, workspace_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise WorkspaceConflictError("stale workspace version")
        return _workspace_row(db, workspace_id)

    return _write(store, operation)


class WorkspaceNotExecutableError(WorkspaceRelationshipError):
    pass


def resolve_executable_workspace(store, workspace_id):
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise WorkspaceValidationError("workspace_id must be a non-empty string")
    workspace_id = workspace_id.strip()

    def operation(db):
        workspace = _workspace_row(db, workspace_id)
        if workspace["status"] != "active":
            raise WorkspaceRelationshipError("workspace must be active")
        project = _project_row(db, workspace["project_id"])
        if project["status"] != "active":
            raise WorkspaceRelationshipError("project must be active")
        configuration = _configuration_row(db, workspace["configuration_id"])
        if configuration["status"] != "active":
            raise WorkspaceRelationshipError("configuration must be active")
        revision = _revision_row(db, workspace["configuration_id"], workspace["configuration_revision_id"])
        checkout_id = workspace["checkout_id"]
        if not checkout_id:
            raise WorkspaceNotExecutableError("workspace has no registered checkout and cannot be used as an execution target")
        checkout = _checkout_row(db, checkout_id)
        if checkout["project_id"] != workspace["project_id"]:
            raise WorkspaceRelationshipError("checkout does not belong to the workspace project")
        if checkout["availability_status"] != "available":
            raise WorkspaceRelationshipError("checkout is not available")
        current_availability = project_checkouts._availability(checkout["canonical_path"])
        if current_availability != "available":
            raise WorkspaceRelationshipError("checkout is not currently available")
        try:
            canonical = project_checkouts._canonical_directory(checkout["canonical_path"])
        except project_checkouts.CheckoutPathError as exc:
            raise WorkspaceRelationshipError(str(exc)) from exc
        if canonical != checkout["canonical_path"]:
            raise WorkspaceRelationshipError("registered checkout path resolves to a different directory")
        path = Path(canonical)
        if not path.is_dir():
            raise WorkspaceRelationshipError("registered checkout is not a directory")
        binding = _ExecutableWorkspaceBinding(
            workspace=workspace,
            project=project,
            configuration=configuration,
            revision=revision,
            checkout=checkout,
            path=path,
        )
        return binding

    return _read(store, operation)


class _ExecutableWorkspaceBinding(dict):
    def __init__(self, *, workspace, project, configuration, revision, checkout, path):
        super().__init__(
            workspace_id=workspace["workspace_id"],
            project_id=workspace["project_id"],
            configuration_id=workspace["configuration_id"],
            configuration_revision_id=workspace["configuration_revision_id"],
            checkout_id=workspace["checkout_id"],
            status=workspace["status"],
            workspace=workspace,
            project=project,
            configuration=configuration,
            revision=revision,
            checkout=checkout,
            path=path,
            canonical_path=path,
            workspace_path=path,
        )
        self.workspace = workspace
        self.project = project
        self.configuration = configuration
        self.revision = revision
        self.checkout = checkout
        self.path = path
        self.canonical_path = path
        self.workspace_path = path
        self.workspace_id = workspace["workspace_id"]
