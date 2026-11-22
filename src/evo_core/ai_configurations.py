import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from .store import utc_now

SENSITIVE_KEYS = {
    "api_key",
    "password",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "secret",
}
ALLOWED_TOP_LEVEL_KEYS = {"schema_version", "components", "extensions"}


class ConfigurationNotFoundError(Exception):
    pass


class ConfigurationValidationError(ValueError):
    pass


class ConfigurationConflictError(Exception):
    pass


class ConfigurationArchivedError(ConfigurationValidationError):
    pass


def _require_expected_version(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationValidationError("expected_version must be a positive integer")
    if value <= 0:
        raise ConfigurationValidationError("expected_version must be a positive integer")
    return value


def _require_text(value, field_name):
    if not isinstance(value, str):
        raise ConfigurationValidationError(f"{field_name} must be a string")
    return value


def _reject_non_finite(obj):
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ConfigurationValidationError("non-finite number is not allowed")
    elif isinstance(obj, dict):
        for value in obj.values():
            _reject_non_finite(value)
    elif isinstance(obj, list):
        for value in obj:
            _reject_non_finite(value)


def _validate_secret_reference(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationValidationError(f"{field_name} must be a non-empty string")
    return value


def _check_sensitive_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in SENSITIVE_KEYS:
                raise ConfigurationValidationError(f"sensitive credential field is not allowed: {key}")
            if key == "secret_ref":
                _validate_secret_reference(value, "secret_ref")
            elif key == "secret_refs":
                if not isinstance(value, dict):
                    raise ConfigurationValidationError("secret_refs must be an object")
                for ref_name, ref_value in value.items():
                    if not isinstance(ref_name, str) or not ref_name.strip():
                        raise ConfigurationValidationError("secret_refs keys must be non-empty strings")
                    _validate_secret_reference(ref_value, "secret_refs value")
            else:
                _check_sensitive_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            _check_sensitive_keys(value)


def _check_json_compatible(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        if isinstance(obj, float):
            if obj != obj or obj in (float("inf"), float("-inf")):
                raise ConfigurationValidationError("non-finite number is not allowed")
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ConfigurationValidationError("object keys must be strings")
            _check_json_compatible(value)
        return
    if isinstance(obj, list):
        for value in obj:
            _check_json_compatible(value)
        return
    raise ConfigurationValidationError("value is not JSON-compatible")


def _parse_json_text(text):
    if not isinstance(text, str):
        raise ConfigurationValidationError("definition must be a JSON object or mapping")
    try:
        parsed = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_duplicate_checking_pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationValidationError(f"invalid JSON definition: {exc}") from exc
    return parsed


def _reject_constant(value):
    raise ConfigurationValidationError(f"non-finite or unsupported constant: {value}")


def _duplicate_checking_pairs(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ConfigurationValidationError("duplicate JSON object keys are not allowed")
    return dict(pairs)


def _validate_mapping(value):
    if not isinstance(value, dict):
        raise ConfigurationValidationError("definition must be a JSON object")
    if "schema_version" not in value:
        raise ConfigurationValidationError("schema_version is required")
    if "components" not in value:
        raise ConfigurationValidationError("components is required")
    unknown = set(value) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigurationValidationError(f"unknown top-level keys: {sorted(unknown)}")
    schema_version = value["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ConfigurationValidationError("schema_version must be an integer")
    if schema_version != 1:
        raise ConfigurationValidationError("unsupported schema_version")
    components = value["components"]
    if not isinstance(components, dict):
        raise ConfigurationValidationError("components must be an object")
    for key, component_value in components.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigurationValidationError("component names must be non-empty strings")
        if not isinstance(component_value, dict):
            raise ConfigurationValidationError("component values must be objects")
    if "extensions" in value and value["extensions"] is not None:
        if not isinstance(value["extensions"], dict):
            raise ConfigurationValidationError("extensions must be an object")
    _reject_non_finite(value)
    _check_json_compatible(value)
    _check_sensitive_keys(value)
    return copy.deepcopy(value)


def validate_definition(value):
    if isinstance(value, str):
        parsed = _parse_json_text(value)
    elif isinstance(value, dict):
        parsed = value
    else:
        raise ConfigurationValidationError("definition must be a JSON object or mapping")
    normalized = _validate_mapping(parsed)
    # Ensure deep copy and JSON compatibility.
    canonical = canonical_json(normalized)
    return json.loads(canonical)


def canonical_json(definition):
    return json.dumps(definition, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(definition):
    return hashlib.sha256(canonical_json(definition).encode("utf-8")).hexdigest()


def _decode_row(row):
    if row is None:
        return None
    result = dict(row)
    if "definition_json" in result:
        result["definition"] = json.loads(result.pop("definition_json"))
    if "provenance_json" in result:
        result["provenance"] = json.loads(result.pop("provenance_json"))
    return result


def _fetch_configuration(store, configuration_id):
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
        ).fetchone()
    if row is None:
        raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
    return row


def _fetch_revision(store, configuration_id, revision_id):
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM ai_configuration_revisions WHERE configuration_id=? AND revision_id=?",
            (configuration_id, revision_id),
        ).fetchone()
    if row is None:
        raise ConfigurationNotFoundError(
            f"revision not found: {revision_id} for configuration {configuration_id}"
        )
    return row


def create_configuration(store, definition, *, name="", description="", change_summary=""):
    name = _require_text(name, "name")
    description = _require_text(description, "description")
    change_summary = _require_text(change_summary, "change_summary")
    validated = validate_definition(definition)
    canonical = canonical_json(validated)
    digest = content_hash(validated)
    configuration_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    now = utc_now()
    schema_version = validated["schema_version"]
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            store.db.execute(
                """INSERT INTO ai_configurations
                   (configuration_id, name, description, status, current_revision_id, created_at, updated_at, version)
                   VALUES (?, ?, ?, 'active', ?, ?, ?, 1)""",
                (configuration_id, name, description, revision_id, now, now),
            )
            store.db.execute(
                """INSERT INTO ai_configuration_revisions
                   (revision_id, configuration_id, revision_number, schema_version, definition_json,
                    content_hash, parent_revision_id, change_summary, created_at, provenance_json)
                   VALUES (?, ?, 1, ?, ?, ?, NULL, ?, ?, '{}')""",
                (revision_id, configuration_id, schema_version, canonical, digest, change_summary, now),
            )
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    configuration = _decode_row(
        store.db.execute(
            "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
        ).fetchone()
    )
    revision = _decode_row(
        store.db.execute(
            "SELECT * FROM ai_configuration_revisions WHERE configuration_id=? AND revision_id=?",
            (configuration_id, revision_id),
        ).fetchone()
    )
    return {"configuration": configuration, "revision": revision}


def get_configuration(store, configuration_id):
    with store.lock:
        row = _fetch_configuration(store, configuration_id)
        config = _decode_row(row)
        revision_row = store.db.execute(
            "SELECT * FROM ai_configuration_revisions WHERE configuration_id=? AND revision_id=?",
            (configuration_id, config["current_revision_id"]),
        ).fetchone()
        config["current_revision"] = _decode_row(revision_row)
    return config


def list_configurations(store, status=None):
    with store.lock:
        if status is not None:
            rows = store.db.execute(
                "SELECT * FROM ai_configurations WHERE status=? ORDER BY updated_at DESC, configuration_id ASC",
                (status,),
            ).fetchall()
        else:
            rows = store.db.execute(
                "SELECT * FROM ai_configurations ORDER BY updated_at DESC, configuration_id ASC"
            ).fetchall()
    return [_decode_row(row) for row in rows]


def get_revision(store, configuration_id, revision_id):
    with store.lock:
        row = _fetch_revision(store, configuration_id, revision_id)
    return _decode_row(row)


def list_revisions(store, configuration_id):
    with store.lock:
        _fetch_configuration(store, configuration_id)
        rows = store.db.execute(
            "SELECT * FROM ai_configuration_revisions WHERE configuration_id=? ORDER BY revision_number ASC",
            (configuration_id,),
        ).fetchall()
    return [_decode_row(row) for row in rows]


def create_revision(
    store,
    configuration_id,
    definition,
    *,
    expected_version,
    parent_revision_id=None,
    change_summary="",
    name=None,
    description=None,
):
    expected_version = _require_expected_version(expected_version)
    change_summary = _require_text(change_summary, "change_summary")
    if name is not None:
        name = _require_text(name, "name")
    if description is not None:
        description = _require_text(description, "description")
    validated = validate_definition(definition)
    canonical = canonical_json(validated)
    digest = content_hash(validated)
    schema_version = validated["schema_version"]
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            config_row = store.db.execute(
                "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
            ).fetchone()
            if config_row is None:
                raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
            config = dict(config_row)
            if config["status"] == "archived":
                raise ConfigurationArchivedError("cannot revise an archived configuration")
            if int(config["version"]) != expected_version:
                raise ConfigurationConflictError("stale configuration version")
            next_number = store.db.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM ai_configuration_revisions WHERE configuration_id=?",
                (configuration_id,),
            ).fetchone()[0]
            new_revision_id = str(uuid.uuid4())
            now = utc_now()
            actual_parent = config["current_revision_id"] if parent_revision_id is None else parent_revision_id
            if parent_revision_id is not None:
                parent_row = store.db.execute(
                    "SELECT 1 FROM ai_configuration_revisions WHERE configuration_id=? AND revision_id=?",
                    (configuration_id, parent_revision_id),
                ).fetchone()
                if parent_row is None:
                    raise ConfigurationValidationError("parent revision does not belong to this configuration")
            store.db.execute(
                """INSERT INTO ai_configuration_revisions
                   (revision_id, configuration_id, revision_number, schema_version, definition_json,
                    content_hash, parent_revision_id, change_summary, created_at, provenance_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
                (
                    new_revision_id,
                    configuration_id,
                    next_number,
                    schema_version,
                    canonical,
                    digest,
                    actual_parent,
                    change_summary,
                    now,
                ),
            )
            updates = {
                "current_revision_id": new_revision_id,
                "updated_at": now,
                "version": int(config["version"]) + 1,
            }
            if name is not None:
                updates["name"] = name
            if description is not None:
                updates["description"] = description
            assignments = ", ".join(f"{key}=?" for key in updates)
            values = [updates[key] for key in updates] + [configuration_id, config["version"]]
            cursor = store.db.execute(
                f"UPDATE ai_configurations SET {assignments} WHERE configuration_id=? AND version=?",
                values,
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("stale configuration version")
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    return get_revision(store, configuration_id, new_revision_id)


def restore_revision(
    store,
    configuration_id,
    revision_id,
    *,
    expected_version,
    change_summary="",
):
    expected_version = _require_expected_version(expected_version)
    change_summary = _require_text(change_summary, "change_summary")
    historical = _fetch_revision(store, configuration_id, revision_id)
    definition = json.loads(historical["definition_json"])
    validated = validate_definition(definition)
    canonical = canonical_json(validated)
    digest = content_hash(validated)
    schema_version = validated["schema_version"]
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            config_row = store.db.execute(
                "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
            ).fetchone()
            if config_row is None:
                raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
            config = dict(config_row)
            if config["status"] == "archived":
                raise ConfigurationArchivedError("cannot restore into an archived configuration")
            if int(config["version"]) != expected_version:
                raise ConfigurationConflictError("stale configuration version")
            next_number = store.db.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM ai_configuration_revisions WHERE configuration_id=?",
                (configuration_id,),
            ).fetchone()[0]
            new_revision_id = str(uuid.uuid4())
            now = utc_now()
            store.db.execute(
                """INSERT INTO ai_configuration_revisions
                   (revision_id, configuration_id, revision_number, schema_version, definition_json,
                    content_hash, parent_revision_id, change_summary, created_at, provenance_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
                (
                    new_revision_id,
                    configuration_id,
                    next_number,
                    schema_version,
                    canonical,
                    digest,
                    config["current_revision_id"],
                    change_summary or f"Restored from revision {revision_id}",
                    now,
                ),
            )
            cursor = store.db.execute(
                "UPDATE ai_configurations SET current_revision_id=?, updated_at=?, version=? WHERE configuration_id=? AND version=?",
                (new_revision_id, now, int(config["version"]) + 1, configuration_id, config["version"]),
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("stale configuration version")
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    return get_revision(store, configuration_id, new_revision_id)


def archive_configuration(store, configuration_id, *, expected_version):
    expected_version = _require_expected_version(expected_version)
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            config_row = store.db.execute(
                "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
            ).fetchone()
            if config_row is None:
                raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
            config = dict(config_row)
            if int(config["version"]) != expected_version:
                raise ConfigurationConflictError("stale configuration version")
            now = utc_now()
            cursor = store.db.execute(
                "UPDATE ai_configurations SET status='archived', updated_at=?, version=? WHERE configuration_id=? AND version=?",
                (now, int(config["version"]) + 1, configuration_id, config["version"]),
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("stale configuration version")
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    return get_configuration(store, configuration_id)


def reactivate_configuration(store, configuration_id, *, expected_version):
    expected_version = _require_expected_version(expected_version)
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            config_row = store.db.execute(
                "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
            ).fetchone()
            if config_row is None:
                raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
            config = dict(config_row)
            if int(config["version"]) != expected_version:
                raise ConfigurationConflictError("stale configuration version")
            now = utc_now()
            cursor = store.db.execute(
                "UPDATE ai_configurations SET status='active', updated_at=?, version=? WHERE configuration_id=? AND version=?",
                (now, int(config["version"]) + 1, configuration_id, config["version"]),
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("stale configuration version")
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    return get_configuration(store, configuration_id)


def update_configuration(store, configuration_id, updates, *, expected_version):
    expected_version = _require_expected_version(expected_version)
    if not isinstance(updates, dict):
        raise ConfigurationValidationError("updates must be an object")
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            config_row = store.db.execute(
                "SELECT * FROM ai_configurations WHERE configuration_id=?", (configuration_id,)
            ).fetchone()
            if config_row is None:
                raise ConfigurationNotFoundError(f"configuration not found: {configuration_id}")
            config = dict(config_row)
            if int(config["version"]) != expected_version:
                raise ConfigurationConflictError("stale configuration version")
            now = utc_now()
            assignments = []
            values = []
            if "name" in updates:
                if not isinstance(updates["name"], str):
                    raise ConfigurationValidationError("name must be a string")
                assignments.append("name=?")
                values.append(updates["name"])
            if "description" in updates:
                if not isinstance(updates["description"], str):
                    raise ConfigurationValidationError("description must be a string")
                assignments.append("description=?")
                values.append(updates["description"])
            if "status" in updates:
                status = updates["status"]
                if status not in ("active", "archived"):
                    raise ConfigurationValidationError("invalid status")
                assignments.append("status=?")
                values.append(status)
            if not assignments:
                raise ConfigurationValidationError("no mutable fields supplied")
            assignments.extend(["updated_at=?", "version=?"])
            values.extend([now, int(config["version"]) + 1, configuration_id, config["version"]])
            cursor = store.db.execute(
                f"UPDATE ai_configurations SET {', '.join(assignments)} WHERE configuration_id=? AND version=?",
                values,
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("stale configuration version")
            store.db.commit()
        except Exception:
            try:
                store.db.rollback()
            except Exception:
                pass
            raise
    return get_configuration(store, configuration_id)
