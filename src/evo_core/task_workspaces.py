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
from .workspace import _is_excluded
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
    # Do not inherit repository-selection or index overrides from the Evo
    # server environment; they could redirect Git away from the validated path.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "0"
    command = [
        "git", "-C", str(path),
        "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false",
        "-c", "credential.helper=",
    ]
    # A repository-local filter process/smudge command can execute during
    # worktree checkout. Discover configured filter keys as data, then blank
    # both execution mechanisms for each driver in this operation.
    if args[:2] == ("worktree", "add"):
        config = subprocess.run(
            ["git", "-C", str(path), "config", "--local", "--name-only", "--get-regexp",
             r"^filter\..*\.(smudge|process)$"],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False, timeout=10, shell=False, env=env,
        )
        if config.returncode not in (0, 1):
            raise TaskWorkspaceProvisioningError("could not inspect repository filter configuration")
        for key in sorted(set(config.stdout.splitlines())):
            if re.fullmatch(r"filter\.[A-Za-z0-9._-]+\.(smudge|process)", key):
                command.extend(["-c", f"{key}="])
    command.extend(args)
    try:
        result = subprocess.run(
            command,
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
        expanded = Path(path).expanduser()
        lexical = Path(os.path.abspath(os.fspath(expanded)))
        # Reject symlinks in every existing path component, not only the final
        # directory. Resolving first and checking afterward would hide them.
        cursor = Path(lexical.anchor)
        for component in lexical.parts[1:]:
            cursor = cursor / component
            if cursor.is_symlink():
                raise TaskWorkspaceValidationError(
                    "destination_parent must not contain symlink components"
                )
        canonical = lexical.resolve(strict=True)
        if not canonical.is_dir() or canonical == Path("/") or canonical.parent == canonical:
            raise TaskWorkspaceValidationError("destination_parent must be a safe existing directory")
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


DEFAULT_REVIEW_MAX_FILES = 100
DEFAULT_REVIEW_MAX_BYTES = 256 * 1024


def get_task_workspace_review(
    store,
    operation_id,
    *,
    max_files=DEFAULT_REVIEW_MAX_FILES,
    max_bytes=DEFAULT_REVIEW_MAX_BYTES,
):
    """Return a bounded, read-only review artifact for a completed task workspace."""
    _ensure_table(store)
    operation = get_task_workspace_operation(store, operation_id)
    if operation["status"] != "completed":
        raise TaskWorkspaceValidationError(
            "task workspace operation is not completed and cannot be reviewed"
        )
    if not operation.get("task_workspace_id") or not operation.get("checkout_id"):
        raise TaskWorkspaceValidationError("task workspace operation is incomplete")
    binding = resolve_executable_workspace(store, operation["task_workspace_id"])
    if binding["checkout_id"] != operation["checkout_id"]:
        raise TaskWorkspaceValidationError("task workspace checkout does not match the operation")
    if str(binding.path) != str(operation["destination_path"]):
        raise TaskWorkspaceValidationError("task workspace path does not match the recorded destination")

    root = binding.path
    baseline = operation["source_revision"]
    max_files = max(1, int(max_files))
    max_bytes = max(1024, int(max_bytes))

    head_before = _git(root, "rev-parse", "--verify", "HEAD")
    status_before = _git(root, "status", "--porcelain", "--untracked-files=all")

    changed = []  # list of (status, path)
    excluded = []
    unreadable = []
    patch_parts = []
    total_bytes = 0
    truncated = False
    truncation_reason = None
    unstable = False

    def add_text(text):
        nonlocal total_bytes, truncated, truncation_reason
        data = text.encode("utf-8", errors="replace")
        if total_bytes + len(data) > max_bytes:
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
            return False
        patch_parts.append(text)
        total_bytes += len(data)
        return True

    # Tracked changes relative to the immutable baseline.
    try:
        name_status = _git(root, "diff", "--name-status", baseline)
    except TaskWorkspaceProvisioningError:
        name_status = ""
    tracked_lines = [line for line in name_status.splitlines() if line.strip()]
    for line in tracked_lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        path = parts[-1].strip()
        if not path:
            continue
        rel = Path(path)
        if _is_excluded(rel):
            excluded.append(path)
            continue
        if (root / rel).is_symlink():
            unreadable.append({"path": path, "reason": "symlink"})
            continue
        if len(changed) >= max_files:
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"
            continue
        changed.append((status, path))

    # Untracked files.
    try:
        untracked_output = _git(root, "ls-files", "--others", "--exclude-standard")
    except TaskWorkspaceProvisioningError:
        untracked_output = ""
    untracked_paths = [p for p in untracked_output.splitlines() if p.strip()]
    for path in untracked_paths:
        rel = Path(path)
        if _is_excluded(rel):
            excluded.append(path)
            continue
        candidate = root / rel
        if candidate.is_symlink():
            unreadable.append({"path": path, "reason": "symlink"})
            continue
        if not candidate.is_file():
            continue
        if len(changed) >= max_files:
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"
            continue
        changed.append(("?", path))

    # Build patch for tracked changes.
    if not truncated:
        try:
            tracked_patch = _git(root, "diff", baseline)
        except TaskWorkspaceProvisioningError:
            tracked_patch = ""
        if tracked_patch:
            if not add_text(tracked_patch + "\n"):
                truncated = True
                if truncation_reason is None:
                    truncation_reason = "output_limit"

    # Include readable untracked file contents.
    for status, path in changed:
        if status != "?":
            continue
        if truncated and truncation_reason == "output_limit":
            break
        candidate = root / Path(path)
        try:
            data = candidate.read_bytes()
        except OSError:
            unreadable.append({"path": path, "reason": "unreadable"})
            continue
        if b"\x00" in data[:4096]:
            unreadable.append({"path": path, "reason": "binary"})
            continue
        text = data.decode("utf-8", errors="replace")
        entry = f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,1 @@\n"
        # Keep it simple: include full content as an added file.
        content_lines = text.splitlines()
        entry += "".join(f"+{line}\n" for line in content_lines)
        if not add_text(entry):
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
            break

    head_after = _git(root, "rev-parse", "--verify", "HEAD")
    status_after = _git(root, "status", "--porcelain", "--untracked-files=all")
    snapshot_stable = (head_before == head_after and status_before == status_after)
    if not snapshot_stable:
        unstable = True
        if truncation_reason is None:
            truncation_reason = "snapshot_unstable"

    return {
        "operation_id": operation["operation_id"],
        "status": "ok",
        "stable": snapshot_stable,
        "unstable": unstable,
        "source_revision": baseline,
        "current_head": head_after,
        "changed_files": [{"status": s, "path": p} for s, p in changed],
        "changed_file_count": len(changed),
        "excluded_files": sorted(set(excluded)),
        "unreadable_files": unreadable,
        "patch": "".join(patch_parts),
        "patch_bytes": total_bytes,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "max_files": max_files,
        "max_bytes": max_bytes,
    }


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
