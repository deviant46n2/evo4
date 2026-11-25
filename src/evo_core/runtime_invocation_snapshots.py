"""Immutable, secret-safe runtime snapshots for individual invocations.

Snapshots preserve the exact non-secret runtime inputs and provenance used to
construct a workspace-bound assistant. Resolved credential values are never
serialized. This module does not create invocations or authorize dispatch.
"""
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import uuid

from . import workspaces
from .store import utc_now


MIGRATION_NAME = "runtime_invocation_snapshots_v1"
SNAPSHOT_SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 262144


class RuntimeSnapshotError(ValueError):
    """A runtime snapshot cannot be safely created or read."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def initialize_runtime_invocation_snapshots(store):
    db = workspaces._store_db(store)
    with store.lock:
        if db.in_transaction:
            raise RuntimeError("unexpected active transaction on EvoStore connection")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS runtime_invocation_snapshots (
                    invocation_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
                    project_id TEXT NOT NULL,
                    workspace_version INTEGER NOT NULL CHECK(workspace_version > 0),
                    configuration_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_runtime_snapshots_workspace
                ON runtime_invocation_snapshots(workspace_id, created_at)
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS runtime_snapshots_no_update
                BEFORE UPDATE ON runtime_invocation_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'runtime invocation snapshots are immutable');
                END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS runtime_snapshots_no_delete
                BEFORE DELETE ON runtime_invocation_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'runtime invocation snapshots cannot be deleted');
                END
            """)
            applied = db.execute(
                "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
            ).fetchone()
            if not applied:
                db.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                    (MIGRATION_NAME, utc_now()),
                )
            db.commit()
            return "already-initialized" if applied else "initialized"
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise


def _runtime_snapshot_payload(runtime):
    config = runtime.assistant.config
    participant = runtime.participant
    if not is_dataclass(participant):
        raise RuntimeSnapshotError("runtime participant descriptor is invalid")
    # Deliberately enumerate safe fields. In particular, config.api_key is
    # never read or copied into the durable record.
    runtime_config = {
        "base_url": config.base_url,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "system_prompt": config.system_prompt,
        "memory_limit": config.memory_limit,
        "history_messages": config.history_messages,
        "max_history_chars": config.max_history_chars,
        "context_window_tokens": config.context_window_tokens,
        "allowed_commands": [list(command) for command in config.allowed_commands],
    }
    provenance = dict(runtime.provenance)
    safe_provenance = {
        key: provenance[key] for key in (
            "workspace_id", "project_id", "configuration_id",
            "configuration_revision_id", "revision_hash",
            "assistant_component_key", "model_component_key",
            "adapter_id", "adapter_contract_version", "canonical_path",
            "secret_reference_names",
        ) if key in provenance
    }
    payload = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "workspace_id": runtime.workspace_id,
        "project_id": runtime.project_id,
        "configuration_id": runtime.configuration_id,
        "revision_id": runtime.revision_id,
        "checkout_id": runtime.checkout_id,
        "workspace_version": runtime.workspace_version,
        "revision_hash": runtime.revision_hash,
        "runtime_config": runtime_config,
        "participant": asdict(participant),
        "effective_allowed_commands": [list(command) for command in runtime.effective_allowed_commands],
        "provenance": safe_provenance,
        "dispatch_enabled": False,
    }
    try:
        encoded = _canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise RuntimeSnapshotError("runtime snapshot contains non-serializable values") from exc
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise RuntimeSnapshotError("runtime snapshot exceeds the storage limit")
    return payload, encoded, sha256(encoded.encode("utf-8")).hexdigest()


def create_runtime_invocation_snapshot(store, runtime, *, invocation_id=None):
    """Persist one immutable snapshot after revalidating its workspace binding.

    invocation_id is supplied by the future invocation owner; this function
    intentionally does not invent or persist invocation lifecycle state.
    """
    if invocation_id is None:
        invocation_id = str(uuid.uuid4())
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise RuntimeSnapshotError("invocation_id must be a non-empty string of at most 128 characters")
    invocation_id = invocation_id.strip()
    payload, encoded, digest = _runtime_snapshot_payload(runtime)
    created_at = utc_now()

    def operation(db):
        # Check inside the same BEGIN IMMEDIATE transaction as the insert so a
        # concurrent rebind cannot slip between validation and persistence.
        runtime.assert_current(store)
        db.execute(
            """INSERT INTO runtime_invocation_snapshots (
                invocation_id, workspace_id, project_id, workspace_version,
                configuration_id, revision_id, revision_hash,
                snapshot_json, snapshot_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                invocation_id, runtime.workspace_id, runtime.project_id,
                runtime.workspace_version, runtime.configuration_id,
                runtime.revision_id, runtime.revision_hash, encoded, digest, created_at,
            ),
        )
        return {
            "invocation_id": invocation_id,
            "workspace_id": runtime.workspace_id,
            "project_id": runtime.project_id,
            "workspace_version": runtime.workspace_version,
            "configuration_id": runtime.configuration_id,
            "revision_id": runtime.revision_id,
            "revision_hash": runtime.revision_hash,
            "snapshot_hash": digest,
            "created_at": created_at,
            "snapshot": payload,
        }

    return workspaces._write(store, operation)


def get_runtime_invocation_snapshot(store, invocation_id):
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise RuntimeSnapshotError("invocation_id must be a non-empty string")
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM runtime_invocation_snapshots WHERE invocation_id=?",
            (invocation_id.strip(),),
        ).fetchone()
    if row is None:
        return None
    encoded = row["snapshot_json"]
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    if digest != row["snapshot_hash"]:
        raise RuntimeSnapshotError("persisted runtime snapshot integrity check failed")
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise RuntimeSnapshotError("persisted runtime snapshot is malformed") from exc
    return {
        "invocation_id": row["invocation_id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "workspace_version": row["workspace_version"],
        "configuration_id": row["configuration_id"],
        "revision_id": row["revision_id"],
        "revision_hash": row["revision_hash"],
        "snapshot_hash": row["snapshot_hash"],
        "created_at": row["created_at"],
        "snapshot": payload,
    }


def list_runtime_invocation_snapshots(store, workspace_id, *, limit=100):
    workspaces._text(workspace_id, "workspace_id", required=True)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise RuntimeSnapshotError("limit must be a positive integer")
    limit = min(limit, 500)
    with store.lock:
        rows = store.db.execute(
            """SELECT invocation_id, workspace_id, project_id, workspace_version,
                      configuration_id, revision_id, revision_hash, snapshot_hash, created_at
               FROM runtime_invocation_snapshots
               WHERE workspace_id=? ORDER BY created_at DESC, invocation_id DESC LIMIT ?""",
            (workspace_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
