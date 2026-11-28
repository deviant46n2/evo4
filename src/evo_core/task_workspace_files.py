"""Bounded, read-only filesystem inspection for isolated task workspaces."""
import hashlib
import os
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from .store import utc_now

from .task_workspaces import (
    TaskWorkspaceValidationError,
    _open_regular_file_at,
    get_task_workspace_operation,
)
from .workspace import _is_excluded
from .workspaces import (
    WorkspaceNotFoundError,
    WorkspaceRelationshipError,
    resolve_executable_workspace,
)


DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
MAX_DIRECTORY_SCAN_ENTRIES = 10_000
DEFAULT_READ_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024
PENDING_WRITE_RECOVERY_AGE_SECONDS = 30


def _task_root(store, operation_id):
    operation = get_task_workspace_operation(store, operation_id)
    if operation["status"] != "completed":
        raise TaskWorkspaceValidationError(
            "task workspace is not completed and cannot be inspected"
        )
    if not operation.get("task_workspace_id") or not operation.get("checkout_id"):
        raise TaskWorkspaceValidationError("task workspace operation is incomplete")
    try:
        binding = resolve_executable_workspace(store, operation["task_workspace_id"])
    except (WorkspaceNotFoundError, WorkspaceRelationshipError) as exc:
        raise TaskWorkspaceValidationError("task workspace binding is unavailable") from exc
    if binding["checkout_id"] != operation["checkout_id"]:
        raise TaskWorkspaceValidationError("task workspace checkout does not match the operation")
    root = Path(binding.path)
    if str(root) != str(operation["destination_path"]):
        raise TaskWorkspaceValidationError("task workspace path does not match the recorded destination")
    if root.is_symlink() or not root.is_dir():
        raise TaskWorkspaceValidationError("task workspace destination is unavailable")
    return operation, root


def _relative_directory(value):
    if value in (None, ""):
        return PurePosixPath(".")
    if not isinstance(value, str) or "\x00" in value or "\\" in value or value.startswith("/"):
        raise TaskWorkspaceValidationError("path must be a relative POSIX path")
    raw_parts = value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise TaskWorkspaceValidationError("path must stay within the task workspace")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise TaskWorkspaceValidationError("path must stay within the task workspace")
    return path


def _open_directory_at(root, relative_path):
    required = ("O_NOFOLLOW", "O_DIRECTORY")
    if any(not hasattr(os, flag) for flag in required) or os.open not in os.supports_dir_fd:
        raise OSError("safe descriptor-relative directory access is unavailable")
    fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative_path.parts:
            if part == ".":
                continue
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def list_task_workspace_files(store, operation_id, *, path="", limit=DEFAULT_LIST_LIMIT):
    """List one directory level without following symlinks or reading file contents."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
        raise TaskWorkspaceValidationError("limit must be an integer between 1 and 500")
    relative = _relative_directory(path)
    operation, root = _task_root(store, operation_id)
    try:
        directory_fd = _open_directory_at(root, relative)
    except (OSError, ValueError) as exc:
        raise TaskWorkspaceValidationError("directory is unavailable or contains a symlink") from exc
    try:
        entries = []
        omitted = 0
        total = 0
        scanned = 0
        scan_truncated = False
        # os.listdir() materializes every name before the response limit can be
        # applied. Stream the directory and stop at a hard scan budget instead.
        with os.scandir(directory_fd) as directory_entries:
            for entry in directory_entries:
                if scanned >= MAX_DIRECTORY_SCAN_ENTRIES:
                    scan_truncated = True
                    break
                scanned += 1
                name = entry.name
                if name == ".git":
                    continue
                child = relative / name if str(relative) != "." else PurePosixPath(name)
                if _is_excluded(Path(str(child))):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    omitted += 1
                    continue
                if stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                elif stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                elif stat.S_ISREG(info.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries.append({
                    "name": name,
                    "path": str(child),
                    "kind": kind,
                    "size_bytes": info.st_size if kind == "file" else None,
                    "modified_at_ns": info.st_mtime_ns,
                })
                total += 1
        entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold(), item["name"]))
        return {
            "operation_id": operation["operation_id"],
            "source_revision": operation["source_revision"],
            "path": "" if str(relative) == "." else str(relative),
            "items": entries[:limit],
            "total": total,
            "total_exact": not scan_truncated,
            "scan_truncated": scan_truncated,
            "scan_limit": MAX_DIRECTORY_SCAN_ENTRIES,
            "omitted_unreadable": omitted,
            "truncated": total > limit or scan_truncated,
            "limit": limit,
        }
    finally:
        os.close(directory_fd)


def read_task_workspace_file(store, operation_id, path, *, max_bytes=DEFAULT_READ_BYTES):
    """Read a bounded UTF-8 regular file through no-follow descriptor traversal."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_READ_BYTES:
        raise TaskWorkspaceValidationError("max_bytes must be an integer between 1 and 1048576")
    relative = _relative_directory(path)
    if str(relative) == "." or _is_excluded(Path(str(relative))):
        raise TaskWorkspaceValidationError("file path is not readable")
    operation, root = _task_root(store, operation_id)
    try:
        fd, before = _open_regular_file_at(root, str(relative))
    except OSError as exc:
        raise TaskWorkspaceValidationError("file is unavailable, unsafe, or not a regular file") from exc
    try:
        if before.st_size > max_bytes:
            raise TaskWorkspaceValidationError("file exceeds the requested read limit")
        chunks = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise TaskWorkspaceValidationError("file changed during read; retry inspection")
        if len(data) > max_bytes:
            raise TaskWorkspaceValidationError("file exceeds the requested read limit")
        if b"\x00" in data:
            raise TaskWorkspaceValidationError("binary files are not available for text inspection")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise TaskWorkspaceValidationError("file is not valid UTF-8 text") from exc
        return {
            "operation_id": operation["operation_id"],
            "source_revision": operation["source_revision"],
            "path": str(relative),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content": text,
            "truncated": False,
            "max_bytes": max_bytes,
        }
    finally:
        os.close(fd)



def _ensure_file_change_table(store):
    with store.lock:
        store.db.execute(
            """CREATE TABLE IF NOT EXISTS task_workspace_file_changes (
                change_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL REFERENCES task_workspaces(operation_id)
                    ON DELETE RESTRICT,
                path TEXT NOT NULL,
                before_sha256 TEXT,
                after_sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        columns = {
            row["name"] for row in store.db.execute(
                "PRAGMA table_info(task_workspace_file_changes)"
            ).fetchall()
        }
        if "status" not in columns:
            store.db.execute(
                "ALTER TABLE task_workspace_file_changes "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'applied'"
            )
        if "error_code" not in columns:
            store.db.execute(
                "ALTER TABLE task_workspace_file_changes ADD COLUMN error_code TEXT"
            )
        if "finalized_at" not in columns:
            store.db.execute(
                "ALTER TABLE task_workspace_file_changes ADD COLUMN finalized_at TEXT"
            )
        store.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_workspace_file_changes_operation "
            "ON task_workspace_file_changes(operation_id, created_at, change_id)"
        )
        store.db.commit()


def _current_file_sha256(root, relative_path):
    """Read a bounded regular file without following links for journal recovery."""
    try:
        fd, before = _open_regular_file_at(root, relative_path)
    except FileNotFoundError:
        return None
    except OSError:
        return "unsafe"
    try:
        if before.st_size > MAX_READ_BYTES:
            return "unsafe"
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        signature_before = (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns, before.st_mode, before.st_nlink,
        )
        signature_after = (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns, after.st_mode, after.st_nlink,
        )
        if signature_before != signature_after:
            return "unsafe"
        return digest.hexdigest()
    finally:
        os.close(fd)


def _reconcile_pending_file_changes(store, operation, root):
    """Resolve interrupted write intents from the current file state when possible."""
    with store.lock:
        pending = store.db.execute(
            """SELECT change_id, path, before_sha256, after_sha256, created_at
               FROM task_workspace_file_changes
               WHERE operation_id=? AND status='pending'
               ORDER BY created_at, change_id LIMIT 500""",
            (operation["operation_id"],),
        ).fetchall()
    recovery_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=PENDING_WRITE_RECOVERY_AGE_SECONDS
    )
    for row in pending:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            created_at = recovery_cutoff - timedelta(seconds=1)
        if created_at > recovery_cutoff:
            continue
        current = _current_file_sha256(root, row["path"])
        if current == row["after_sha256"]:
            status, error_code = "applied", None
        elif current is None and row["before_sha256"] is None:
            status, error_code = "failed", "interrupted_before_create"
        elif current == row["before_sha256"]:
            status, error_code = "failed", "interrupted_before_apply"
        else:
            status, error_code = "indeterminate", "state_changed_after_interruption"
        with store.lock:
            store.db.execute(
                """UPDATE task_workspace_file_changes
                   SET status=?, error_code=?, finalized_at=?
                   WHERE change_id=? AND status='pending'""",
                (status, error_code, utc_now(), row["change_id"]),
            )
            store.db.commit()


def apply_task_workspace_file(
    store, operation_id, path, content, *, expected_sha256=None, overwrite=False, approved=False,
):
    """Atomically create or replace one bounded UTF-8 file after explicit approval.

    Existing editor updates require the SHA-256 observed by the caller,
    preventing stale contents from silently overwriting a newer version. A fresh
    approved agent overwrite may set overwrite=True; the current file signature
    is still checked immediately before atomic replacement. New files are created
    without replacing an existing entry.
    """
    if approved is not True:
        raise TaskWorkspaceValidationError("explicit approval is required to apply a file")
    if not isinstance(content, str):
        raise TaskWorkspaceValidationError("file content must be UTF-8 text")
    try:
        data = content.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise TaskWorkspaceValidationError("file content is not valid UTF-8") from exc
    if len(data) > MAX_READ_BYTES:
        raise TaskWorkspaceValidationError("file content must not exceed 1048576 UTF-8 bytes")
    if b"\x00" in data:
        raise TaskWorkspaceValidationError("NUL bytes are not allowed in text files")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
    ):
        raise TaskWorkspaceValidationError("expected_sha256 must be a lowercase SHA-256 digest")
    relative = _relative_directory(path)
    if str(relative) == "." or ".git" in relative.parts or _is_excluded(Path(str(relative))):
        raise TaskWorkspaceValidationError("file path is not writable")
    operation, root = _task_root(store, operation_id)
    parent = PurePosixPath(*relative.parts[:-1]) if len(relative.parts) > 1 else PurePosixPath(".")
    basename = relative.parts[-1]
    try:
        directory_fd = _open_directory_at(root, parent)
    except OSError as exc:
        raise TaskWorkspaceValidationError("parent directory is unavailable or contains a symlink") from exc

    temp_name = ".evo-write-" + uuid.uuid4().hex
    temp_fd = None
    original_signature = None
    before_sha256 = None
    filesystem_mutated = False
    mode = 0o644
    try:
        try:
            existing_fd, before = _open_regular_file_at(root, str(relative))
        except FileNotFoundError:
            existing_fd = None
            before = None
        except OSError as exc:
            raise TaskWorkspaceValidationError("target is unsafe or not a private regular file") from exc

        if before is None:
            if expected_sha256 is not None:
                raise TaskWorkspaceValidationError("file no longer exists; reload before applying")
        else:
            if expected_sha256 is None and overwrite is not True:
                os.close(existing_fd)
                raise TaskWorkspaceValidationError("file already exists; reload before applying")
            try:
                if before.st_size > MAX_READ_BYTES:
                    raise TaskWorkspaceValidationError("existing file exceeds the inspection limit")
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(existing_fd, 65536)
                    if not chunk:
                        break
                    digest.update(chunk)
                after = os.fstat(existing_fd)
                original_signature = (
                    before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns, before.st_mode,
                    before.st_nlink,
                )
                after_signature = (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns, after.st_mode,
                    after.st_nlink,
                )
                if original_signature != after_signature:
                    raise TaskWorkspaceValidationError("file changed during update check; reload before applying")
                before_sha256 = digest.hexdigest()
                if expected_sha256 is not None and before_sha256 != expected_sha256:
                    raise TaskWorkspaceValidationError("file changed since it was opened; reload before applying")
                mode = stat.S_IMODE(before.st_mode)
            finally:
                os.close(existing_fd)

        after_sha256 = hashlib.sha256(data).hexdigest()
        change_id = str(uuid.uuid4())
        created_at = utc_now()
        _ensure_file_change_table(store)
        with store.lock:
            store.db.execute(
                """INSERT INTO task_workspace_file_changes
                   (change_id, operation_id, path, before_sha256, after_sha256,
                    size_bytes, created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (change_id, operation["operation_id"], str(relative), before_sha256,
                 after_sha256, len(data), created_at),
            )
            store.db.commit()

        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=directory_fd,
        )
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None

        # Serialize the final compare-and-swap across processes using SQLite's
        # write lock. The pending intent was committed before filesystem mutation.
        with store.lock:
            store.db.execute("BEGIN IMMEDIATE")
            try:
                journal = store.db.execute(
                    "SELECT status FROM task_workspace_file_changes WHERE change_id=?",
                    (change_id,),
                ).fetchone()
                if journal is None or journal["status"] != "pending":
                    raise TaskWorkspaceValidationError(
                        "file write intent is no longer pending; reload before applying"
                    )
                # Recheck the destination immediately before the atomic directory
                # entry operation. Creation uses link(2), which cannot replace a name.
                try:
                    current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    current = None
                if before is None:
                    if current is not None:
                        raise TaskWorkspaceValidationError("file appeared during apply; reload before applying")
                    os.link(
                        temp_name, basename, src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd, follow_symlinks=False,
                    )
                    filesystem_mutated = True
                    os.unlink(temp_name, dir_fd=directory_fd)
                else:
                    if current is None or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                        raise TaskWorkspaceValidationError("target changed during apply; reload before applying")
                    current_signature = (
                        current.st_dev, current.st_ino, current.st_size,
                        current.st_mtime_ns, current.st_ctime_ns, current.st_mode,
                        current.st_nlink,
                    )
                    if current_signature != original_signature:
                        raise TaskWorkspaceValidationError("target changed during apply; reload before applying")
                    os.replace(
                        temp_name, basename, src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                    filesystem_mutated = True
                os.fsync(directory_fd)
                store.db.execute(
                    "UPDATE task_workspace_file_changes SET status='applied', finalized_at=? "
                    "WHERE change_id=? AND status='pending'",
                    (utc_now(), change_id),
                )
                store.db.commit()
            except BaseException:
                store.db.rollback()
                raise
    except TaskWorkspaceValidationError:
        if "change_id" in locals() and not filesystem_mutated:
            with store.lock:
                store.db.execute(
                    "UPDATE task_workspace_file_changes SET status='failed', "
                    "error_code='validation_failed', finalized_at=? "
                    "WHERE change_id=? AND status='pending'",
                    (utc_now(), change_id),
                )
                store.db.commit()
        raise
    except OSError as exc:
        if "change_id" in locals() and not filesystem_mutated:
            with store.lock:
                store.db.execute(
                    "UPDATE task_workspace_file_changes SET status='failed', "
                    "error_code='filesystem_error', finalized_at=? "
                    "WHERE change_id=? AND status='pending'",
                    (utc_now(), change_id),
                )
                store.db.commit()
        raise TaskWorkspaceValidationError("file could not be safely applied") from exc
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except OSError:
            pass
        os.close(directory_fd)

    return {
        "change_id": change_id,
        "operation_id": operation["operation_id"],
        "source_revision": operation["source_revision"],
        "path": str(relative),
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "size_bytes": len(data),
        "created_at": created_at,
        "status": "applied",
    }


def list_task_workspace_file_changes(store, operation_id, *, limit=100):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise TaskWorkspaceValidationError("limit must be an integer between 1 and 500")
    operation, root = _task_root(store, operation_id)
    _ensure_file_change_table(store)
    _reconcile_pending_file_changes(store, operation, root)
    with store.lock:
        total = store.db.execute(
            "SELECT COUNT(*) FROM task_workspace_file_changes WHERE operation_id=?",
            (operation["operation_id"],),
        ).fetchone()[0]
        rows = store.db.execute(
            """SELECT change_id, operation_id, path, before_sha256, after_sha256,
                      size_bytes, created_at, status, error_code, finalized_at
               FROM task_workspace_file_changes
               WHERE operation_id=? ORDER BY created_at DESC, change_id DESC LIMIT ?""",
            (operation["operation_id"], limit),
        ).fetchall()
    return {
        "operation_id": operation["operation_id"],
        "source_revision": operation["source_revision"],
        "items": [dict(row) for row in rows],
        "total": total,
        "truncated": total > limit,
        "limit": limit,
    }
