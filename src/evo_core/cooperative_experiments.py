"""Durable, sequential cooperative experiment records.

This module freezes a task/run manifest and records operator-controlled lifecycle
transitions. It never dispatches participants, executes commands, or resumes work.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import uuid

from . import workspaces
from .store import utc_now


MIGRATION_NAME = "cooperative_experiments_v1"
CONDITIONS = frozenset({"A", "B", "C", "D"})
STATUSES = frozenset({
    "planned", "authorized", "running", "verifying", "adjudicating",
    "succeeded", "failed", "cancelled", "interrupted", "unknown",
})
TRANSITIONS = {
    "planned": frozenset({"authorized", "cancelled"}),
    "authorized": frozenset({"running", "cancelled"}),
    "running": frozenset({"verifying", "failed", "cancelled", "interrupted", "unknown"}),
    "verifying": frozenset({"adjudicating", "failed", "interrupted", "unknown"}),
    "adjudicating": frozenset({"succeeded", "failed", "interrupted", "unknown"}),
}
MAX_SPEC_BYTES = 131072
MAX_EVENT_BYTES = 32768


class ExperimentError(ValueError):
    """An experiment manifest or lifecycle transition is invalid."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


_SECRET_TEXT = re.compile(
    r"(?i)(?:\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def _text(value, field, maximum=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ExperimentError(f"{field} must be non-empty bounded text")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise ExperimentError(f"{field} contains unsupported control characters")
    if _SECRET_TEXT.search(value):
        raise ExperimentError(f"{field} appears to contain credential material")
    return value.strip()


def _reject_secret_material(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or re.search(r"(?i)(api[_-]?key|authorization|secret|password|credential)", key):
                raise ExperimentError("event payload contains a prohibited credential field")
            _reject_secret_material(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_material(item)
    elif isinstance(value, str) and _SECRET_TEXT.search(value):
        raise ExperimentError("event payload appears to contain credential material")


def _positive_int(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ExperimentError(f"{field} must be a positive bounded integer")
    return value


def _utc_deadline(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ExperimentError("deadline_utc is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentError("deadline_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentError("deadline_utc must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise ExperimentError("deadline_utc must be in the future")
    return parsed.isoformat().replace("+00:00", "Z")


def _references(value, field, maximum=100):
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise ExperimentError(f"{field} must be a bounded reference list")
    result = [_text(item, field, 512) for item in value]
    if len(result) != len(set(result)):
        raise ExperimentError(f"{field} must not contain duplicates")
    return result


def _participant_manifest(runtime):
    participants = []
    for descriptor in runtime.participants:
        item = asdict(descriptor)
        # The descriptor is code-owned and must never contain resolved credentials.
        encoded = _canonical(item)
        if re.search(r"(?i)(api[_-]?key|authorization|bearer|secret_value|password)", encoded):
            raise ExperimentError("participant descriptor contains credential-like fields")
        participants.append(item)
    ids = [p.get("participant_id") for p in participants]
    integrations = [p.get("integration_id") for p in participants]
    if not participants or any(not isinstance(x, str) or not x for x in ids + integrations):
        raise ExperimentError("runtime participant identities are incomplete")
    if len(ids) != len(set(ids)) or len(integrations) != len(set(integrations)):
        raise ExperimentError("runtime participant identities are ambiguous")
    return participants


def initialize_cooperative_experiments(store):
    """Install append-only run events and frozen experiment manifests."""
    db = workspaces._store_db(store)
    with store.lock:
        tables = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"workspaces", "runtime_invocation_snapshots", "participant_invocations",
                    "cooperative_handoffs", "schema_migrations"}
        if not required.issubset(tables):
            raise ExperimentError("workspace, invocation, and handoff foundations must be initialized first")
        if db.in_transaction:
            raise RuntimeError("unexpected active transaction on EvoStore connection")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS cooperative_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    configuration_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    condition TEXT NOT NULL CHECK(condition IN ('A','B','C','D')),
                    status TEXT NOT NULL CHECK(status IN
                      ('planned','authorized','running','verifying','adjudicating',
                       'succeeded','failed','cancelled','interrupted','unknown')),
                    spec_json TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS cooperative_experiment_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL REFERENCES cooperative_experiments(experiment_id) ON DELETE RESTRICT,
                    idempotency_key TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(experiment_id, idempotency_key)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_coop_experiments_workspace ON cooperative_experiments(workspace_id, created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_coop_experiment_events ON cooperative_experiment_events(experiment_id, event_id)")
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS cooperative_experiment_events_no_update
                BEFORE UPDATE ON cooperative_experiment_events
                BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS cooperative_experiment_events_no_delete
                BEFORE DELETE ON cooperative_experiment_events
                BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS cooperative_experiment_spec_immutable
                BEFORE UPDATE OF experiment_id, workspace_id, project_id, configuration_id,
                                 revision_id, revision_hash, condition, spec_json, spec_hash, created_at
                ON cooperative_experiments
                BEGIN SELECT RAISE(ABORT, 'experiment manifest is immutable'); END
            """)
            applied = db.execute("SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)).fetchone()
            if not applied:
                db.execute("INSERT INTO schema_migrations(name, applied_at) VALUES (?,?)", (MIGRATION_NAME, utc_now()))
            db.commit()
            return "already-initialized" if applied else "initialized"
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise


def create_experiment(store, runtime, *, task_statement, acceptance_criteria,
                      verification_commands, condition, input_token_ceiling,
                      output_token_ceiling, wall_clock_seconds, deadline_utc,
                      experiment_id=None):
    """Freeze a benchmark task against the exact workspace-bound runtime revision."""
    initialize_cooperative_experiments(store)
    if not isinstance(condition, str) or condition not in CONDITIONS:
        raise ExperimentError("condition must be one of A, B, C, or D")
    task_statement = _text(task_statement, "task_statement", 20000)
    criteria = _references(acceptance_criteria, "acceptance_criteria", 100)
    if not criteria:
        raise ExperimentError("at least one acceptance criterion is required")
    if not isinstance(verification_commands, (list, tuple)) or not 1 <= len(verification_commands) <= 20:
        raise ExperimentError("verification_commands must contain 1 to 20 commands")
    commands = []
    for command in verification_commands:
        if not isinstance(command, (list, tuple)) or not 1 <= len(command) <= 32:
            raise ExperimentError("each verification command must be a bounded argument vector")
        commands.append([_text(arg, "verification command argument", 512) for arg in command])
    deadline = _utc_deadline(deadline_utc)
    budgets = {
        "input_token_ceiling": _positive_int(input_token_ceiling, "input_token_ceiling", 100_000_000),
        "output_token_ceiling": _positive_int(output_token_ceiling, "output_token_ceiling", 100_000_000),
        "wall_clock_seconds": _positive_int(wall_clock_seconds, "wall_clock_seconds", 604800),
        "deadline_utc": deadline,
    }
    if datetime.fromisoformat(deadline.replace("Z", "+00:00")) > datetime.now(timezone.utc) + timedelta(seconds=budgets["wall_clock_seconds"]):
        raise ExperimentError("deadline_utc exceeds the frozen wall-clock ceiling")
    participants = _participant_manifest(runtime)
    model_count = sum(1 for p in participants if p.get("participant_type") == "model")
    if condition in {"C", "D"} and model_count < 2:
        raise ExperimentError("cooperation conditions C and D require two distinct model participants")
    workspace = workspaces.get_workspace(store, runtime.workspace_id)
    if (workspace["project_id"] != runtime.project_id
            or workspace["configuration_id"] != runtime.configuration_id
            or workspace["configuration_revision_id"] != runtime.revision_id):
        raise ExperimentError("runtime no longer matches the workspace's pinned configuration revision")
    spec = {
        "schema_version": 1,
        "task_statement": task_statement,
        "task_statement_sha256": sha256(task_statement.encode("utf-8")).hexdigest(),
        "acceptance_criteria": criteria,
        "verification_commands": commands,
        "participants": participants,
        "participant_selection": (
            [participants[0]["participant_id"]] if condition in {"A", "B"}
            else [p["participant_id"] for p in participants if p.get("participant_type") == "model"][:2]
        ),
        "budgets": budgets,
        "execution_policy": "sequential_global_provider_lease",
        "automatic_resume": False,
    }
    spec_json = _canonical(spec)
    if len(spec_json.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ExperimentError("experiment manifest exceeds the storage limit")
    experiment_id = _text(experiment_id or str(uuid.uuid4()), "experiment_id", 128)
    now = utc_now()
    digest = sha256(spec_json.encode("utf-8")).hexdigest()

    def operation(db):
        current = workspaces._workspace_row(db, runtime.workspace_id)
        if (current["status"] != "active" or current["project_id"] != runtime.project_id
                or current["configuration_id"] != runtime.configuration_id
                or current["configuration_revision_id"] != runtime.revision_id):
            raise ExperimentError("workspace changed or is not active")
        db.execute("""
            INSERT INTO cooperative_experiments(
                experiment_id,workspace_id,project_id,configuration_id,revision_id,
                revision_hash,condition,status,spec_json,spec_hash,version,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,'planned',?,?,1,?,?)
        """, (experiment_id, runtime.workspace_id, runtime.project_id, runtime.configuration_id,
              runtime.revision_id, runtime.revision_hash, condition, spec_json, digest, now, now))
        db.execute("""
            INSERT INTO cooperative_experiment_events(
                experiment_id,idempotency_key,from_status,to_status,event_type,payload_json,created_at
            ) VALUES(?,? ,NULL,'planned','created',?,?)
        """, (experiment_id, "created", _canonical({"spec_hash": digest}), now))
        return _experiment_row(db, experiment_id)
    return workspaces._write(store, operation)


def _experiment_row(db, experiment_id):
    row = db.execute("SELECT * FROM cooperative_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
    if row is None:
        raise ExperimentError("experiment not found")
    result = dict(row)
    if sha256(result["spec_json"].encode("utf-8")).hexdigest() != result["spec_hash"]:
        raise ExperimentError("experiment manifest integrity check failed")
    result["spec"] = json.loads(result["spec_json"])
    return result


def get_experiment(store, experiment_id):
    initialize_cooperative_experiments(store)
    return workspaces._read(store, lambda db: _experiment_row(db, experiment_id))


def list_experiments(store, workspace_id, limit=50):
    initialize_cooperative_experiments(store)
    workspace_id = _text(workspace_id, "workspace_id", 128)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ExperimentError("limit must be between 1 and 200")
    def operation(db):
        rows = db.execute(
            "SELECT experiment_id FROM cooperative_experiments WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        ).fetchall()
        return [_experiment_row(db, row["experiment_id"]) for row in rows]
    return workspaces._read(store, operation)


def transition_experiment(store, experiment_id, to_status, *, idempotency_key,
                          event_type, payload=None, expected_version=None):
    """Atomically append one valid transition; never resumes or invokes work."""
    initialize_cooperative_experiments(store)
    if not isinstance(to_status, str) or to_status not in STATUSES:
        raise ExperimentError("target experiment status is unsupported")
    key = _text(idempotency_key, "idempotency_key", 128)
    event_type = _text(event_type, "event_type", 64)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", event_type):
        raise ExperimentError("event_type is invalid")
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        raise ExperimentError("event payload must be an object")
    _reject_secret_material(payload)
    payload_json = _canonical(payload)
    if len(payload_json.encode("utf-8")) > MAX_EVENT_BYTES:
        raise ExperimentError("event payload exceeds the storage limit")
    now = utc_now()

    def operation(db):
        row = _experiment_row(db, experiment_id)
        prior = db.execute(
            "SELECT * FROM cooperative_experiment_events WHERE experiment_id=? AND idempotency_key=?",
            (experiment_id, key),
        ).fetchone()
        if prior is not None:
            if prior["to_status"] == to_status and prior["event_type"] == event_type and prior["payload_json"] == payload_json:
                return _experiment_row(db, experiment_id)
            raise ExperimentError("idempotency key was already used for a different transition")
        if expected_version is not None and (
            isinstance(expected_version, bool) or not isinstance(expected_version, int)
            or expected_version != row["version"]
        ):
            raise ExperimentError("experiment version conflict")
        current = row["status"]
        if to_status not in TRANSITIONS.get(current, frozenset()):
            raise ExperimentError(f"transition {current} -> {to_status} is not allowed")
        if to_status == "adjudicating":
            refs = payload.get("verification_evidence_references")
            if not _references(refs, "verification_evidence_references"):
                raise ExperimentError("verification evidence is required before adjudication")
        if to_status == "succeeded":
            adjudication = payload.get("adjudication")
            if (not isinstance(adjudication, dict)
                    or not isinstance(adjudication.get("reviewer_type"), str)
                    or adjudication.get("reviewer_type") not in {"human", "deterministic"}):
                raise ExperimentError("success requires explicit adjudication")
            results = adjudication.get("criteria_results")
            if not isinstance(results, list) or not results:
                raise ExperimentError("success requires adjudication results for acceptance criteria")
            expected = set(json.loads(row["spec_json"])["acceptance_criteria"])
            observed = []
            for item in results:
                if not isinstance(item, dict) or set(item) != {"criterion_id", "status", "evidence_references"}:
                    raise ExperimentError("adjudication criterion result is malformed")
                if not isinstance(item["status"], str) or item["status"] not in {"pass", "fail", "unknown"}:
                    raise ExperimentError("adjudication criterion status is invalid")
                criterion_id = _text(item["criterion_id"], "criterion_id", 128)
                observed.append(criterion_id)
                if not _references(item["evidence_references"], "adjudication evidence references"):
                    raise ExperimentError("each adjudicated criterion requires evidence")
            if len(observed) != len(set(observed)) or set(observed) != expected or any(item["status"] != "pass" for item in results):
                raise ExperimentError("success requires every frozen criterion to pass with explicit evidence")
        next_version = row["version"] + 1
        db.execute("""
            INSERT INTO cooperative_experiment_events(
                experiment_id,idempotency_key,from_status,to_status,event_type,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?)
        """, (experiment_id, key, current, to_status, event_type, payload_json, now))
        db.execute("UPDATE cooperative_experiments SET status=?,version=?,updated_at=? WHERE experiment_id=? AND version=?",
                   (to_status, next_version, now, experiment_id, row["version"]))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise ExperimentError("experiment version conflict")
        return _experiment_row(db, experiment_id)
    return workspaces._write(store, operation)


def list_experiment_events(store, experiment_id):
    initialize_cooperative_experiments(store)
    def operation(db):
        _experiment_row(db, experiment_id)
        rows = db.execute(
            "SELECT * FROM cooperative_experiment_events WHERE experiment_id=? ORDER BY event_id",
            (experiment_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    return workspaces._read(store, operation)
