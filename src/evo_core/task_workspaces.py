"""Task-scoped, revision-pinned Git worktrees for registered Evo workspaces.

This module creates a separate detached Git worktree for one bounded task. It
never edits the registered source checkout and never removes a worktree as
implicit error recovery: incomplete provisioning remains recorded for review.
"""
import os
import re
import subprocess
import uuid
from pathlib import Path

from .project_checkouts import (
    CheckoutPathConflictError,
    CheckoutPathError,
    _canonical_directory,
    _paths_overlap,
    list_all_checkouts,
    register_checkout,
)
from .store import utc_now
from .workspaces import (
    WorkspaceConflictError,
    WorkspaceRelationshipError,
    create_workspace,
    resolve_executable_workspace,
)


TABLE = "task_workspaces"
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


class TaskWorkspaceError(RuntimeError):
    """Base error for task workspace provisioning."""


class TaskWorkspaceValidationError(TaskWorkspaceError, ValueError):
    pass


class TaskWorkspaceConflictError(TaskWorkspaceError):
    pass


class TaskWorkspaceProvisioningError(TaskWorkspaceError):
    def __init__(self, message, operation_id=None, status="failed"):
        super().__init__(message)
        self.operation_id = operation_id
        self.status = status


def _ensure_table(store):
    if store is None or not hasattr(store, "db") or not hasattr(store, "lock"):
        raise ValueError("a valid EvoStore is required")
    with store.lock:
        db = store.db
        db.execute(
            """CREATE TABLE IF NOT EXISTS task_workspaces (
                operation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                parent_workspace_id TEXT NOT NULL,
                task_workspace_id TEXT,
                project_id TEXT NOT NULL,
                checkout_id TEXT,
                source_revision TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('provisioning', 'completed', 'recovery_required', 'failed')),
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (project_id, task_id),
                FOREIGN KEY (parent_workspace_id) REFERENCES workspaces(workspace_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (task_workspace_id) REFERENCES workspaces(workspace_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (project_id) REFERENCES software_projects(project_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (checkout_id) REFERENCES project_checkouts(checkout_id)
                    ON DELETE RESTRICT
            )"""
        )
        db.commit()


def _git(path, *args, timeout=30):
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
            shell=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TaskWorkspaceProvisioningError(f"git operation could not complete: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise TaskWorkspaceProvisioningError(
            f"git {args[0] if args else 'command'} failed (exit {result.returncode}): {detail}"
        )
    return result.stdout.strip()


def _record(store, operation_id, **fields):
    _ensure_table(store)
    allowed = {
        "task_workspace_id", "checkout_id", "status", "error",
    }
    if set(fields) - allowed:
        raise ValueError("unsupported task workspace operation field")
    assignments = ["updated_at=?"]
    values = [utc_now()]
    for key, value in fields.items():
        assignments.append(f"{key}=?")
        values.append(value)
    values.append(operation_id)
    with store.lock:
        store.db.execute(
            f"UPDATE task_workspaces SET {', '.join(assignments)} WHERE operation_id=?",
            values,
        )
        store.db.commit()


def _validate_task_id(task_id):
    if not isinstance(task_id, str) or not task_id.strip():
        raise TaskWorkspaceValidationError("task_id must be a non-empty string")
    task_id = task_id.strip()
    if len(task_id) > 200 or any(ord(char) < 32 for char in task_id):
        raise TaskWorkspaceValidationError("task_id must be at most 200 printable characters")
    return task_id


def _safe_parent(path):
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        raise TaskWorkspaceValidationError("destination_parent must be a non-empty path")
    try:
        canonical = Path(path).expanduser().resolve(strict=True)
        if not canonical.is_dir() or canonical == Path("/") or canonical.parent == canonical:
            raise TaskWorkspaceValidationError("destination_parent must be a safe existing directory")
        if Path(path).expanduser().is_symlink():
            raise TaskWorkspaceValidationError("destination_parent must not be a symlink")
        return canonical
    except TaskWorkspaceValidationError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise TaskWorkspaceValidationError(f"destination_parent cannot be validated: {exc}") from exc


def create_task_workspace(
    store,
    parent_workspace_id,
    task_id,
    destination_parent,
    *,
    source_revision=None,
):
    """Create a detached task worktree from a clean registered workspace.

    The source checkout must be clean (including untracked files). The revision
    must be a full commit object ID. The returned workspace inherits the exact
    immutable AI configuration revision from the parent workspace.
    """
    task_id = _validate_task_id(task_id)
    _ensure_table(store)
    parent = resolve_executable_workspace(store, parent_workspace_id)
    source = Path(parent["canonical_path"])
    destination_root = _safe_parent(destination_parent)

    current_head = _git(source, "rev-parse", "--verify", "HEAD")
    revision = current_head if source_revision is None else source_revision
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise TaskWorkspaceValidationError("source_revision must be a full Git commit ID")
    resolved_revision = _git(source, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if resolved_revision.lower() != revision.lower():
        raise TaskWorkspaceValidationError("source_revision must be the canonical full commit ID")

    status = _git(source, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise TaskWorkspaceConflictError(
            "source checkout is dirty; commit or otherwise resolve its changes before provisioning"
        )

    operation_id = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:12]
    safe_task = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-._")[:32] or "task"
    destination = destination_root / f"evo-{safe_task}-{suffix}"
    canonical_destination = str(destination.resolve(strict=False))

    for checkout in list_all_checkouts(store):
        if _paths_overlap(canonical_destination, checkout["canonical_path"]):
            raise TaskWorkspaceConflictError("task worktree path overlaps a registered checkout")

    now = utc_now()
    with store.lock:
        try:
            store.db.execute(
                """INSERT INTO task_workspaces
                   (operation_id, task_id, parent_workspace_id, project_id,
                    source_revision, destination_path, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'provisioning', ?, ?)""",
                (
                    operation_id, task_id, parent_workspace_id, parent["project_id"],
                    resolved_revision, canonical_destination, now, now,
                ),
            )
            store.db.commit()
        except Exception as exc:
            store.db.rollback()
            if "UNIQUE constraint failed" in str(exc):
                raise TaskWorkspaceConflictError(
                    "a task workspace already exists for this task and project"
                ) from exc
            raise

    worktree_created = False
    try:
        if destination.exists() or destination.is_symlink():
            raise TaskWorkspaceConflictError("generated task worktree destination already exists")
        # Recheck registry overlap immediately before Git creates the path.
        for checkout in list_all_checkouts(store):
            if _paths_overlap(canonical_destination, checkout["canonical_path"]):
                raise TaskWorkspaceConflictError("task worktree path overlaps a registered checkout")
        _git(source, "worktree", "add", "--detach", str(destination), resolved_revision, timeout=120)
        worktree_created = True

        actual_path = _canonical_directory(destination)
        if actual_path != canonical_destination:
            raise TaskWorkspaceProvisioningError("created worktree resolved to an unexpected path")
        actual_head = _git(destination, "rev-parse", "--verify", "HEAD")
        if actual_head.lower() != resolved_revision.lower():
            raise TaskWorkspaceProvisioningError("created worktree does not match the pinned source revision")
        if _git(destination, "status", "--porcelain", "--untracked-files=all"):
            raise TaskWorkspaceProvisioningError("new task worktree is unexpectedly dirty")

        checkout = register_checkout(
            store,
            parent["project_id"],
            destination,
            branch_or_ref="HEAD (detached task worktree)",
            last_known_commit=resolved_revision,
        )
        _record(store, operation_id, checkout_id=checkout["checkout_id"])

        task_workspace = create_workspace(
            store,
            f"{parent['workspace']['name']} — {task_id}",
            parent["project_id"],
            parent["configuration_id"],
            parent["configuration_revision_id"],
            checkout_id=checkout["checkout_id"],
            description=f"Task-isolated workspace for task {task_id}; source revision {resolved_revision}.",
        )
        _record(
            store,
            operation_id,
            task_workspace_id=task_workspace["workspace_id"],
            status="completed",
        )
        return {
            "operation_id": operation_id,
            "status": "completed",
            "task_id": task_id,
            "parent_workspace_id": parent_workspace_id,
            "workspace": task_workspace,
            "checkout": checkout,
            "source_revision": resolved_revision,
            "canonical_path": actual_path,
            "worktree_created": True,
        }
    except Exception as exc:
        status_value = "recovery_required" if worktree_created else "failed"
        try:
            _record(
                store,
                operation_id,
                status=status_value,
                error=f"{type(exc).__name__}: {exc}"[:4000],
            )
        except Exception:
            pass
        if isinstance(exc, TaskWorkspaceError):
            if isinstance(exc, TaskWorkspaceProvisioningError):
                exc.operation_id = operation_id
                exc.status = status_value
            raise
        if isinstance(exc, (CheckoutPathError, CheckoutPathConflictError,
                            WorkspaceRelationshipError, WorkspaceConflictError)):
            raise TaskWorkspaceProvisioningError(
                str(exc), operation_id=operation_id, status=status_value
            ) from exc
        raise TaskWorkspaceProvisioningError(
            str(exc), operation_id=operation_id, status=status_value
        ) from exc


def get_task_workspace_operation(store, operation_id):
    _ensure_table(store)
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM task_workspaces WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    if row is None:
        raise TaskWorkspaceValidationError("task workspace operation not found")
    return dict(row)


def get_task_workspace_for_task(store, project_id, task_id):
    task_id = _validate_task_id(task_id)
    _ensure_table(store)
    with store.lock:
        row = store.db.execute(
            """SELECT * FROM task_workspaces
               WHERE project_id=? AND task_id=?""",
            (project_id, task_id),
        ).fetchone()
    return None if row is None else dict(row)
