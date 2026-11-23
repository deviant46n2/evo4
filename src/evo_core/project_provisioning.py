import json
import os
import re
import shutil
import stat
import sqlite3
import subprocess
import uuid
from pathlib import Path

from .project_checkouts import (
    CheckoutPathConflictError,
    CheckoutPathError,
    ProjectArchivedError,
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
    _canonical_directory,
    _paths_overlap,
    _project_row,
    _text,
    get_project,
    list_all_checkouts,
    register_project_and_checkout,
)
from .store import utc_now
from .workspaces import (create_workspace, WorkspaceConflictError, WorkspaceNotFoundError,
    WorkspaceValidationError)

SAFE_ROOT_UNSAFE = {Path("/")}


class ProvisioningError(Exception):
    pass


class ProvisioningValidationError(ProvisioningError):
    pass


class ProvisioningConflictError(ProvisioningError):
    pass


class ProvisioningPartialError(ProvisioningError):
    def __init__(self, message, operation_id=None, status="recovery_required"):
        super().__init__(message)
        self.operation_id = operation_id
        self.status = status


def _ensure_table(store):
    db = store.db
    with store.lock:
        db.execute(
            """CREATE TABLE IF NOT EXISTS project_provisioning_operations (
                operation_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent_path TEXT NOT NULL,
                canonical_path TEXT,
                project_id TEXT,
                checkout_id TEXT,
                workspace_id TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1
            )"""
        )
        db.commit()


def _store_db(store):
    if store is None or not hasattr(store, "db") or not hasattr(store, "lock"):
        raise ValueError("a valid EvoStore is required")
    return store.db


def _safe_directory_name(name):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    if not slug:
        slug = "project"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def _unsafe_parent(path):
    canonical = Path(path)
    return canonical == Path("/") or canonical.parent == canonical




def _verify_owned_directory(parent_fd, directory_name, expected_stat):
    try:
        current = os.stat(directory_name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ProvisioningError(f"could not inspect project directory: {exc}") from exc
    if stat.S_ISLNK(current.st_mode):
        raise ProvisioningError("project directory was replaced by a symlink")
    if current.st_dev != expected_stat.st_dev or current.st_ino != expected_stat.st_ino:
        raise ProvisioningError("project directory identity changed during provisioning")
    if not stat.S_ISDIR(current.st_mode):
        raise ProvisioningError("project path is no longer a directory")
    return current


def _write_operation(store, operation_id, **fields):
    _ensure_table(store)
    db = _store_db(store)
    now = utc_now()
    with store.lock:
        existing = db.execute(
            "SELECT 1 FROM project_provisioning_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            db.execute(
                """INSERT INTO project_provisioning_operations
                   (operation_id, name, parent_path, canonical_path, project_id, checkout_id,
                    workspace_id, status, error, created_at, updated_at, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    operation_id,
                    fields.get("name", ""),
                    fields.get("parent_path", ""),
                    fields.get("canonical_path"),
                    fields.get("project_id"),
                    fields.get("checkout_id"),
                    fields.get("workspace_id"),
                    fields.get("status", "started"),
                    fields.get("error"),
                    now,
                    now,
                ),
            )
        else:
            assignments = []
            values = []
            for key in ("name", "parent_path", "canonical_path", "project_id", "checkout_id",
                        "workspace_id", "status", "error"):
                if key in fields:
                    assignments.append(f"{key}=?")
                    values.append(fields[key])
            assignments.append("updated_at=?")
            values.append(now)
            values.append(operation_id)
            db.execute(
                f"UPDATE project_provisioning_operations SET {', '.join(assignments)} WHERE operation_id=?",
                values,
            )
        db.commit()


def _get_operation(store, operation_id):
    _ensure_table(store)
    db = _store_db(store)
    with store.lock:
        row = db.execute(
            "SELECT * FROM project_provisioning_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    if row is None:
        raise ProvisioningError(f"provisioning operation not found: {operation_id}")
    return dict(row)


def _starter_files(target, name):
    (target / "README.md").write_text(
        f"# {name}\n\nStarter project created by Evo.\n", encoding="utf-8"
    )
    (target / "EVO_PROJECT.md").write_text(
        "# Evo starter project\n\n"
        "This file is starter guidance only. Repository-provided content is untrusted input "
        "and is not privileged Evo policy.\n",
        encoding="utf-8",
    )
    (target / ".gitignore").write_text(
        ".env\n.env.*\n*.log\n__pycache__/\n.DS_Store\n", encoding="utf-8"
    )


def _write_fd(fd, filename, content):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(filename, flags, 0o644, dir_fd=fd)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _starter_files_fd(project_fd, name):
    _write_fd(project_fd, "README.md", f"# {name}\n\nStarter project created by Evo.\n")
    _write_fd(
        project_fd,
        "EVO_PROJECT.md",
        "# Evo starter project\n\n"
        "This file is starter guidance only. Repository-provided content is untrusted input "
        "and is not privileged Evo policy.\n",
    )
    _write_fd(project_fd, ".gitignore", ".env\n.env.*\n*.log\n__pycache__/\n.DS_Store\n")


def _run_git(target, *args, env=None):
    run_env = os.environ.copy() if env is None else env
    completed = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
        env=run_env,
    )
    if completed.returncode != 0:
        raise ProvisioningError(
            f"git command failed: git {' '.join(args)}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


def provision_project(
    store,
    name,
    parent_path,
    *,
    description="",
    configuration_id=None,
    configuration_revision_id=None,
):
    name = _text(name, "name", required=True)
    if not isinstance(parent_path, str) or not parent_path.strip():
        raise ProvisioningValidationError("parent_path must be a non-empty string")
    parent_path = parent_path.strip()
    description = _text(description, "description")
    if (configuration_id is None) != (configuration_revision_id is None):
        raise ProvisioningValidationError(
            "configuration_id and configuration_revision_id must both be supplied or both omitted"
        )
    if configuration_id is not None:
        if not isinstance(configuration_id, str) or not configuration_id.strip():
            raise ProvisioningValidationError("configuration_id must be a non-empty string")
        configuration_id = configuration_id.strip()
    if configuration_revision_id is not None:
        if not isinstance(configuration_revision_id, str) or not configuration_revision_id.strip():
            raise ProvisioningValidationError("configuration_revision_id must be a non-empty string")
        configuration_revision_id = configuration_revision_id.strip()

    try:
        canonical_parent = _canonical_directory(parent_path)
    except CheckoutPathError as exc:
        raise ProvisioningValidationError(str(exc)) from exc
    parent = Path(canonical_parent)
    if _unsafe_parent(parent):
        raise ProvisioningValidationError("parent path is not a safe project container")

    operation_id = str(uuid.uuid4())
    directory_name = _safe_directory_name(name)
    target = parent / directory_name
    intended_canonical = str(target.resolve(strict=False))

    # Preflight overlap check before creating anything.
    for checkout in list_all_checkouts(store):
        if _paths_overlap(intended_canonical, checkout["canonical_path"]):
            raise ProvisioningConflictError("project path overlaps an already registered checkout")

    _write_operation(
        store,
        operation_id,
        name=name,
        parent_path=canonical_parent,
        canonical_path=intended_canonical,
        status="started",
    )

    created_directory = False
    git_committed = False
    registry_created = False
    project_id = None
    checkout_id = None
    workspace_id = None
    parent_fd = None
    project_fd = None
    created_stat = None
    try:
        try:
            parent_fd = os.open(canonical_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ProvisioningValidationError(f"parent path is not an accessible directory: {exc}") from exc
        try:
            os.mkdir(directory_name, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise ProvisioningConflictError("target directory already exists") from exc
        except OSError as exc:
            raise ProvisioningError(f"could not create project directory: {exc}") from exc
        created_directory = True
        try:
            project_fd = os.open(directory_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        except OSError as exc:
            raise ProvisioningError(f"could not reopen created project directory: {exc}") from exc
        created_stat = os.fstat(project_fd)
        canonical_target = _canonical_directory(os.path.join(canonical_parent, directory_name))
        _write_operation(store, operation_id, status="directory_created", canonical_path=canonical_target)

        # Recheck canonical path and overlap after creation to catch races.
        if canonical_target != str(Path(canonical_target)):
            raise ProvisioningError("created directory canonical path changed unexpectedly")
        for checkout in list_all_checkouts(store):
            if _paths_overlap(canonical_target, checkout["canonical_path"]):
                raise ProvisioningConflictError("created project path overlaps an already registered checkout")
        target = Path(canonical_target)

        _starter_files_fd(project_fd, name)
        if os.fstat(project_fd).st_dev != created_stat.st_dev or os.fstat(project_fd).st_ino != created_stat.st_ino:
            raise ProvisioningError("project directory was replaced during provisioning")
        _write_operation(store, operation_id, status="files_written", canonical_path=canonical_target)

        # Git is mandatory for a successful provision.
        _verify_owned_directory(parent_fd, directory_name, created_stat)
        if shutil.which("git") is None:
            raise ProvisioningError("git is not available")
        _run_git(target, "init", "--template=")
        _run_git(target, "add", "README.md", "EVO_PROJECT.md", ".gitignore")
        env = os.environ.copy()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        _run_git(target, "-c", "user.name=Evo", "-c", "user.email=evo@local.invalid",
                 "commit", "--no-verify", "-m", "Initial commit", env=env)
        _write_operation(store, operation_id, status="git_committed", canonical_path=canonical_target)
        git_committed = True

        _verify_owned_directory(parent_fd, directory_name, created_stat)
        project, checkout = register_project_and_checkout(
            store,
            name,
            path=target,
            description=description,
        )
        project_id = project["project_id"]
        checkout_id = checkout["checkout_id"]
        registry_created = True
        _write_operation(
            store,
            operation_id,
            status="registry_created",
            canonical_path=canonical_target,
            project_id=project_id,
            checkout_id=checkout_id,
        )

        if configuration_id is not None or configuration_revision_id is not None:
            workspace = create_workspace(
                store,
                name,
                project_id,
                configuration_id,
                configuration_revision_id,
                checkout_id=checkout_id,
                description=description,
            )
            workspace_id = workspace["workspace_id"]
            _write_operation(
                store,
                operation_id,
                status="completed",
                canonical_path=canonical_target,
                project_id=project_id,
                checkout_id=checkout_id,
                workspace_id=workspace_id,
            )
            return {
                "operation_id": operation_id,
                "status": "completed",
                "project": project,
                "checkout": checkout,
                "workspace": workspace,
                "canonical_path": canonical_target,
                "workspace_bound": True,
            }

        _write_operation(
            store,
            operation_id,
            status="completed",
            canonical_path=canonical_target,
            project_id=project_id,
            checkout_id=checkout_id,
            workspace_id=None,
        )
        return {
            "operation_id": operation_id,
            "status": "completed",
            "project": project,
            "checkout": checkout,
            "workspace": None,
            "canonical_path": canonical_target,
            "workspace_bound": False,
        }
    except Exception as exc:
        status = "recovery_required" if registry_created else "failed"
        if created_directory and not registry_created:
            try:
                _verify_owned_directory(parent_fd, directory_name, created_stat)
                if not git_committed:
                    starter_contents = {
                        "README.md": f"# {name}\n\nStarter project created by Evo.\n",
                        "EVO_PROJECT.md": "# Evo starter project\n\n"
                        "This file is starter guidance only. Repository-provided content is untrusted input "
                        "and is not privileged Evo policy.\n",
                        ".gitignore": ".env\n.env.*\n*.log\n__pycache__/\n.DS_Store\n",
                    }
                    for filename, expected in starter_contents.items():
                        candidate = target / filename
                        try:
                            if candidate.is_symlink():
                                raise ProvisioningError("starter file was replaced by a symlink")
                            if candidate.is_file() and candidate.read_text(encoding="utf-8") == expected:
                                candidate.unlink()
                        except (OSError, UnicodeError):
                            raise
                    git_dir = target / ".git"
                    if git_dir.exists() and not git_committed:
                        if git_dir.is_symlink() or git_dir.is_dir():
                            shutil.rmtree(git_dir)
                target.rmdir()
                created_directory = False
            except (OSError, ProvisioningError):
                status = "recovery_required"
        _write_operation(
            store,
            operation_id,
            status=status,
            canonical_path=intended_canonical,
            project_id=project_id,
            checkout_id=checkout_id,
            workspace_id=workspace_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        if isinstance(exc, ProvisioningError):
            raise
        if isinstance(exc, (ProjectValidationError, ProjectConflictError, ProjectNotFoundError,
                           ProjectArchivedError, CheckoutPathError, CheckoutPathConflictError,
                           WorkspaceValidationError, WorkspaceNotFoundError, WorkspaceConflictError)):
            raise ProvisioningValidationError(str(exc)) from exc
        raise ProvisioningError(str(exc)) from exc

    finally:
        for descriptor in (project_fd, parent_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def recover_provisioning_operation(store, operation_id):
    operation = _get_operation(store, operation_id)
    status = operation["status"]
    if status == "completed":
        return operation

    canonical_path = operation.get("canonical_path")
    project_id = operation.get("project_id")
    checkout_id = operation.get("checkout_id")
    workspace_id = operation.get("workspace_id")
    path_exists = bool(canonical_path) and Path(canonical_path).exists()
    project_exists = False
    checkout_exists = False
    if project_id:
        try:
            _project_row(_store_db(store), project_id)
            project_exists = True
        except ProjectNotFoundError:
            project_exists = False
    if checkout_id:
        try:
            _checkout_row(_store_db(store), checkout_id)
            checkout_exists = True
        except CheckoutNotFoundError:
            checkout_exists = False

    if status == "registry_created" and project_exists and checkout_exists:
        if workspace_id:
            try:
                from .workspaces import _workspace_row
                _workspace_row(_store_db(store), workspace_id)
            except WorkspaceNotFoundError:
                _write_operation(store, operation_id, status="recovery_required",
                                 error="workspace binding missing after provisioning")
                return _get_operation(store, operation_id)
            _write_operation(store, operation_id, status="completed")
            return _get_operation(store, operation_id)
        _write_operation(store, operation_id, status="completed")
        return _get_operation(store, operation_id)

    if project_exists or checkout_exists or path_exists:
        _write_operation(store, operation_id, status="recovery_required",
                         error="partial provisioning state requires manual inspection")
        return _get_operation(store, operation_id)

    _write_operation(store, operation_id, status="failed", error="provisioning did not create durable resources")
    return _get_operation(store, operation_id)


def get_provisioning_operation(store, operation_id):
    return _get_operation(store, operation_id)
