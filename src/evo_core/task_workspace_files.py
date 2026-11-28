"""Bounded, read-only filesystem inspection for isolated task workspaces."""
import os
import stat
from pathlib import Path, PurePosixPath

from .task_workspaces import (
    TaskWorkspaceValidationError,
    _is_excluded,
    _open_regular_file_at,
    get_task_workspace_operation,
)
from .workspaces import resolve_executable_workspace


DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
DEFAULT_READ_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024


def _task_root(store, operation_id):
    operation = get_task_workspace_operation(store, operation_id)
    if operation["status"] != "completed":
        raise TaskWorkspaceValidationError(
            "task workspace is not completed and cannot be inspected"
        )
    if not operation.get("task_workspace_id") or not operation.get("checkout_id"):
        raise TaskWorkspaceValidationError("task workspace operation is incomplete")
    binding = resolve_executable_workspace(store, operation["task_workspace_id"])
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
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise TaskWorkspaceValidationError("path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
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
        names = os.listdir(directory_fd)
        entries = []
        omitted = 0
        for name in names:
            if name == ".git":
                continue
            child = relative / name if str(relative) != "." else PurePosixPath(name)
            if _is_excluded(Path(str(child))):
                continue
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
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
        entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold(), item["name"]))
        total = len(entries)
        return {
            "operation_id": operation["operation_id"],
            "source_revision": operation["source_revision"],
            "path": "" if str(relative) == "." else str(relative),
            "items": entries[:limit],
            "total": total,
            "omitted_unreadable": omitted,
            "truncated": total > limit,
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
            "content": text,
            "truncated": False,
            "max_bytes": max_bytes,
        }
    finally:
        os.close(fd)
