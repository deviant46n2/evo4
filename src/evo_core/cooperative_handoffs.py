"""Versioned, bounded, immutable handoff contracts for sequential cooperation.

This module validates and records structured artifacts only. It does not invoke
participants, authorize dispatch, execute tools, or advance an experiment.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import uuid

from . import workspaces
from .store import utc_now


HANDOFF_SCHEMA_VERSION = 1
HANDOFF_CONTRACT_VERSION = 1
MAX_HANDOFF_BYTES = 131072
MAX_CONTEXT_REFERENCES = 64
MAX_LIST_ITEMS = 80
MAX_TEXT_CHARS = 8192
MAX_REFERENCE_CHARS = 2048
MIGRATION_NAME = "cooperative_handoffs_v1"
HANDOFF_ROLES = frozenset({"proposal", "critique", "synthesis", "adjudication"})
PERSISTABLE_ROLES = frozenset({"proposal", "critique", "synthesis"})


class HandoffError(ValueError):
    """A handoff is malformed, unbounded, or outside its pinned lifecycle."""


@dataclass(frozen=True)
class HandoffBudget:
    input_tokens: int
    output_tokens: int
    deadline_utc: str

    def __post_init__(self):
        for name, value in (("input_tokens", self.input_tokens), ("output_tokens", self.output_tokens)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000_000:
                raise HandoffError(f"{name} must be a positive bounded integer")
        _parse_deadline(self.deadline_utc)


@dataclass(frozen=True)
class HandoffContextReference:
    reference_id: str
    source_type: str
    scope: str
    trust_label: str


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HandoffError("duplicate JSON object key")
        result[key] = value
    return result


_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _text(value, field, *, maximum=MAX_TEXT_CHARS, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > maximum:
        raise HandoffError(f"{field} must be non-empty bounded text")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise HandoffError(f"{field} contains unsupported control characters")
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise HandoffError(f"{field} appears to contain credential material")
    return value


def _reference_list(value, field, *, maximum=MAX_LIST_ITEMS):
    if not isinstance(value, list) or len(value) > maximum:
        raise HandoffError(f"{field} must be a bounded list")
    result = []
    for item in value:
        result.append(_text(item, field, maximum=MAX_REFERENCE_CHARS))
    if len(result) != len(set(result)):
        raise HandoffError(f"{field} contains duplicate references")
    return result


def _exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise HandoffError("handoff payload fields do not match the role contract")


def _parse_deadline(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise HandoffError("handoff deadline is missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError("handoff deadline is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HandoffError("handoff deadline must include a timezone")
    return parsed.astimezone(timezone.utc)


def _enum(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise HandoffError(f"{field} is unsupported")
    return value


def validate_context_references(references):
    if not isinstance(references, (list, tuple)) or len(references) > MAX_CONTEXT_REFERENCES:
        raise HandoffError("context references must be a bounded list")
    normalized = []
    seen = set()
    for item in references:
        if isinstance(item, HandoffContextReference):
            item = {
                "reference_id": item.reference_id, "source_type": item.source_type,
                "scope": item.scope, "trust_label": item.trust_label,
            }
        _exact_keys(item, {"reference_id", "source_type", "scope", "trust_label"})
        reference_id = _text(item["reference_id"], "context reference id", maximum=128)
        source_type = _enum(
            item["source_type"],
            {"task_statement", "repository_revision", "artifact", "verification", "handoff"},
            "context reference source_type",
        )
        scope = _text(item["scope"], "context reference scope", maximum=256)
        expected_trust = {
            "task_statement": "untrusted_input",
            "repository_revision": "untrusted_input",
            "artifact": "derived_output",
            "verification": "verified_evidence",
            "handoff": "derived_output",
        }[source_type]
        trust_label = _enum(
            item["trust_label"],
            {expected_trust},
            "context reference trust_label for its source type",
        )
        if reference_id in seen:
            raise HandoffError("context references must be unique")
        seen.add(reference_id)
        normalized.append({
            "reference_id": reference_id, "source_type": source_type,
            "scope": scope, "trust_label": trust_label,
        })
    return normalized


def validate_handoff_payload(role, payload):
    """Validate one role-specific JSON object and return a detached canonical value."""
    role = _enum(role, HANDOFF_ROLES, "handoff role")
    if role == "proposal":
        _exact_keys(payload, {"summary", "plan"}, {"artifact_references"})
        _text(payload["summary"], "proposal summary")
        if not isinstance(payload["plan"], list) or not 1 <= len(payload["plan"]) <= 40:
            raise HandoffError("proposal plan must contain 1 to 40 steps")
        plan, ids = [], set()
        for step in payload["plan"]:
            _exact_keys(step, {"step_id", "description"}, {"affected_paths", "evidence_references"})
            step_id = _text(step["step_id"], "proposal step id", maximum=96)
            if step_id in ids:
                raise HandoffError("proposal step IDs must be unique")
            ids.add(step_id)
            plan.append({
                "step_id": step_id,
                "description": _text(step["description"], "proposal step description", maximum=2048),
                "affected_paths": _reference_list(step.get("affected_paths", []), "affected_paths", maximum=32),
                "evidence_references": _reference_list(step.get("evidence_references", []), "evidence_references", maximum=32),
            })
        result = {"summary": payload["summary"], "plan": plan}
        if "artifact_references" in payload:
            result["artifact_references"] = _reference_list(payload["artifact_references"], "artifact_references")
    elif role == "critique":
        _exact_keys(payload, {"summary", "findings"})
        _text(payload["summary"], "critique summary")
        if not isinstance(payload["findings"], list) or len(payload["findings"]) > 40:
            raise HandoffError("critique findings must be a bounded list")
        findings, ids = [], set()
        for finding in payload["findings"]:
            _exact_keys(finding, {"finding_id", "severity", "target", "issue", "recommendation"}, {"evidence_references"})
            finding_id = _text(finding["finding_id"], "finding id", maximum=96)
            if finding_id in ids:
                raise HandoffError("critique finding IDs must be unique")
            ids.add(finding_id)
            severity = _enum(
                finding["severity"], {"critical", "high", "medium", "low", "informational"},
                "critique finding severity",
            )
            findings.append({
                "finding_id": finding_id,
                "severity": severity,
                "target": _text(finding["target"], "finding target", maximum=512),
                "issue": _text(finding["issue"], "finding issue", maximum=4096),
                "recommendation": _text(finding["recommendation"], "finding recommendation", maximum=2048),
                "evidence_references": _reference_list(finding.get("evidence_references", []), "evidence_references", maximum=32),
            })
        result = {"summary": payload["summary"], "findings": findings}
    elif role == "synthesis":
        _exact_keys(payload, {"summary", "dispositions"}, {"artifact_references"})
        _text(payload["summary"], "synthesis summary")
        if not isinstance(payload["dispositions"], list) or len(payload["dispositions"]) > 80:
            raise HandoffError("synthesis dispositions must be a bounded list")
        dispositions, ids = [], set()
        for item in payload["dispositions"]:
            _exact_keys(item, {"finding_id", "disposition", "reason"})
            finding_id = _text(item["finding_id"], "disposition finding id", maximum=96)
            if finding_id in ids:
                raise HandoffError("synthesis finding dispositions must be unique")
            ids.add(finding_id)
            disposition = _enum(
                item["disposition"], {"accepted", "rejected", "deferred"},
                "synthesis disposition",
            )
            dispositions.append({
                "finding_id": finding_id, "disposition": disposition,
                "reason": _text(item["reason"], "disposition reason", maximum=2048),
            })
        result = {"summary": payload["summary"], "dispositions": dispositions}
        if "artifact_references" in payload:
            result["artifact_references"] = _reference_list(payload["artifact_references"], "artifact_references")
    else:
        _exact_keys(payload, {"reviewer_type", "criteria_results", "notes"})
        reviewer_type = _enum(payload["reviewer_type"], {"human", "deterministic"}, "adjudication reviewer_type")
        _text(payload["notes"], "adjudication notes", maximum=4096, allow_empty=True)
        if not isinstance(payload["criteria_results"], list) or not 1 <= len(payload["criteria_results"]) <= 100:
            raise HandoffError("adjudication requires 1 to 100 criteria results")
        criteria, ids = [], set()
        for item in payload["criteria_results"]:
            _exact_keys(item, {"criterion_id", "status", "evidence_references"})
            criterion_id = _text(item["criterion_id"], "criterion id", maximum=96)
            if criterion_id in ids:
                raise HandoffError("adjudication criterion IDs must be unique")
            ids.add(criterion_id)
            status = _enum(item["status"], {"pass", "fail", "unknown"}, "adjudication criterion status")
            criteria.append({
                "criterion_id": criterion_id, "status": status,
                "evidence_references": _reference_list(item["evidence_references"], "evidence_references", maximum=32),
            })
        result = {"reviewer_type": reviewer_type, "criteria_results": criteria, "notes": payload["notes"]}
    encoded = _canonical(result)
    if len(encoded.encode("utf-8")) > MAX_HANDOFF_BYTES:
        raise HandoffError("handoff payload exceeds the byte limit")
    return json.loads(encoded)


def initialize_cooperative_handoffs(store):
    """Create append-only handoff storage; invocation/snapshot migrations must exist first."""
    db = workspaces._store_db(store)
    with store.lock:
        tables = {
            row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"runtime_invocation_snapshots", "participant_invocations", "schema_migrations"}.issubset(tables):
            raise HandoffError("runtime snapshots and invocation lifecycle must be initialized first")
        if db.in_transaction:
            raise RuntimeError("unexpected active transaction on EvoStore connection")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS participant_invocation_outputs (
                    invocation_id TEXT PRIMARY KEY REFERENCES participant_invocations(invocation_id) ON DELETE RESTRICT,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    configuration_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    participant_id TEXT NOT NULL,
                    task_role TEXT NOT NULL CHECK(task_role IN ('proposal','critique','synthesis')),
                    output_json TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS participant_outputs_no_update
                BEFORE UPDATE ON participant_invocation_outputs
                BEGIN SELECT RAISE(ABORT, 'participant invocation outputs are immutable'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS participant_outputs_no_delete
                BEFORE DELETE ON participant_invocation_outputs
                BEGIN SELECT RAISE(ABORT, 'participant invocation outputs cannot be deleted'); END
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS cooperative_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    invocation_id TEXT NOT NULL REFERENCES participant_invocations(invocation_id) ON DELETE RESTRICT,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    configuration_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    source_output_hash TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('proposal','critique','synthesis')),
                    source_participant_id TEXT NOT NULL,
                    target_participant_id TEXT,
                    handoff_json TEXT NOT NULL,
                    handoff_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(invocation_id, role)
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_cooperative_handoffs_task
                ON cooperative_handoffs(workspace_id, task_id, created_at)
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS cooperative_handoffs_no_update
                BEFORE UPDATE ON cooperative_handoffs
                BEGIN SELECT RAISE(ABORT, 'cooperative handoffs are immutable'); END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS cooperative_handoffs_no_delete
                BEFORE DELETE ON cooperative_handoffs
                BEGIN SELECT RAISE(ABORT, 'cooperative handoffs cannot be deleted'); END
            """)
            applied = db.execute("SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)).fetchone()
            if not applied:
                db.execute("INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)", (MIGRATION_NAME, utc_now()))
            db.commit()
            return "already-initialized" if applied else "initialized"
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise


def record_participant_output(store, invocation_id, output_json, *, task_role):
    """Persist a bounded structured-role completion after successful settlement."""
    task_role = _enum(task_role, PERSISTABLE_ROLES, "participant output task role")
    initialize_cooperative_handoffs(store)
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise HandoffError("invocation_id is invalid")
    if not isinstance(output_json, str):
        raise HandoffError("participant output must be JSON text")
    try:
        encoded_bytes = output_json.encode("utf-8")
        output = json.loads(output_json, object_pairs_hook=_unique_pairs)
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        raise HandoffError("participant output is malformed") from exc
    if len(encoded_bytes) > MAX_HANDOFF_BYTES:
        raise HandoffError("participant output exceeds the byte limit")
    _exact_keys(output, {"content", "tool_calls", "finish_reason", "truncated"})
    if (
        not isinstance(output["content"], str)
        or output["tool_calls"] != []
        or output["truncated"] is not False
        or (output["finish_reason"] is not None and not isinstance(output["finish_reason"], str))
    ):
        raise HandoffError("structured handoff output must be complete text-only output without tool calls")
    if output["finish_reason"] is not None:
        _text(output["finish_reason"], "participant finish reason", maximum=128, allow_empty=True)
    _text(output["content"], "participant structured output", maximum=MAX_HANDOFF_BYTES)
    output_hash = sha256(output_json.encode("utf-8")).hexdigest()
    created_at = utc_now()

    def operation(db):
        row = db.execute(
            """SELECT i.*, s.snapshot_hash AS current_snapshot_hash,
                      s.workspace_id AS snapshot_workspace_id,
                      s.project_id AS snapshot_project_id,
                      s.configuration_id AS snapshot_configuration_id,
                      s.revision_id AS snapshot_revision_id,
                      s.revision_hash AS snapshot_revision_hash,
                      s.snapshot_json AS snapshot_json,
                      l.state AS lease_state
               FROM participant_invocations i
               JOIN runtime_invocation_snapshots s ON s.invocation_id=i.invocation_id
               LEFT JOIN dispatch_leases l ON l.invocation_id=i.invocation_id
               WHERE i.invocation_id=?""",
            (invocation_id.strip(),),
        ).fetchone()
        if row is None or row["status"] != "succeeded" or row["lease_state"] is not None:
            raise HandoffError("structured output requires a settled successful invocation with no active lease")
        if sha256(row["snapshot_json"].encode("utf-8")).hexdigest() != row["current_snapshot_hash"]:
            raise HandoffError("structured output source snapshot integrity check failed")
        if (
            row["snapshot_hash"] != row["current_snapshot_hash"]
            or row["workspace_id"] != row["snapshot_workspace_id"]
            or row["project_id"] != row["snapshot_project_id"]
            or row["configuration_id"] != row["snapshot_configuration_id"]
            or row["revision_id"] != row["snapshot_revision_id"]
            or row["revision_hash"] != row["snapshot_revision_hash"]
        ):
            raise HandoffError("structured output invocation does not match its immutable snapshot")
        db.execute(
            """INSERT INTO participant_invocation_outputs(
                invocation_id,workspace_id,project_id,configuration_id,revision_id,
                revision_hash,snapshot_hash,participant_id,task_role,output_json,output_hash,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                invocation_id.strip(), row["workspace_id"], row["project_id"],
                row["configuration_id"], row["revision_id"], row["revision_hash"],
                row["snapshot_hash"], row["participant_id"], task_role,
                output_json, output_hash, created_at,
            ),
        )
        return {"invocation_id": invocation_id.strip(), "output_hash": output_hash, "created_at": created_at}
    return workspaces._write(store, operation)


def create_handoff(
    store, runtime, *, invocation_id, task_id, role, target_participant_id,
    payload, context_references=(), budget,
):
    """Persist a handoff only from a succeeded invocation on this exact runtime revision."""
    role = _enum(role, PERSISTABLE_ROLES, "persistable handoff role")
    task_id = _text(task_id, "task_id", maximum=128)
    if not isinstance(budget, HandoffBudget):
        raise HandoffError("handoff requires validated per-handoff token ceilings and a deadline")
    normalized_payload = validate_handoff_payload(role, payload)
    references = validate_context_references(context_references)
    parent = getattr(runtime, "parent_runtime", runtime)
    selected = runtime if hasattr(runtime, "participant") else None
    if (
        selected is None
        or not hasattr(selected, "participant_adapter")
        or selected.participant.participant_type != "model"
    ):
        raise HandoffError("handoff source must be a selected model participant runtime")
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise HandoffError("invocation_id is invalid")
    if target_participant_id is not None:
        if not isinstance(target_participant_id, str) or not target_participant_id.strip() or len(target_participant_id) > 128:
            raise HandoffError("target participant ID is invalid")
        if role in {"proposal", "critique"} and target_participant_id == selected.participant.participant_id:
            raise HandoffError(f"{role} must target a distinct participant")
        participants = {
            item.participant_id for item in parent.participants
            if item.participant_type == "model"
        }
        if target_participant_id not in participants:
            raise HandoffError("handoff target is not a model participant bound to the pinned runtime revision")
    elif role in {"proposal", "critique"}:
        raise HandoffError(f"{role} requires a target participant from the pinned runtime revision")
    parent.assert_current(store)
    created_at = utc_now()
    deadline = _parse_deadline(budget.deadline_utc)
    if deadline <= datetime.now(timezone.utc):
        raise HandoffError("handoff deadline must be in the future")
    payload_record = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "task_id": task_id,
        "role": role,
        "source_participant_id": selected.participant.participant_id,
        "target_participant_id": target_participant_id,
        "context_references": references,
        "budget": {
            "input_tokens": budget.input_tokens,
            "output_tokens": budget.output_tokens,
            "deadline_utc": budget.deadline_utc,
        },
        "payload": normalized_payload,
    }
    encoded = _canonical(payload_record)
    if len(encoded.encode("utf-8")) > MAX_HANDOFF_BYTES:
        raise HandoffError("complete handoff record exceeds the byte limit")
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    handoff_id = "handoff_" + uuid.uuid4().hex
    def operation(db):
        parent.assert_current(store)
        invocation = db.execute(
            "SELECT * FROM participant_invocations WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        snapshot = db.execute(
            "SELECT * FROM runtime_invocation_snapshots WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        output_record = db.execute(
            "SELECT * FROM participant_invocation_outputs WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if invocation is None or snapshot is None or output_record is None:
            raise HandoffError("handoff source invocation, snapshot, or structured output artifact is missing")
        if invocation["status"] != "succeeded":
            raise HandoffError("handoff source invocation must have succeeded")
        try:
            snapshot_payload = json.loads(snapshot["snapshot_json"])
        except (TypeError, ValueError) as exc:
            raise HandoffError("handoff source snapshot is malformed") from exc
        if sha256(snapshot["snapshot_json"].encode("utf-8")).hexdigest() != snapshot["snapshot_hash"]:
            raise HandoffError("handoff source snapshot integrity check failed")
        if not isinstance(snapshot_payload, dict):
            raise HandoffError("handoff source snapshot must be a JSON object")
        snapshot_participant = snapshot_payload.get("participant")
        if not isinstance(snapshot_participant, dict):
            raise HandoffError("handoff source snapshot participant descriptor is invalid")
        if (
            snapshot_payload.get("invocation_kind") != "participant_completion"
            or snapshot_participant.get("participant_id") != selected.participant.participant_id
            or snapshot_participant.get("integration_id") != selected.participant.integration_id
        ):
            raise HandoffError("handoff source snapshot does not identify the selected participant")
        if (
            invocation["participant_id"] != selected.participant.participant_id
            or invocation["workspace_id"] != parent.workspace_id
            or invocation["project_id"] != parent.project_id
            or invocation["configuration_id"] != parent.configuration_id
            or invocation["revision_id"] != parent.revision_id
            or invocation["revision_hash"] != parent.revision_hash
            or invocation["snapshot_hash"] != snapshot["snapshot_hash"]
            or snapshot["workspace_id"] != parent.workspace_id
            or snapshot["project_id"] != parent.project_id
            or snapshot["configuration_id"] != parent.configuration_id
            or snapshot["revision_id"] != parent.revision_id
            or snapshot["revision_hash"] != parent.revision_hash
        ):
            raise HandoffError("handoff source invocation does not match the selected pinned runtime")
        if sha256(output_record["output_json"].encode("utf-8")).hexdigest() != output_record["output_hash"]:
            raise HandoffError("persisted participant output integrity check failed")
        if (
            output_record["participant_id"] != selected.participant.participant_id
            or output_record["task_role"] != role
            or output_record["snapshot_hash"] != snapshot["snapshot_hash"]
            or output_record["workspace_id"] != parent.workspace_id
            or output_record["project_id"] != parent.project_id
            or output_record["configuration_id"] != parent.configuration_id
            or output_record["revision_id"] != parent.revision_id
            or output_record["revision_hash"] != parent.revision_hash
        ):
            raise HandoffError("participant output artifact does not match the pinned invocation")
        try:
            normalized_output = json.loads(
                output_record["output_json"], object_pairs_hook=_unique_pairs
            )
            model_payload = json.loads(
                normalized_output["content"], object_pairs_hook=_unique_pairs
            )
            model_payload = validate_handoff_payload(role, model_payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise HandoffError("participant output does not satisfy the requested handoff contract") from exc
        if _canonical(model_payload) != _canonical(normalized_payload):
            raise HandoffError("handoff payload differs from the participant's persisted structured output")
        invocation_deadline = _parse_deadline(invocation["deadline_utc"])
        if deadline > invocation_deadline:
            raise HandoffError("handoff deadline cannot exceed its source invocation deadline")
        try:
            snapshot_context = snapshot_payload["runtime_config"]["context_window_tokens"]
        except (KeyError, TypeError) as exc:
            raise HandoffError("source snapshot is missing its bounded context window") from exc
        if (
            isinstance(snapshot_context, bool)
            or not isinstance(snapshot_context, int)
            or snapshot_context < 1
            or isinstance(invocation["requested_output_tokens"], bool)
            or not isinstance(invocation["requested_output_tokens"], int)
            or budget.output_tokens > invocation["requested_output_tokens"]
            or budget.input_tokens + budget.output_tokens > snapshot_context
        ):
            raise HandoffError("handoff token ceilings exceed the source invocation or context-window limits")
        db.execute(
            """INSERT INTO cooperative_handoffs(
                handoff_id,invocation_id,workspace_id,project_id,configuration_id,
                revision_id,revision_hash,snapshot_hash,source_output_hash,task_id,role,
                source_participant_id,target_participant_id,handoff_json,handoff_hash,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                handoff_id, invocation_id, parent.workspace_id, parent.project_id,
                parent.configuration_id, parent.revision_id, parent.revision_hash,
                snapshot["snapshot_hash"], output_record["output_hash"], task_id, role, selected.participant.participant_id,
                target_participant_id, encoded, digest, created_at,
            ),
        )
        return {
            "handoff_id": handoff_id, "invocation_id": invocation_id,
            "workspace_id": parent.workspace_id, "project_id": parent.project_id,
            "configuration_id": parent.configuration_id, "revision_id": parent.revision_id,
            "revision_hash": parent.revision_hash, "snapshot_hash": snapshot["snapshot_hash"],
            "source_output_hash": output_record["output_hash"],
            "task_id": task_id, "role": role,
            "source_participant_id": selected.participant.participant_id,
            "target_participant_id": target_participant_id,
            "handoff_hash": digest, "created_at": created_at,
            "handoff": payload_record,
        }
    return workspaces._write(store, operation)


def get_handoff(store, handoff_id):
    if not isinstance(handoff_id, str) or not handoff_id.strip() or len(handoff_id) > 128:
        raise HandoffError("handoff ID is invalid")
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM cooperative_handoffs WHERE handoff_id=?", (handoff_id.strip(),)
        ).fetchone()
    if row is None:
        return None
    encoded = row["handoff_json"]
    if sha256(encoded.encode("utf-8")).hexdigest() != row["handoff_hash"]:
        raise HandoffError("persisted handoff integrity check failed")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise HandoffError("persisted handoff JSON is malformed") from exc
    return {**dict(row), "handoff_json": value}


def list_handoffs(store, workspace_id, task_id, *, limit=100):
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise HandoffError("workspace_id is required")
    task_id = _text(task_id, "task_id", maximum=128)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise HandoffError("handoff list limit must be positive")
    with store.lock:
        rows = store.db.execute(
            """SELECT handoff_id,invocation_id,role,source_participant_id,target_participant_id,
                      handoff_hash,created_at
               FROM cooperative_handoffs WHERE workspace_id=? AND task_id=?
               ORDER BY created_at, handoff_id LIMIT ?""",
            (workspace_id.strip(), task_id, min(limit, 500)),
        ).fetchall()
    return [dict(row) for row in rows]
