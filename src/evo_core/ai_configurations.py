import copy
import hashlib
import json
import sqlite3
import threading
import uuid
import ipaddress
import re
from urllib.parse import urlsplit
from datetime import datetime, timezone

from .store import utc_now
from .participant_contracts import UnsupportedAdapterError, resolve_adapter_contract

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


def _schema2_text(value, field_name, *, maximum=4096, allow_empty=False):
    if not isinstance(value, str):
        raise ConfigurationValidationError(f"{field_name} must be a string")
    if (not allow_empty and not value.strip()) or len(value) > maximum or "\x00" in value:
        raise ConfigurationValidationError(f"{field_name} is empty or outside its length limit")
    return value


def _schema2_int(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigurationValidationError(
            f"{field_name} must be an integer from {minimum} through {maximum}"
        )
    return value


def _schema2_number(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationValidationError(f"{field_name} must be a number")
    if not minimum <= value <= maximum:
        raise ConfigurationValidationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return value


def _schema2_endpoint(value):
    endpoint = _schema2_text(value, "model.settings.endpoint", maximum=2048)
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationValidationError("model.settings.endpoint is malformed") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in endpoint
        or "#" in endpoint
        or parsed.query
        or parsed.fragment
        or "%" in hostname
        or parsed.path not in {"", "/", "/v1"}
    ):
        raise ConfigurationValidationError("model.settings.endpoint violates endpoint URL policy")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationValidationError("model.settings.endpoint port is invalid")
    try:
        address = ipaddress.ip_address(hostname)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        is_loopback = address.is_loopback
    except ValueError:
        is_loopback = hostname.rstrip(".").lower() == "localhost"
        try:
            normalized_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ConfigurationValidationError("model.settings.endpoint hostname is invalid") from exc
        labels = normalized_host.split(".")
        if (
            len(normalized_host) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise ConfigurationValidationError("model.settings.endpoint hostname is invalid")
    if parsed.scheme == "http" and not is_loopback:
        raise ConfigurationValidationError("non-loopback provider endpoints must use HTTPS")
    return endpoint


def _schema2_argv_prefixes(value):
    if not isinstance(value, list) or len(value) > 128:
        raise ConfigurationValidationError("command_policy.settings.allowed_commands must be a bounded list")
    normalized = []
    total_chars = 0
    for index, prefix in enumerate(value):
        if not isinstance(prefix, list) or not prefix or len(prefix) > 64:
            raise ConfigurationValidationError(
                f"command_policy.settings.allowed_commands[{index}] must be a non-empty argv list"
            )
        for part in prefix:
            if not isinstance(part, str) or not part or "\x00" in part or len(part) > 512:
                raise ConfigurationValidationError(
                    f"command_policy.settings.allowed_commands[{index}] contains an invalid argument"
                )
            total_chars += len(part)
        if total_chars > 8192:
            raise ConfigurationValidationError("command policy exceeds the total text limit")
        candidate = list(prefix)
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _validate_schema2_component(key, component):
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
        raise ConfigurationValidationError("schema-2 component keys must be lowercase identifiers")
    if not isinstance(component, dict):
        raise ConfigurationValidationError(f"component {key!r} must be an object")
    allowed_component_keys = {"type", "component_version", "adapter", "settings", "secret_refs"}
    unknown = set(component) - allowed_component_keys
    if unknown:
        raise ConfigurationValidationError(f"component {key!r} has unknown fields: {sorted(unknown)}")
    component_type = component.get("type")
    if not isinstance(component_type, str) or component_type not in {
        "model", "assistant_runtime", "command_policy", "deterministic_verifier"
    }:
        raise ConfigurationValidationError(f"component {key!r} has an unsupported type")
    _schema2_int(component.get("component_version"), f"component {key!r}.component_version", 1, 1)
    adapter = component.get("adapter")
    if not isinstance(adapter, dict) or set(adapter) != {"id", "contract_version"}:
        raise ConfigurationValidationError(f"component {key!r}.adapter must contain id and contract_version")
    try:
        resolve_adapter_contract(adapter.get("id"), adapter.get("contract_version"), component_type)
    except UnsupportedAdapterError as exc:
        raise ConfigurationValidationError(f"component {key!r} has an unsupported adapter contract") from exc
    settings = component.get("settings")
    if not isinstance(settings, dict):
        raise ConfigurationValidationError(f"component {key!r}.settings must be an object")

    if component_type == "model":
        unknown = set(settings) - {"endpoint", "model", "timeout_seconds"}
        if unknown or set(settings) != {"endpoint", "model", "timeout_seconds"}:
            raise ConfigurationValidationError(f"model component {key!r} has missing or unknown settings")
        _schema2_endpoint(settings["endpoint"])
        _schema2_text(settings["model"], f"component {key!r}.settings.model", maximum=512)
        _schema2_int(settings["timeout_seconds"], f"component {key!r}.settings.timeout_seconds", 1, 600)
        secret_refs = component.get("secret_refs", {})
        if not isinstance(secret_refs, dict) or set(secret_refs) - {"api_key"}:
            raise ConfigurationValidationError(f"model component {key!r}.secret_refs supports only api_key")
        for name, reference in secret_refs.items():
            if name != "api_key" or not isinstance(reference, str) or not re.fullmatch(
                r"env:[A-Za-z_][A-Za-z0-9_]*", reference
            ):
                raise ConfigurationValidationError("model secret references must use env:VARIABLE_NAME")
    elif "secret_refs" in component:
        raise ConfigurationValidationError(f"component {key!r} does not support secret references")

    if component_type == "assistant_runtime":
        required = {
            "model_component", "persona_prompt", "max_output_tokens", "temperature",
            "context_window_tokens", "history_messages", "max_history_chars", "memory_limit",
        }
        if set(settings) != required:
            raise ConfigurationValidationError(
                f"assistant_runtime component {key!r} must define exactly {sorted(required)}"
            )
        model_key = settings["model_component"]
        if not isinstance(model_key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", model_key):
            raise ConfigurationValidationError("assistant_runtime.model_component must be a component key")
        _schema2_text(settings["persona_prompt"], "assistant_runtime.persona_prompt", maximum=12000, allow_empty=True)
        _schema2_int(settings["max_output_tokens"], "assistant_runtime.max_output_tokens", 1, 32768)
        _schema2_number(settings["temperature"], "assistant_runtime.temperature", 0.0, 2.0)
        _schema2_int(settings["context_window_tokens"], "assistant_runtime.context_window_tokens", 4096, 2_000_000)
        _schema2_int(settings["history_messages"], "assistant_runtime.history_messages", 0, 512)
        _schema2_int(settings["max_history_chars"], "assistant_runtime.max_history_chars", 0, 2_000_000)
        _schema2_int(settings["memory_limit"], "assistant_runtime.memory_limit", 0, 256)

    elif component_type == "command_policy":
        if set(settings) != {"allowed_commands"}:
            raise ConfigurationValidationError("command_policy settings must contain only allowed_commands")
        _schema2_argv_prefixes(settings["allowed_commands"])

    elif component_type == "deterministic_verifier":
        required = {"required_fields", "evidence_fields", "max_output_bytes", "allow_additional_fields"}
        if set(settings) != required:
            raise ConfigurationValidationError(
                f"deterministic_verifier component {key!r} must define exactly {sorted(required)}"
            )
        for field_name in ("required_fields", "evidence_fields"):
            fields = settings[field_name]
            if not isinstance(fields, list) or len(fields) > 128:
                raise ConfigurationValidationError(f"deterministic_verifier.{field_name} must be a bounded list")
            if any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", item) for item in fields):
                raise ConfigurationValidationError(f"deterministic_verifier.{field_name} contains an invalid field name")
            if len(fields) != len(set(fields)):
                raise ConfigurationValidationError(f"deterministic_verifier.{field_name} must be unique")
        if not set(settings["evidence_fields"]).issubset(set(settings["required_fields"])):
            raise ConfigurationValidationError("evidence_fields must be included in required_fields")
        _schema2_int(settings["max_output_bytes"], "deterministic_verifier.max_output_bytes", 1, 1_048_576)
        if not isinstance(settings["allow_additional_fields"], bool):
            raise ConfigurationValidationError("deterministic_verifier.allow_additional_fields must be boolean")


def _validate_schema2_mapping(value):
    _reject_non_finite(value)
    _check_json_compatible(value)
    allowed = {"schema_version", "components", "entrypoints", "extensions"}
    unknown = set(value) - allowed
    if unknown:
        raise ConfigurationValidationError(f"unknown schema-2 top-level keys: {sorted(unknown)}")
    if set(value) - {"extensions"} != {"schema_version", "components", "entrypoints"}:
        raise ConfigurationValidationError("schema 2 requires schema_version, components, and entrypoints")
    components = value["components"]
    if not isinstance(components, dict) or not components or len(components) > 64:
        raise ConfigurationValidationError("schema-2 components must be an object with 1 through 64 entries")
    for key, component in components.items():
        _validate_schema2_component(key, component)
    entrypoints = value["entrypoints"]
    if not isinstance(entrypoints, dict) or set(entrypoints) != {"assistant"}:
        raise ConfigurationValidationError("schema-2 entrypoints must define exactly assistant")
    assistant_key = entrypoints["assistant"]
    if not isinstance(assistant_key, str) or assistant_key not in components:
        raise ConfigurationValidationError("entrypoints.assistant must reference an existing component")
    if components[assistant_key]["type"] != "assistant_runtime":
        raise ConfigurationValidationError("entrypoints.assistant must reference an assistant_runtime")
    model_key = components[assistant_key]["settings"]["model_component"]
    if model_key not in components or components[model_key]["type"] != "model":
        raise ConfigurationValidationError("assistant_runtime must reference an existing model component")
    if "extensions" in value:
        extensions = value["extensions"]
        if not isinstance(extensions, dict):
            raise ConfigurationValidationError("schema-2 extensions must be an object")
        for name, extension in extensions.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,63}:[a-z][a-z0-9_.-]{0,63}", name
            ):
                raise ConfigurationValidationError("extension names must be namespaced")
            if (
                not isinstance(extension, dict)
                or set(extension) != {"version", "data"}
                or isinstance(extension.get("version"), bool)
                or not isinstance(extension.get("version"), int)
                or not 1 <= extension["version"] <= 2_147_483_647
                or not isinstance(extension.get("data"), dict)
            ):
                raise ConfigurationValidationError(f"extension {name!r} must contain version and object data")
    if len(canonical_json(value).encode("utf-8")) > 2_097_152:
        raise ConfigurationValidationError("schema-2 definition exceeds the 2 MiB size limit")
    _reject_non_finite(value)
    _check_json_compatible(value)
    _check_sensitive_keys(value)
    return copy.deepcopy(value)


def _validate_mapping(value):
    if not isinstance(value, dict):
        raise ConfigurationValidationError("definition must be a JSON object")
    if "schema_version" not in value:
        raise ConfigurationValidationError("schema_version is required")
    if "components" not in value:
        raise ConfigurationValidationError("components is required")
    schema_version = value["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ConfigurationValidationError("schema_version must be an integer")
    if schema_version == 2:
        return _validate_schema2_mapping(value)
    if schema_version != 1:
        raise ConfigurationValidationError("unsupported schema_version")
    unknown = set(value) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigurationValidationError(f"unknown top-level keys: {sorted(unknown)}")
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


def validate_executable_definition(value):
    """Validate and return only schema-2 definitions eligible for runtime binding."""
    normalized = validate_definition(value)
    if normalized["schema_version"] != 2:
        raise ConfigurationValidationError(
            "schema-1 definitions are readable/editable but are not executable"
        )
    return normalized


def preview_schema1_migration(value):
    """Return a non-mutating migration assessment; never invent a schema-2 mapping."""
    normalized = validate_definition(value)
    if normalized["schema_version"] != 1:
        raise ConfigurationValidationError("migration preview requires a schema-1 definition")
    components = normalized.get("components", {})
    findings = []
    if not components:
        findings.append("schema-1 definition has no typed assistant entrypoint")
    else:
        findings.append("schema-1 component payloads are opaque and cannot be losslessly typed")
    findings.append("provider, adapter, secret, generation, and entrypoint semantics require explicit review")
    return {
        "source_schema_version": 1,
        "target_schema_version": 2,
        "source_content_hash": content_hash(normalized),
        "automatic_migration": False,
        "requires_manual_reconstruction": True,
        "source_revision_must_remain_unchanged": True,
        "component_keys": tuple(sorted(components)),
        "findings": tuple(findings),
    }


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
    with store.lock:
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
