import os
import sqlite3
import stat
import uuid
from pathlib import Path

from .store import utc_now


class ProjectNotFoundError(Exception):
    pass


class CheckoutNotFoundError(Exception):
    pass


class ProjectValidationError(ValueError):
    pass


class ProjectConflictError(Exception):
    pass


class ProjectArchivedError(ProjectValidationError):
    pass


class CheckoutPathError(ProjectValidationError):
    pass


class CheckoutPathConflictError(ProjectConflictError):
    pass


class CheckoutInUseError(ProjectConflictError):
    pass


def _expected_version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectValidationError("expected_version must be a positive integer")
    return value


def _text(value, field, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ProjectValidationError(f"{field} must be a string")
    if required and not value.strip():
        raise ProjectValidationError(f"{field} must not be empty")
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


def _project_row(db, project_id):
    row = db.execute(
        "SELECT * FROM software_projects WHERE project_id=?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return dict(row)


def _checkout_row(db, checkout_id):
    row = db.execute(
        "SELECT * FROM project_checkouts WHERE checkout_id=?",
        (checkout_id,),
    ).fetchone()
    if row is None:
        raise CheckoutNotFoundError(f"checkout not found: {checkout_id}")
    return dict(row)


def _canonical_directory(path):
    if not isinstance(path, (str, os.PathLike)):
        raise CheckoutPathError("checkout path must be a filesystem path")
    if isinstance(path, str) and not path.strip():
        raise CheckoutPathError("checkout path must not be empty")
    try:
        supplied = Path(path).expanduser()
        if not str(supplied).strip():
            raise CheckoutPathError("checkout path must not be empty")
        canonical = supplied.resolve(strict=True)
        if not stat.S_ISDIR(canonical.stat().st_mode):
            raise CheckoutPathError("checkout path must identify a directory")
        with os.scandir(canonical) as entries:
            next(entries, None)
        return str(canonical)
    except CheckoutPathError:
        raise
    except FileNotFoundError as exc:
        raise CheckoutPathError("checkout directory does not exist") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise CheckoutPathError(f"checkout directory cannot be validated: {exc}") from exc


def _availability(path):
    try:
        target = Path(path)
        info = target.stat()
        if not stat.S_ISDIR(info.st_mode):
            return "unavailable"
        with os.scandir(target) as entries:
            next(entries, None)
        return "available"
    except FileNotFoundError:
        return "missing"
    except (OSError, RuntimeError, ValueError):
        return "unavailable"


def register_project(
    store,
    name,
    *,
    description="",
    git_remote=None,
    default_ref=None,
    project_type=None,
):
    name = _text(name, "name", required=True)
    description = _text(description, "description")
    git_remote = _text(git_remote, "git_remote")
    default_ref = _text(default_ref, "default_ref")
    project_type = _text(project_type, "project_type")
    project_id = str(uuid.uuid4())
    now = utc_now()

    def operation(db):
        db.execute(
            """INSERT INTO software_projects
               (project_id, name, description, git_remote, default_ref,
                project_type, status, created_at, updated_at, version)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 1)""",
            (project_id, name, description, git_remote, default_ref,
             project_type, now, now),
        )
        return _project_row(db, project_id)

    return _write(store, operation)


def get_project(store, project_id):
    return _read(store, lambda db: _project_row(db, project_id))


def list_projects(store, status=None):
    if status is not None and status not in {"active", "archived"}:
        raise ProjectValidationError("status must be active or archived")
    def operation(db):
        if status is None:
            rows = db.execute(
                "SELECT * FROM software_projects ORDER BY updated_at DESC, project_id",
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM software_projects WHERE status=? ORDER BY updated_at DESC, project_id",
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]
    return _read(store, operation)


def update_project(store, project_id, updates, *, expected_version):
    expected_version = _expected_version(expected_version)
    if not isinstance(updates, dict):
        raise ProjectValidationError("updates must be an object")
    allowed = {"name", "description", "git_remote", "default_ref", "project_type"}
    unknown = set(updates) - allowed
    if unknown:
        raise ProjectValidationError(f"unsupported project fields: {sorted(unknown)}")
    if not updates:
        raise ProjectValidationError("no mutable fields supplied")

    normalized = {}
    for field, value in updates.items():
        if field == "name":
            normalized[field] = _text(value, field, required=True)
        else:
            normalized[field] = _text(value, field)

    def operation(db):
        project = _project_row(db, project_id)
        if project["version"] != expected_version:
            raise ProjectConflictError("stale project version")
        assignments = [f"{field}=?" for field in normalized]
        values = list(normalized.values())
        now = utc_now()
        assignments.extend(["updated_at=?", "version=?"])
        values.extend([now, expected_version + 1, project_id, expected_version])
        cursor = db.execute(
            f"UPDATE software_projects SET {', '.join(assignments)} "
            "WHERE project_id=? AND version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("stale project version")
        return _project_row(db, project_id)

    return _write(store, operation)


def _set_project_status(store, project_id, expected_version, status):
    expected_version = _expected_version(expected_version)

    def operation(db):
        project = _project_row(db, project_id)
        if project["version"] != expected_version:
            raise ProjectConflictError("stale project version")
        now = utc_now()
        cursor = db.execute(
            """UPDATE software_projects
               SET status=?, updated_at=?, version=?
               WHERE project_id=? AND version=?""",
            (status, now, expected_version + 1, project_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("stale project version")
        return _project_row(db, project_id)

    return _write(store, operation)


def archive_project(store, project_id, *, expected_version):
    return _set_project_status(store, project_id, expected_version, "archived")


def reactivate_project(store, project_id, *, expected_version):
    return _set_project_status(store, project_id, expected_version, "active")


def register_checkout(
    store,
    project_id,
    path,
    *,
    branch_or_ref=None,
    last_known_commit=None,
):
    canonical_path = _canonical_directory(path)
    branch_or_ref = _text(branch_or_ref, "branch_or_ref")
    last_known_commit = _text(last_known_commit, "last_known_commit")
    checkout_id = str(uuid.uuid4())
    now = utc_now()

    def operation(db):
        project = _project_row(db, project_id)
        if project["status"] != "active":
            raise ProjectArchivedError("cannot register a checkout to an archived project")
        try:
            db.execute(
                """INSERT INTO project_checkouts
                   (checkout_id, project_id, canonical_path, branch_or_ref,
                    last_known_commit, availability_status, created_at, updated_at, version)
                   VALUES (?, ?, ?, ?, ?, 'available', ?, ?, 1)""",
                (checkout_id, project_id, canonical_path, branch_or_ref,
                 last_known_commit, now, now),
            )
        except sqlite3.IntegrityError as exc:
            if "canonical_path" in str(exc).lower() or "unique" in str(exc).lower():
                raise CheckoutPathConflictError(
                    "a checkout is already registered at this canonical path"
                ) from exc
            raise
        return _checkout_row(db, checkout_id)

    return _write(store, operation)


def get_checkout(store, checkout_id):
    return _read(store, lambda db: _checkout_row(db, checkout_id))


def list_checkouts(store, project_id):
    def operation(db):
        _project_row(db, project_id)
        rows = db.execute(
            """SELECT * FROM project_checkouts
               WHERE project_id=? ORDER BY created_at, checkout_id""",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    return _read(store, operation)


def update_checkout(store, checkout_id, updates, *, expected_version):
    expected_version = _expected_version(expected_version)
    if not isinstance(updates, dict):
        raise ProjectValidationError("updates must be an object")
    allowed = {"branch_or_ref", "last_known_commit"}
    unknown = set(updates) - allowed
    if unknown:
        raise ProjectValidationError(f"unsupported checkout fields: {sorted(unknown)}")
    if not updates:
        raise ProjectValidationError("no mutable fields supplied")
    normalized = {
        field: _text(value, field)
        for field, value in updates.items()
    }

    def operation(db):
        checkout = _checkout_row(db, checkout_id)
        if checkout["version"] != expected_version:
            raise ProjectConflictError("stale checkout version")
        assignments = [f"{field}=?" for field in normalized]
        values = list(normalized.values())
        now = utc_now()
        assignments.extend(["updated_at=?", "version=?"])
        values.extend([now, expected_version + 1, checkout_id, expected_version])
        cursor = db.execute(
            f"UPDATE project_checkouts SET {', '.join(assignments)} "
            "WHERE checkout_id=? AND version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("stale checkout version")
        return _checkout_row(db, checkout_id)

    return _write(store, operation)


def refresh_checkout_availability(store, checkout_id):
    def operation(db):
        checkout = _checkout_row(db, checkout_id)
        status = _availability(checkout["canonical_path"])
        if status == checkout["availability_status"]:
            return checkout
        now = utc_now()
        db.execute(
            """UPDATE project_checkouts
               SET availability_status=?, updated_at=?, version=version+1
               WHERE checkout_id=?""",
            (status, now, checkout_id),
        )
        return _checkout_row(db, checkout_id)

    return _write(store, operation)


def unregister_checkout(store, checkout_id, *, expected_version):
    expected_version = _expected_version(expected_version)

    def operation(db):
        checkout = _checkout_row(db, checkout_id)
        if checkout["version"] != expected_version:
            raise ProjectConflictError("stale checkout version")
        references = db.execute(
            "SELECT 1 FROM workspaces WHERE checkout_id=? LIMIT 1",
            (checkout_id,),
        ).fetchone()
        if references is not None:
            raise CheckoutInUseError("checkout is referenced by a workspace")
        cursor = db.execute(
            "DELETE FROM project_checkouts WHERE checkout_id=? AND version=?",
            (checkout_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("stale checkout version")
        return {"checkout_id": checkout_id, "unregistered": True}

    return _write(store, operation)
