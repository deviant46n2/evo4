"""Task-scoped, revision-pinned Git worktrees for registered Evo workspaces.

This module creates a separate detached Git worktree for one bounded task. It
never edits the registered source checkout and never removes a worktree as
implicit error recovery: incomplete provisioning remains recorded for review.
"""
import os
import signal
import hashlib
import stat
import time
import re
import subprocess
import uuid
import threading
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


def _cleanup_process_group(proc):
    """Terminate and reap a process group. Returns None."""
    if proc is None:
        return
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            pid = int(entry)
            with open(f"/proc/{pid}/stat", "r") as handle:
                stat = handle.read()
            if ")" not in stat:
                continue
            pgrp = int(stat.rsplit(")", 1)[-1].split()[2])
            if pgrp == proc.pid and pid != os.getpid():
                try:
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
        except (OSError, ValueError):
            continue
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


_DEFAULT_GIT_OUTPUT_BYTES = 8 * 1024 * 1024


def _git(path, *args, timeout=30, max_output_bytes=None, truncated=None, env=None, metrics=None, discover_helpers=True, strip_output=True):
    """Run Git without inherited Git overrides, external helpers, or unbounded output."""
    operation_deadline = __import__("time").monotonic() + timeout
    safe_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if env is not None:
        safe_env.update({key: value for key, value in env.items() if not key.startswith("GIT_")})
    safe_env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
    })
    root = str(Path(path).resolve())
    overrides = []
    if discover_helpers:
        # Repository configuration is mutable independently of this process.
        # Never cache helper discovery: a stale empty cache can allow a newly
        # configured clean/smudge/process filter or diff helper to execute.
        helper_keys = []
        for pattern in (
            r"^filter\..*\.(clean|smudge|process)$",
            r"^diff\..*\.(command|textconv)$",
        ):
            discovery_truncated = []
            discovery_remaining = operation_deadline - __import__("time").monotonic()
            if discovery_remaining <= 0:
                raise TaskWorkspaceProvisioningError("git helper discovery timed out")
            try:
                discovery = _git(
                    root, "config", "--local", "--name-only", "--get-regexp", pattern,
                    timeout=min(discovery_remaining, 10), max_output_bytes=65536,
                    truncated=discovery_truncated, env=safe_env, discover_helpers=False,
                )
            except TaskWorkspaceProvisioningError as exc:
                if getattr(exc, "exit_code", None) == 1:
                    discovery = ""
                else:
                    raise
            if discovery_truncated:
                raise TaskWorkspaceProvisioningError("Git helper discovery was incomplete")
            helper_keys.extend(line for line in discovery.splitlines() if line)
        for key in sorted(set(helper_keys)):
            if re.fullmatch(r'filter\..+\.(clean|smudge|process)', key) or re.fullmatch(r'diff\..+\.(command|textconv)', key):
                overrides.extend(["-c", f"{key}="])

    command = [
        "git", "--literal-pathspecs", "-C", root,
        "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false",
        "-c", "core.attributesFile=/dev/null",
        "-c", "credential.helper=",
        *overrides,
    ]
    if args:
        command.extend(args[:1])
        if args[0] == "diff":
            command.extend(["--no-ext-diff", "--no-textconv"])
        command.extend(args[1:])
    limit = _DEFAULT_GIT_OUTPUT_BYTES if max_output_bytes is None else max_output_bytes
    proc = None
    stdout_chunks, stderr_chunks = [], []
    total = [0]
    exceeded = [False]
    reader_errors = []
    lock = threading.Lock()

    try:
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env=safe_env, start_new_session=True,
        )

        def reader(stream, chunks):
            try:
                while True:
                    chunk = os.read(stream.fileno(), 8192)
                    if not chunk:
                        break
                    with lock:
                        available = max(0, limit - total[0])
                        if available:
                            kept = chunk[:available]
                            chunks.append(kept)
                            total[0] += len(kept)
                        if len(chunk) > available:
                            exceeded[0] = True
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            except OSError:
                                try:
                                    proc.kill()
                                except OSError:
                                    pass
                            break
            except OSError as exc:
                reader_errors.append(exc)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    try:
                        proc.kill()
                    except OSError:
                        pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        out_thread = threading.Thread(target=reader, args=(proc.stdout, stdout_chunks), daemon=True)
        err_thread = threading.Thread(target=reader, args=(proc.stderr, stderr_chunks), daemon=True)
        out_thread.start()
        err_thread.start()
        try:
            remaining = operation_deadline - __import__("time").monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            _cleanup_process_group(proc)
            out_thread.join(timeout=2)
            err_thread.join(timeout=2)
            raise TaskWorkspaceProvisioningError("git operation timed out") from exc
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)
        if out_thread.is_alive() or err_thread.is_alive():
            _cleanup_process_group(proc)
            out_thread.join(timeout=2)
            err_thread.join(timeout=2)
            raise TaskWorkspaceProvisioningError("git output collection did not terminate")
        if proc.returncode is None:
            raise TaskWorkspaceProvisioningError("git process was not reaped")
        if reader_errors:
            raise TaskWorkspaceProvisioningError("git output collection failed") from reader_errors[0]
        stdout = b"".join(stdout_chunks).decode("utf-8", errors="surrogateescape")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if metrics is not None:
            metrics["captured_bytes"] = total[0]
        if exceeded[0]:
            if truncated is not None:
                truncated.append(True)
            else:
                raise TaskWorkspaceProvisioningError("git output exceeded its safety limit")
        if proc.returncode and not exceeded[0]:
            exc = TaskWorkspaceProvisioningError(
                f"git {args[0] if args else 'command'} failed (exit {proc.returncode}): {(stderr or stdout).strip()[-1000:]}"
            )
            exc.exit_code = proc.returncode
            raise exc
        return stdout.strip() if strip_output else stdout
    except TaskWorkspaceProvisioningError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if proc is not None and proc.poll() is None:
            _cleanup_process_group(proc)
        raise TaskWorkspaceProvisioningError("git operation could not complete") from exc


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
    worktree_creation_attempted = False
    try:
        if destination.exists() or destination.is_symlink():
            raise TaskWorkspaceConflictError("generated task worktree destination already exists")
        # Recheck registry overlap immediately before Git creates the path.
        for checkout in list_all_checkouts(store):
            if _paths_overlap(canonical_destination, checkout["canonical_path"]):
                raise TaskWorkspaceConflictError("task worktree path overlaps a registered checkout")
        worktree_creation_attempted = True
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
        status_value = "recovery_required" if (worktree_created or worktree_creation_attempted) else "failed"
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


def list_task_workspace_operations(store, *, project_id=None, status=None, limit=100):
    """List task workspace operation records without touching their worktrees."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise TaskWorkspaceValidationError("limit must be an integer between 1 and 500")
    if project_id is not None and (
        not isinstance(project_id, str) or not project_id.strip() or len(project_id) > 128
    ):
        raise TaskWorkspaceValidationError("project_id must be a non-empty identifier")
    allowed_statuses = {"provisioning", "completed", "recovery_required", "failed"}
    if status is not None and (
        not isinstance(status, str) or status not in allowed_statuses
    ):
        raise TaskWorkspaceValidationError("unsupported task workspace status")
    _ensure_table(store)
    clauses, values = [], []
    if project_id is not None:
        clauses.append("project_id=?")
        values.append(project_id.strip())
    if status is not None:
        clauses.append("status=?")
        values.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with store.lock:
        rows = store.db.execute(
            "SELECT * FROM task_workspaces" + where +
            " ORDER BY created_at DESC, operation_id DESC LIMIT ?",
            (*values, limit),
        ).fetchall()
    public_fields = (
        "operation_id", "task_id", "parent_workspace_id", "task_workspace_id",
        "project_id", "checkout_id", "source_revision", "destination_path",
        "status", "created_at", "updated_at",
    )
    return [
        {**{key: row[key] for key in public_fields}, "error_recorded": bool(row["error"])}
        for row in rows
    ]


def get_task_workspace_operation_status(store, operation_id):
    """Return a read-only operation snapshot with conservative filesystem observations.

    This deliberately does not infer that a provisioning record is abandoned,
    change its status, invoke Git, or remove/re-register any filesystem resource.
    """
    operation = get_task_workspace_operation(store, operation_id)
    operation["error_recorded"] = bool(operation.pop("error", None))
    path = Path(operation["destination_path"])
    try:
        is_symlink = path.is_symlink()
        exists = path.exists()
        is_directory = path.is_dir() if exists and not is_symlink else False
    except OSError:
        is_symlink, exists, is_directory = False, False, False
    operation["filesystem"] = {
        "path_exists": exists,
        "path_is_directory": is_directory,
        "path_is_symlink": is_symlink,
    }
    operation["recovery_guidance"] = (
        "Inspect the recorded destination and Git worktree metadata before taking action. "
        "Evo has not changed or removed any files."
        if operation["status"] in ("provisioning", "recovery_required")
        else None
    )
    return operation


DEFAULT_REVIEW_MAX_FILES = 100
DEFAULT_REVIEW_MAX_BYTES = 256 * 1024


def _quote_patch_path(path_text):
    """Quote unusual paths so filenames cannot inject patch headers."""
    escaped = []
    needs_quotes = False
    for char in path_text:
        code = ord(char)
        if char == "\\":
            escaped.append("\\\\")
            needs_quotes = True
        elif char == '"':
            escaped.append('\\"')
            needs_quotes = True
        elif char == "\t":
            escaped.append("\\t")
            needs_quotes = True
        elif char == "\n":
            escaped.append("\\n")
            needs_quotes = True
        elif char == "\r":
            escaped.append("\\r")
            needs_quotes = True
        elif code < 32 or code >= 127:
            escaped.append(f"\\{code:03o}")
            needs_quotes = True
        else:
            escaped.append(char)
    value = "".join(escaped)
    return '"' + value + '"' if needs_quotes else value


def _safe_relative_path(path_text):
    if not isinstance(path_text, str) or not path_text or "\x00" in path_text:
        return None
    if path_text.startswith("/") or path_text.startswith("\\"):
        return None
    parts = Path(path_text).parts
    if any(part in ("", ".", "..") for part in parts):
        return None
    candidate = Path(*parts)
    if candidate.is_absolute():
        return None
    return candidate


def _open_regular_file_at(root, relative_path):
    """Open a regular file beneath root without following any path symlink."""
    import stat
    required = ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")
    if any(not hasattr(os, flag) for flag in required) or os.open not in os.supports_dir_fd:
        raise OSError("safe descriptor-relative file access is unavailable")
    parts = Path(relative_path).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise OSError("unsafe relative path")
    directory_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    try:
        info = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
        os.close(fd)
        raise OSError("file is not a private regular file")
    return fd, info


def _stat_signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink)


def _untracked_signature(root, paths, max_total_bytes=64 * 1024 * 1024):
    import hashlib
    result = []
    consumed = 0
    for path in paths:
        try:
            fd, before = _open_regular_file_at(root, path)
            if before.st_size > max_total_bytes - consumed:
                os.close(fd)
                result.append((path, "over_budget", _stat_signature(before)))
                consumed = max_total_bytes
                continue
            digest = hashlib.sha256()
            over_budget = False
            try:
                remaining = max_total_bytes - consumed
                while True:
                    # Read at most one byte beyond the remaining allowance so
                    # a file that grows during hashing cannot evade the budget.
                    chunk = os.read(fd, min(65536, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        over_budget = True
                        consumed = max_total_bytes
                        break
                    consumed += len(chunk)
                    remaining -= len(chunk)
                    digest.update(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            if _stat_signature(before) != _stat_signature(after):
                result.append((path, "unstable"))
            elif over_budget:
                result.append((path, "over_budget", _stat_signature(after)))
            else:
                result.append((path, _stat_signature(after), digest.hexdigest()))
        except OSError:
            result.append((path, None))
    return tuple(result)


def get_task_workspace_review(
    store,
    operation_id,
    *,
    max_files=DEFAULT_REVIEW_MAX_FILES,
    max_bytes=DEFAULT_REVIEW_MAX_BYTES,
):
    """Return a bounded, read-only review artifact for a completed task workspace."""
    if isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1 or max_files > 1000:
        raise TaskWorkspaceValidationError("max_files must be a positive integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024 or max_bytes > 64 * 1024 * 1024:
        raise TaskWorkspaceValidationError("max_bytes must be at least 1024")
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

    review_deadline = __import__("time").monotonic() + 120.0

    def _review_git(*git_args, **kwargs):
        remaining = review_deadline - __import__("time").monotonic()
        if remaining <= 0:
            raise TaskWorkspaceProvisioningError("task workspace review deadline exceeded")
        kwargs["timeout"] = min(kwargs.get("timeout", 30), remaining)
        return _git(root, *git_args, **kwargs)

    head_before_truncated = []
    head_before = _review_git( "rev-parse", "--verify", "HEAD", max_output_bytes=4096, truncated=head_before_truncated, strip_output=True)
    status_before_truncated = []
    status_before = _review_git( "status", "--porcelain", "--untracked-files=all", max_output_bytes=max_bytes + 1024, truncated=status_before_truncated, strip_output=False)
    diff_before_truncated = []
    diff_before = _review_git( "diff", baseline, max_output_bytes=max_bytes + 1024, truncated=diff_before_truncated, strip_output=False)
    untracked_before_truncated = []
    untracked_before = _review_git( "ls-files", "--others", "--exclude-standard", "-z", max_output_bytes=max_bytes + 1024, truncated=untracked_before_truncated, strip_output=False)
    if head_before_truncated or status_before_truncated or diff_before_truncated or untracked_before_truncated:
        raise TaskWorkspaceProvisioningError("review metadata exceeded output budget")
    untracked_before_sig = _untracked_signature(root, [p for p in untracked_before.split("\x00") if p])

    changed = []  # list of (status, path, old_path)
    excluded = []
    unreadable = []
    metadata_count = 0
    changed_omitted = 0
    excluded_omitted = 0
    unreadable_omitted = 0

    def record_excluded(path):
        nonlocal metadata_count, excluded_omitted, truncated, truncation_reason
        if metadata_count < max_files:
            excluded.append(path)
            metadata_count += 1
        else:
            excluded_omitted += 1
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"

    def record_unreadable(path, reason):
        nonlocal metadata_count, unreadable_omitted, truncated, truncation_reason
        if metadata_count < max_files:
            unreadable.append({"path": path, "reason": reason})
            metadata_count += 1
        else:
            unreadable_omitted += 1
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"
    patch_parts = []
    total_bytes = 0
    truncated = bool(diff_before_truncated)
    truncation_reason = "output_limit" if diff_before_truncated else None
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

    # Tracked changes relative to the immutable baseline (NUL-delimited).
    name_status_truncated = []
    name_status = _review_git( "diff", "-z", "--name-status", "--no-renames", baseline, max_output_bytes=max_bytes + 1024, truncated=name_status_truncated, strip_output=False)
    if name_status_truncated:
        raise TaskWorkspaceProvisioningError("review metadata exceeded output budget")
    # Parse NUL-delimited pairs: status token then literal path.
    tokens = name_status.split("\x00")
    i = 0
    while i < len(tokens):
        token = tokens[i].strip()
        i += 1
        if not token:
            continue
        if i >= len(tokens):
            break
        path = tokens[i]
        i += 1
        rel = _safe_relative_path(path)
        if rel is None:
            record_unreadable(path, "unsafe_path")
            continue
        if _is_excluded(rel):
            record_excluded(path)
            continue
        candidate = root / rel
        cursor = root
        symlink = False
        for part in rel.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                symlink = True
                break
        if symlink or candidate.is_symlink():
            record_unreadable(path, "symlink")
            continue
        if metadata_count >= max_files:
            changed_omitted += 1
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"
            continue
        changed.append((token, str(rel), None))
        metadata_count += 1

    # Untracked files.
    untracked_truncated = []
    untracked_output = _review_git( "ls-files", "--others", "--exclude-standard", "-z", max_output_bytes=max_bytes + 1024, truncated=untracked_truncated, strip_output=False)
    if untracked_truncated:
        raise TaskWorkspaceProvisioningError("review metadata exceeded output budget")
    untracked_paths = [p for p in untracked_output.split("\x00") if p]
    for path in untracked_paths:
        rel = _safe_relative_path(path)
        if rel is None:
            record_unreadable(path, "unsafe_path")
            continue
        if _is_excluded(rel):
            record_excluded(path)
            continue
        candidate = root / rel
        cursor = root
        symlink = False
        for part in rel.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                symlink = True
                break
        if symlink or candidate.is_symlink():
            record_unreadable(path, "symlink")
            continue
        if not candidate.is_file():
            continue
        if metadata_count >= max_files:
            changed_omitted += 1
            truncated = True
            if truncation_reason is None:
                truncation_reason = "file_limit"
            continue
        # Expose untracked files as additions in the review contract while
        # retaining an internal marker so their contents are read directly
        # rather than passed to `git diff` (which cannot see untracked files).
        changed.append(("A", str(rel), "untracked"))
        metadata_count += 1

    # One literal-pathspec-scoped diff avoids per-file process overhead and pathspec magic.
    tracked_paths = [path for status, path, source_kind in changed if source_kind != "untracked"]
    if tracked_paths and not truncated:
        file_diff_truncated = []
        file_diff = _review_git(
            "diff", baseline, "--", *tracked_paths,
            max_output_bytes=max_bytes + 1024, truncated=file_diff_truncated, strip_output=False,
        )
        if file_diff_truncated:
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
        if file_diff and not add_text(file_diff):
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"

    # Include readable untracked file contents.
    for status, path, source_kind in changed:
        if source_kind != "untracked":
            continue
        if truncated and truncation_reason == "output_limit":
            break
        rel = _safe_relative_path(path)
        if rel is None:
            unreadable.append({"path": path, "reason": "unsafe_path"})
            continue
        candidate = root / rel
        # Read incrementally with strict byte budget.
        remaining = max_bytes - total_bytes
        if remaining <= 0:
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
            break
        per_file_cap = min(remaining, 65536)
        chunks = []
        read_total = 0
        binary = False
        try:
            fd, st_before = _open_regular_file_at(root, str(rel))
        except OSError:
            record_unreadable(path, "unsafe_or_unreadable")
            continue
        try:
            while read_total < per_file_cap:
                chunk = os.read(fd, min(8192, per_file_cap - read_total))
                if not chunk:
                    break
                chunks.append(chunk)
                read_total += len(chunk)
                if b"\x00" in chunk:
                    binary = True
                    break
            file_truncated = False
            if not binary and read_total == per_file_cap:
                file_truncated = bool(os.read(fd, 1))
            st_after = os.fstat(fd)
            if _stat_signature(st_before) != _stat_signature(st_after):
                record_unreadable(path, "changed_during_read")
                unstable = True
                continue
        except OSError:
            record_unreadable(path, "unreadable")
            continue
        finally:
            os.close(fd)
        data = b"".join(chunks)
        if binary:
            record_unreadable(path, "binary")
            continue
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            record_unreadable(path, "invalid_utf8")
            continue
        quoted_path = _quote_patch_path(path)
        entry = f"diff --git a/{quoted_path} b/{quoted_path}\nnew file mode {100755 if (st_before.st_mode & 0o111) else 100644}\n--- /dev/null\n+++ b/{quoted_path}\n"
        content_lines = text.splitlines()
        entry += "".join(f"+{line}\n" for line in content_lines)
        if text and not text.endswith(("\n", "\r")):
            entry += "\\ No newline at end of file\n"
        if file_truncated:
            entry += "\n[truncated]\n"
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
        if not add_text(entry):
            truncated = True
            if truncation_reason is None:
                truncation_reason = "output_limit"
            break

    head_after_truncated = []
    head_after = _review_git( "rev-parse", "--verify", "HEAD", max_output_bytes=4096, truncated=head_after_truncated, strip_output=True)
    status_after_truncated = []
    status_after = _review_git( "status", "--porcelain", "--untracked-files=all", max_output_bytes=max_bytes + 1024, truncated=status_after_truncated, strip_output=False)
    diff_after_truncated = []
    diff_after = _review_git( "diff", baseline, max_output_bytes=max_bytes + 1024, truncated=diff_after_truncated, strip_output=False)
    untracked_after_truncated = []
    untracked_after = _review_git( "ls-files", "--others", "--exclude-standard", "-z", max_output_bytes=max_bytes + 1024, truncated=untracked_after_truncated, strip_output=False)
    untracked_after_sig = _untracked_signature(root, [p for p in untracked_after.split("\x00") if p])
    metadata_truncated = bool(head_after_truncated or status_after_truncated or diff_after_truncated or untracked_after_truncated)
    if metadata_truncated:
        truncated = True
        if truncation_reason is None:
            truncation_reason = "output_limit"
    snapshot_stable = (
        not truncated
        and not metadata_truncated
        and head_before == head_after
        and status_before == status_after
        and diff_before == diff_after
        and untracked_before == untracked_after
        and untracked_before_sig == untracked_after_sig
        and all(len(item) >= 3 and item[1] not in (None, "unstable", "over_budget")
                for item in untracked_before_sig + untracked_after_sig)
    )
    if not snapshot_stable:
        unstable = True
        if truncation_reason is None:
            truncation_reason = "snapshot_unstable"

    # Include the bounded write journal so reviewers can distinguish edits
    # made through Evo's approval-gated editor from other workspace changes.
    from .task_workspace_files import list_task_workspace_file_changes
    file_change_history = list_task_workspace_file_changes(
        store, operation["operation_id"], limit=500,
    )
    file_change_status_counts = {
        status: sum(1 for item in file_change_history["items"] if item["status"] == status)
        for status in ("applied", "pending", "failed", "indeterminate")
    }
    file_change_summary = {
        "total": file_change_history["total"],
        **file_change_status_counts,
        "truncated": file_change_history["truncated"],
        "limit": file_change_history["limit"],
    }

    response = {
        "operation_id": operation["operation_id"],
        "status": "ok",
        "stable": snapshot_stable,
        "unstable": unstable,
        "source_revision": baseline,
        "current_head": head_after,
        "changed_files": [{"status": s, "path": p} for s, p, _ in changed],
        "changed_file_count": len(changed),
        "file_change_summary": file_change_summary,
        "file_change_history": file_change_history["items"],
        "excluded_files": sorted(set(excluded)),
        "excluded_files_omitted": excluded_omitted,
        "unreadable_files": unreadable,
        "unreadable_files_omitted": unreadable_omitted,
        "changed_files_omitted": changed_omitted,
        "patch": "".join(patch_parts),
        "patch_bytes": total_bytes,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "max_files": max_files,
        "max_bytes": max_bytes,
    }
    import json
    serialized_size = len(json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
    if serialized_size > max_bytes + 4 * 1024 * 1024:
        raise TaskWorkspaceProvisioningError("review response exceeded its serialized size budget")
    return response




def get_task_workspace_fingerprint(store, operation_id, *, max_files=25000, max_bytes=512 * 1024 * 1024, timeout_seconds=30):
    """Hash a bounded, read-only snapshot of every regular workspace file.

    Git metadata is excluded. Symlinks, special files, races, and budget
    exhaustion make the snapshot incomplete rather than silently omitting data.
    """
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 100000:
        raise TaskWorkspaceValidationError("max_files must be between 1 and 100000")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1024 <= max_bytes <= 2 * 1024 * 1024 * 1024:
        raise TaskWorkspaceValidationError("max_bytes must be between 1024 and 2 GiB")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 120:
        raise TaskWorkspaceValidationError("timeout_seconds must be between 1 and 120")
    operation = get_task_workspace_operation(store, operation_id)
    if operation["status"] != "completed":
        raise TaskWorkspaceValidationError("task workspace operation is not completed")
    binding = resolve_executable_workspace(store, operation["task_workspace_id"])
    if binding["checkout_id"] != operation["checkout_id"] or str(binding.path) != str(operation["destination_path"]):
        raise TaskWorkspaceValidationError("task workspace binding does not match its operation")
    root = Path(binding.path)
    deadline = time.monotonic() + timeout_seconds
    digest = hashlib.sha256()
    files = 0
    total_bytes = 0

    def add_record(value):
        digest.update(value.encode("utf-8", errors="surrogateescape"))
        digest.update(bytes([0]))

    def visit(directory_fd, relative):
        nonlocal files, total_bytes
        if time.monotonic() > deadline:
            raise TimeoutError("snapshot deadline exceeded")
        before_dir = os.fstat(directory_fd)
        if not stat.S_ISDIR(before_dir.st_mode):
            raise OSError("workspace directory changed type")
        with os.scandir(directory_fd) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not relative.parts and entry.name == ".git":
                if not stat.S_ISREG(info.st_mode):
                    raise OSError("task worktree Git metadata pointer is not a regular file")
                continue
            rel = (relative / entry.name) if relative else Path(entry.name)
            if stat.S_ISDIR(info.st_mode):
                add_record("D:" + rel.as_posix() + ":" + str(stat.S_IMODE(info.st_mode)))
                child_fd = os.open(
                    entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    visit(child_fd, rel)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                files += 1
                if files > max_files or info.st_size > max_bytes - total_bytes:
                    raise OverflowError("snapshot file or byte budget exceeded")
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                fd = os.open(entry.name, flags, dir_fd=directory_fd)
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise OSError("workspace file changed before hashing")
                    file_hash = hashlib.sha256()
                    read_bytes = 0
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError("snapshot deadline exceeded")
                        chunk = os.read(fd, 1024 * 1024)
                        if not chunk:
                            break
                        read_bytes += len(chunk)
                        if read_bytes > max_bytes - total_bytes:
                            raise OverflowError("snapshot byte budget exceeded")
                        file_hash.update(chunk)
                    after = os.fstat(fd)
                    signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_mode)
                    if signature(opened) != signature(after) or read_bytes != after.st_size:
                        raise OSError("workspace file changed while hashing")
                finally:
                    os.close(fd)
                total_bytes += read_bytes
                add_record("F:" + rel.as_posix() + ":" + str(stat.S_IMODE(after.st_mode)) + ":" + str(read_bytes) + ":" + file_hash.hexdigest())
            else:
                raise OSError("workspace contains a symlink or unsupported filesystem entry")
        after_dir = os.fstat(directory_fd)
        signature = lambda item: (item.st_dev, item.st_ino, item.st_mtime_ns, item.st_ctime_ns, item.st_mode)
        if signature(before_dir) != signature(after_dir):
            raise OSError("workspace directory changed while hashing")

    root_fd = None
    try:
        root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        visit(root_fd, Path())
    except (OSError, OverflowError, TimeoutError) as exc:
        return {"fingerprint": None, "complete": False, "file_count": files,
                "total_bytes": total_bytes, "reason": str(exc)[:240]}
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return {"fingerprint": digest.hexdigest(), "complete": True, "file_count": files,
            "total_bytes": total_bytes, "reason": None}



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
