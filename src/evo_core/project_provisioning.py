import json
import os
import re
import shutil
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
    register_checkout,
    register_project,
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


def _run_git(target, *args):
    completed = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
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
    registry_created = False
    project_id = None
    checkout_id = None
    workspace_id = None
    try:
        try:
            os.mkdir(target)
        except FileExistsError as exc:
            raise ProvisioningConflictError("target directory already exists") from exc
        except OSError as exc:
            raise ProvisioningError(f"could not create project directory: {exc}") from exc
        created_directory = True
        _write_operation(store, operation_id, status="directory_created", canonical_path=str(target.resolve(strict=True)))

        # Recheck canonical path and overlap after creation to catch races.
        canonical_target = _canonical_directory(target)
        if canonical_target != str(target.resolve(strict=True)):
            raise ProvisioningError("created directory canonical path changed unexpectedly")
        for checkout in list_all_checkouts(store):
            if _paths_overlap(canonical_target, checkout["canonical_path"]):
                raise ProvisioningConflictError("created project path overlaps an already registered checkout")
        target = Path(canonical_target)

        _starter_files(target, name)
        _write_operation(store, operation_id, status="files_written", canonical_path=canonical_target)

        # Git is mandatory for a successful provision.
        if shutil.which("git") is None:
            raise ProvisioningError("git is not available")
        _run_git(target, "init")
        _run_git(target, "add", "-A")
        _run_git(
            target,
            "-c", "user.name=Evo",
            "-c", "user.email=evo@local.invalid",
            "commit", "-m", "Initial commit",
        )
        _write_operation(store, operation_id, status="git_committed", canonical_path=canonical_target)

        project = register_project(store, name, description=description)
        project_id = project["project_id"]
        checkout = register_checkout(store, project_id, target)
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
                shutil.rmtree(target)
                created_directory = False
            except OSError:
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
        pass


def get_provisioning_operation(store, operation_id):
    return _get_operation(store, operation_id)
