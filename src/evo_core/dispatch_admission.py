"""Durable authorization, resource admission, and invocation lifecycle primitives.

This module deliberately does not install itself into a participant adapter.
P3.5 wiring must pass these decisions through the single dispatch boundary and
must not treat a persisted runtime snapshot as invocation authorization.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import uuid

from . import workspaces
from .runtime_invocation_snapshots import get_runtime_invocation_snapshot
from .store import utc_now


MIGRATION_NAME = "participant_invocation_lifecycle_v1"
GLOBAL_PROVIDER_LEASE = "global_provider_dispatch"
TERMINAL_STATUSES = frozenset({
    "succeeded", "malformed_output", "unavailable", "denied",
    "rate_limited", "timed_out", "cancelled", "budget_exhausted",
    "provider_failed", "abandoned",
})


class AdmissionError(RuntimeError):
    """An invocation cannot be safely authorized or admitted."""


@dataclass(frozen=True)
class ResourceDemand:
    locality: str
    cpu_cores: float
    ram_mib: float
    gpu_vram_mib: float | None = None
    maximum_gpu_temperature_c: float | None = 85.0

    def __post_init__(self):
        if self.locality not in {"local_process", "local_endpoint", "remote_service"}:
            raise ValueError("resource locality is unsupported")
        for name, value in (("cpu_cores", self.cpu_cores), ("ram_mib", self.ram_mib)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.gpu_vram_mib is not None and (
            isinstance(self.gpu_vram_mib, bool)
            or not isinstance(self.gpu_vram_mib, (int, float))
            or not math.isfinite(self.gpu_vram_mib)
            or self.gpu_vram_mib <= 0
        ):
            raise ValueError("gpu_vram_mib must be a finite positive number or None")
        if self.locality == "local_endpoint" and self.gpu_vram_mib is None:
            raise ValueError("local endpoint demand requires an explicit GPU/CPU resource profile")
        if self.locality != "local_endpoint" and self.gpu_vram_mib is not None:
            raise ValueError("GPU VRAM demand is supported only for a local endpoint")
        if self.maximum_gpu_temperature_c is not None and (
            isinstance(self.maximum_gpu_temperature_c, bool)
            or not isinstance(self.maximum_gpu_temperature_c, (int, float))
            or not math.isfinite(self.maximum_gpu_temperature_c)
            or not 1 <= self.maximum_gpu_temperature_c <= 110
        ):
            raise ValueError("maximum GPU temperature is invalid")


@dataclass(frozen=True)
class AdmissionPolicy:
    telemetry_max_age_seconds: int = 10
    ram_reserve_mib: float = 2048.0
    cpu_reserve_cores: float = 1.0
    gpu_vram_reserve_mib: float = 1024.0
    cpu_pressure_percent: float = 90.0

    def __post_init__(self):
        if isinstance(self.telemetry_max_age_seconds, bool) or not isinstance(self.telemetry_max_age_seconds, int) or not 1 <= self.telemetry_max_age_seconds <= 60:
            raise ValueError("telemetry_max_age_seconds must be between 1 and 60")
        for name, value in (
            ("ram_reserve_mib", self.ram_reserve_mib),
            ("cpu_reserve_cores", self.cpu_reserve_cores),
            ("gpu_vram_reserve_mib", self.gpu_vram_reserve_mib),
            ("cpu_pressure_percent", self.cpu_pressure_percent),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.cpu_pressure_percent > 100:
            raise ValueError("cpu_pressure_percent cannot exceed 100")


@dataclass(frozen=True)
class ProviderBudget:
    maximum_requests_per_utc_day: int
    maximum_output_tokens_per_invocation: int
    maximum_reserved_output_tokens_per_utc_day: int

    def __post_init__(self):
        for name, value in (
            ("maximum_requests_per_utc_day", self.maximum_requests_per_utc_day),
            ("maximum_output_tokens_per_invocation", self.maximum_output_tokens_per_invocation),
            ("maximum_reserved_output_tokens_per_utc_day", self.maximum_reserved_output_tokens_per_utc_day),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def _parse_utc(value, field):
    if not isinstance(value, str) or not value:
        raise AdmissionError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdmissionError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_resource_admission(telemetry, demand: ResourceDemand, policy=AdmissionPolicy(), *, now=None):
    """Return a deterministic allow/defer/unknown decision from one fresh snapshot."""
    if not isinstance(telemetry, dict):
        return {"decision": "unknown", "reason": "telemetry_unavailable"}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        sampled_at = _parse_utc(telemetry.get("sampled_at"), "telemetry sampled_at")
    except AdmissionError:
        return {"decision": "unknown", "reason": "telemetry_timestamp_invalid"}
    age = (now.astimezone(timezone.utc) - sampled_at).total_seconds()
    if age < -2:
        return {"decision": "unknown", "reason": "telemetry_timestamp_in_future", "age_seconds": age}
    if age > policy.telemetry_max_age_seconds:
        return {"decision": "unknown", "reason": "telemetry_stale", "age_seconds": age}

    ram_available = telemetry.get("ram_available_bytes")
    cores = telemetry.get("cpu_logical_cores")
    load = telemetry.get("load_average_1m")
    if (
        isinstance(ram_available, bool) or not isinstance(ram_available, (int, float))
        or not math.isfinite(ram_available) or ram_available < 0
        or isinstance(cores, bool) or not isinstance(cores, int) or cores < 1
        or isinstance(load, bool) or not isinstance(load, (int, float))
        or not math.isfinite(load) or load < 0
    ):
        return {"decision": "unknown", "reason": "required_cpu_or_ram_telemetry_missing"}
    ram_headroom_mib = ram_available / (1024 * 1024) - policy.ram_reserve_mib
    cpu_headroom = max(0.0, float(cores) - float(load)) - policy.cpu_reserve_cores
    result = {
        "decision": "admitted",
        "reason": "resource_requirements_satisfied",
        "telemetry_age_seconds": round(age, 3),
        "ram_headroom_mib": round(ram_headroom_mib, 2),
        "cpu_headroom_cores": round(cpu_headroom, 3),
        "required_ram_mib": float(demand.ram_mib),
        "required_cpu_cores": float(demand.cpu_cores),
        "locality": demand.locality,
    }
    cpu_util = telemetry.get("cpu_utilization_percent")
    if cpu_util is not None:
        if isinstance(cpu_util, bool) or not isinstance(cpu_util, (int, float)) or not math.isfinite(cpu_util) or not 0 <= cpu_util <= 100:
            return {"decision": "unknown", "reason": "cpu_utilization_telemetry_invalid"}
        if cpu_util >= policy.cpu_pressure_percent:
            return {**result, "decision": "deferred", "reason": "cpu_pressure"}
    if ram_headroom_mib < demand.ram_mib:
        return {**result, "decision": "deferred", "reason": "insufficient_ram_headroom"}
    if cpu_headroom < demand.cpu_cores:
        return {**result, "decision": "deferred", "reason": "insufficient_cpu_headroom"}

    if demand.gpu_vram_mib is not None:
        used = telemetry.get("gpu_memory_used_mib")
        total = telemetry.get("gpu_memory_total_mib")
        temperature = telemetry.get("gpu_temperature_c")
        if telemetry.get("gpu_available") is not True:
            return {**result, "decision": "unknown", "reason": "required_gpu_telemetry_unavailable"}
        if (
            isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or used < 0
            or isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or total <= 0
            or used > total
            or isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature)
        ):
            return {**result, "decision": "unknown", "reason": "required_gpu_telemetry_invalid"}
        gpu_headroom = total - used - policy.gpu_vram_reserve_mib
        result.update({
            "gpu_vram_headroom_mib": round(gpu_headroom, 2),
            "required_gpu_vram_mib": float(demand.gpu_vram_mib),
            "gpu_temperature_c": float(temperature),
        })
        if demand.maximum_gpu_temperature_c is not None and temperature >= demand.maximum_gpu_temperature_c:
            return {**result, "decision": "deferred", "reason": "gpu_temperature_ceiling"}
        if gpu_headroom < demand.gpu_vram_mib:
            return {**result, "decision": "deferred", "reason": "insufficient_gpu_vram_headroom"}
    return result


def initialize_invocation_lifecycle(store):
    """Install append-only audit and durable lease tables in the Registry database."""
    db = workspaces._store_db(store)

    def operation(connection):
        connection.execute("""
            CREATE TABLE IF NOT EXISTS participant_invocations (
                invocation_id TEXT PRIMARY KEY REFERENCES runtime_invocation_snapshots(invocation_id) ON DELETE RESTRICT,
                workspace_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                integration_id TEXT NOT NULL,
                adapter_id TEXT NOT NULL,
                configuration_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                revision_hash TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'admitted','running','succeeded','malformed_output','unavailable',
                    'denied','deferred','rate_limited','timed_out','cancelled',
                    'budget_exhausted','provider_failed','abandoned'
                )),
                decision_json TEXT NOT NULL,
                deadline_utc TEXT NOT NULL,
                requested_output_tokens INTEGER NOT NULL CHECK(requested_output_tokens > 0),
                budget_day_utc TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                usage_json TEXT,
                error_code TEXT,
                error_message TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS provider_budget_usage (
                integration_id TEXT NOT NULL,
                budget_day_utc TEXT NOT NULL,
                requests_reserved INTEGER NOT NULL DEFAULT 0 CHECK(requests_reserved >= 0),
                output_tokens_reserved INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens_reserved >= 0),
                output_tokens_used INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens_used >= 0),
                PRIMARY KEY(integration_id, budget_day_utc)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS dispatch_leases (
                lease_key TEXT PRIMARY KEY,
                invocation_id TEXT NOT NULL UNIQUE REFERENCES participant_invocations(invocation_id) ON DELETE RESTRICT,
                owner_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('active','abandoned')),
                acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                deadline_utc TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS invocation_lifecycle_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                invocation_id TEXT NOT NULL REFERENCES participant_invocations(invocation_id) ON DELETE RESTRICT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_invocations_workspace_created
            ON participant_invocations(workspace_id, created_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_invocations_integration_day
            ON participant_invocations(integration_id, budget_day_utc)
        """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS invocation_events_no_update
            BEFORE UPDATE ON invocation_lifecycle_events
            BEGIN SELECT RAISE(ABORT, 'invocation lifecycle events are append-only'); END
        """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS invocation_events_no_delete
            BEFORE DELETE ON invocation_lifecycle_events
            BEGIN SELECT RAISE(ABORT, 'invocation lifecycle events are append-only'); END
        """)
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
        ).fetchone()
        if not applied:
            connection.execute(
                "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                (MIGRATION_NAME, utc_now()),
            )
        return True

    return workspaces._write(store, operation)


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _event(db, invocation_id, event_type, payload):
    encoded = _canonical_json(payload)
    if len(encoded.encode("utf-8")) > 16384:
        raise AdmissionError("lifecycle event exceeds the storage limit")
    db.execute(
        "INSERT INTO invocation_lifecycle_events(invocation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
        (invocation_id, event_type, encoded, utc_now()),
    )


def _snapshot_matches(db, runtime, envelope):
    row = db.execute(
        "SELECT * FROM runtime_invocation_snapshots WHERE invocation_id=?",
        (envelope.invocation_id,),
    ).fetchone()
    if row is None:
        raise AdmissionError("runtime invocation snapshot is missing")
    digest = sha256(row["snapshot_json"].encode("utf-8")).hexdigest()
    if digest != row["snapshot_hash"] or digest != row["snapshot_hash"]:
        raise AdmissionError("runtime invocation snapshot integrity check failed")
    if (
        row["workspace_id"] != runtime.workspace_id
        or row["project_id"] != runtime.project_id
        or row["configuration_id"] != runtime.configuration_id
        or row["revision_id"] != runtime.revision_id
        or row["revision_hash"] != runtime.revision_hash
    ):
        raise AdmissionError("runtime invocation snapshot does not match the bound runtime")
    try:
        snapshot = json.loads(row["snapshot_json"])
    except (TypeError, ValueError) as exc:
        raise AdmissionError("runtime invocation snapshot is malformed") from exc
    participant = snapshot.get("participant", {})
    if (
        participant.get("participant_id") != envelope.participant_id
        or participant.get("adapter_id") != envelope.adapter_id
        or participant.get("configuration_revision_id") != envelope.configuration_revision_id
    ):
        raise AdmissionError("invocation participant does not match the immutable runtime snapshot")
    return row


def _output_token_request(envelope):
    try:
        payload = json.loads(envelope.input_json)
        value = payload.get("max_tokens")
    except (TypeError, ValueError, AttributeError):
        raise AdmissionError("invocation output-token request is malformed")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdmissionError("invocation output-token request is invalid")
    return value


def _validate_envelope(runtime, envelope, now):
    from .participant_contracts import InvocationEnvelope
    if not isinstance(envelope, InvocationEnvelope):
        raise AdmissionError("a validated invocation envelope is required")
    if (
        envelope.invocation_id == ""
        or envelope.participant_id != runtime.participant.participant_id
        or envelope.project_id != runtime.project_id
        or envelope.workspace_id != runtime.workspace_id
        or envelope.configuration_id != runtime.configuration_id
        or envelope.configuration_revision_id != runtime.revision_id
        or envelope.adapter_id != runtime.participant.adapter_id
        or envelope.adapter_contract_version != runtime.participant.adapter_contract_version
    ):
        raise AdmissionError("invocation scope or participant identity does not match the runtime")
    deadline = _parse_utc(envelope.deadline_utc, "invocation deadline")
    remaining = (deadline - now).total_seconds()
    if remaining <= 0 or remaining > 600:
        raise AdmissionError("invocation deadline must be in the next 1–600 seconds")
    if envelope.retry_limit != 0:
        raise AdmissionError("automatic retries are not enabled")
    if not isinstance(envelope.input_json, str) or len(envelope.input_json.encode("utf-8")) > 1_048_576:
        raise AdmissionError("invocation input is missing or oversized")
    return deadline, _output_token_request(envelope)


def admit_invocation(
    store,
    runtime,
    envelope,
    *,
    approval=None,
    provider_budget: ProviderBudget | None = None,
    telemetry=None,
    resource_demand: ResourceDemand,
    policy=AdmissionPolicy(),
    owner_id=None,
    now=None,
):
    """Atomically persist the decision, reserve budgets, and acquire the global lease.

    The runtime binding and immutable invocation snapshot are revalidated inside
    the same BEGIN IMMEDIATE transaction as the lease and budget reservation.
    Denied/deferred decisions are persisted for audit and never acquire a lease.
    """
    initialize_invocation_lifecycle(store)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    deadline, requested_tokens = _validate_envelope(runtime, envelope, now)
    if requested_tokens > runtime.participant.limits_dict.get("max_output_tokens", requested_tokens) if hasattr(runtime.participant, "limits_dict") else False:
        raise AdmissionError("requested output tokens exceed the pinned participant limit")
    if not isinstance(resource_demand, ResourceDemand):
        raise AdmissionError("a code-owned resource demand is required")
    if owner_id is None:
        owner_id = str(uuid.uuid4())
    if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 128:
        raise AdmissionError("lease owner identity is invalid")

    # The deterministic verifier is local and does not consume provider quota or
    # the provider-dispatch lease. Model adapters require both exact compliance
    # approval and an explicit operator-configured daily budget.
    is_provider = runtime.participant.adapter_id == "openai_compatible_chat"
    if is_provider:
        expected_status = "local_only" if resource_demand.locality == "local_endpoint" else "approved"
        if approval is None or approval.status != expected_status or approval.adapter_id != runtime.participant.adapter_id:
            approval_result = {"decision": "denied", "reason": "provider_compliance_not_approved"}
        else:
            approval_result = {"decision": "admitted", "reason": "provider_compliance_approved"}
        if provider_budget is None:
            budget_result = {"decision": "denied", "reason": "provider_budget_not_configured"}
        else:
            budget_result = {"decision": "admitted", "reason": "provider_budget_configured"}
    else:
        approval_result = {"decision": "admitted", "reason": "not_a_provider_integration"}
        budget_result = {"decision": "admitted", "reason": "not_a_provider_integration"}

    resource_result = evaluate_resource_admission(telemetry, resource_demand, policy, now=now)
    output_limit = requested_tokens
    if provider_budget is not None:
        output_limit = min(output_limit, provider_budget.maximum_output_tokens_per_invocation)
    if requested_tokens > output_limit:
        budget_result = {"decision": "denied", "reason": "per_invocation_output_token_limit"}

    origin = getattr(runtime.bound_participant, "endpoint", None)
    integration_id = runtime.participant.integration_id
    budget_day = now.date().isoformat()
    decision = {
        "decision": "admitted",
        "reason": "all_gates_satisfied",
        "approval": approval_result,
        "budget": budget_result,
        "resource": resource_result,
        "provider_origin": origin,
        "requested_output_tokens": requested_tokens,
    }
    if approval_result["decision"] != "admitted":
        decision.update(approval_result)
    elif budget_result["decision"] != "admitted":
        decision.update(budget_result)
    elif resource_result["decision"] != "admitted":
        decision.update(resource_result)

    def operation(db):
        runtime.assert_current(store)
        snapshot = _snapshot_matches(db, runtime, envelope)
        existing = db.execute(
            "SELECT invocation_id FROM participant_invocations WHERE invocation_id=?",
            (envelope.invocation_id,),
        ).fetchone()
        if existing:
            raise AdmissionError("invocation ID has already been used")
        state = decision["decision"]
        lease_required = is_provider
        if state == "admitted" and lease_required:
            lease = db.execute(
                "SELECT * FROM dispatch_leases WHERE lease_key=?",
                (GLOBAL_PROVIDER_LEASE,),
            ).fetchone()
            if lease is not None:
                state = "deferred" if lease["state"] == "active" else "denied"
                decision["decision"] = state
                decision["reason"] = "global_provider_dispatch_busy" if lease["state"] == "active" else "global_provider_lease_abandoned"
        if state == "admitted" and is_provider:
            row = db.execute(
                "SELECT requests_reserved,output_tokens_reserved,output_tokens_used FROM provider_budget_usage WHERE integration_id=? AND budget_day_utc=?",
                (integration_id, budget_day),
            ).fetchone()
            requests = row["requests_reserved"] if row else 0
            reserved = row["output_tokens_reserved"] if row else 0
            if requests + 1 > provider_budget.maximum_requests_per_utc_day:
                state = "rate_limited"
                decision.update({"decision": state, "reason": "daily_request_budget_exhausted"})
            elif reserved + requested_tokens > provider_budget.maximum_reserved_output_tokens_per_utc_day:
                state = "budget_exhausted"
                decision.update({"decision": state, "reason": "daily_output_token_budget_exhausted"})
        db.execute(
            """INSERT INTO participant_invocations (
                invocation_id,workspace_id,project_id,participant_id,integration_id,adapter_id,
                configuration_id,revision_id,revision_hash,snapshot_hash,status,decision_json,
                deadline_utc,requested_output_tokens,budget_day_utc,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                envelope.invocation_id, runtime.workspace_id, runtime.project_id,
                runtime.participant.participant_id, integration_id, runtime.participant.adapter_id,
                runtime.configuration_id, runtime.revision_id, runtime.revision_hash,
                snapshot["snapshot_hash"], state, _canonical_json(decision),
                deadline.isoformat().replace("+00:00", "Z"), requested_tokens,
                budget_day if is_provider else None, utc_now(), utc_now(),
            ),
        )
        _event(db, envelope.invocation_id, "admission_decided", decision)
        if state == "admitted":
            if is_provider:
                db.execute(
                    """INSERT INTO provider_budget_usage
                       (integration_id,budget_day_utc,requests_reserved,output_tokens_reserved,output_tokens_used)
                       VALUES(?,?,1,?,0)
                       ON CONFLICT(integration_id,budget_day_utc) DO UPDATE SET
                         requests_reserved=requests_reserved+1,
                         output_tokens_reserved=output_tokens_reserved+excluded.output_tokens_reserved""",
                    (integration_id, budget_day, requested_tokens),
                )
                db.execute(
                    """INSERT INTO dispatch_leases
                       (lease_key,invocation_id,owner_id,state,acquired_at,heartbeat_at,deadline_utc)
                       VALUES(?,?,?,'active',?,?,?)""",
                    (
                        GLOBAL_PROVIDER_LEASE, envelope.invocation_id, owner_id,
                        utc_now(), utc_now(), deadline.isoformat().replace("+00:00", "Z"),
                    ),
                )
            return {"allowed": True, "status": "admitted", **decision}
        return {"allowed": False, "status": state, **decision}

    return workspaces._write(store, operation)


def mark_invocation_running(store, invocation_id):
    def operation(db):
        row = db.execute(
            "SELECT status FROM participant_invocations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None or row["status"] != "admitted":
            return False
        now = utc_now()
        db.execute(
            "UPDATE participant_invocations SET status='running',started_at=?,updated_at=? WHERE invocation_id=? AND status='admitted'",
            (now, now, invocation_id),
        )
        db.execute(
            "UPDATE dispatch_leases SET heartbeat_at=? WHERE invocation_id=? AND state='active'",
            (now, invocation_id),
        )
        _event(db, invocation_id, "invocation_started", {})
        return True
    return workspaces._write(store, operation)


def heartbeat_dispatch_lease(store, invocation_id):
    def operation(db):
        now = utc_now()
        cursor = db.execute(
            """UPDATE dispatch_leases SET heartbeat_at=?
               WHERE invocation_id=? AND state='active'
               AND deadline_utc > ?""",
            (now, invocation_id, now),
        )
        if cursor.rowcount == 1:
            _event(db, invocation_id, "lease_heartbeat", {})
        return cursor.rowcount == 1
    return workspaces._write(store, operation)


def finalize_invocation(store, invocation_id, status, *, usage=None, error_code=None, error_message=None, provider_settled=True):
    if status not in TERMINAL_STATUSES - {"denied", "abandoned"}:
        raise ValueError("invocation terminal status is invalid")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("invocation usage must be an object or None")
    if error_code is not None and (not isinstance(error_code, str) or len(error_code) > 128):
        raise ValueError("invocation error code is invalid")
    if error_message is not None and (not isinstance(error_message, str) or len(error_message) > 2000):
        raise ValueError("invocation error message is invalid")

    def operation(db):
        row = db.execute(
            "SELECT * FROM participant_invocations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return False
        if row["status"] in TERMINAL_STATUSES:
            return False
        now = utc_now()
        db.execute(
            """UPDATE participant_invocations SET status=?,finished_at=?,updated_at=?,
               usage_json=?,error_code=?,error_message=? WHERE invocation_id=?""",
            (
                status, now, now,
                _canonical_json(usage) if usage is not None else None,
                error_code, error_message[:2000] if error_message else None, invocation_id,
            ),
        )
        lease = db.execute(
            "SELECT * FROM dispatch_leases WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if lease is not None:
            if provider_settled and lease["state"] == "active":
                db.execute("DELETE FROM dispatch_leases WHERE invocation_id=?", (invocation_id,))
            else:
                db.execute(
                    "UPDATE dispatch_leases SET state='abandoned',heartbeat_at=? WHERE invocation_id=?",
                    (now, invocation_id),
                )
        # Unknown usage retains the full reservation: releasing it would permit
        # daily-budget oversubscription when the provider may have processed work.
        if usage is not None and row["budget_day_utc"] is not None:
            output_tokens = usage.get("output_tokens")
            if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0:
                db.execute(
                    """UPDATE provider_budget_usage
                       SET output_tokens_reserved=MAX(0,output_tokens_reserved-?),
                           output_tokens_used=output_tokens_used+?
                       WHERE integration_id=? AND budget_day_utc=?""",
                    (row["requested_output_tokens"], output_tokens, row["integration_id"], row["budget_day_utc"]),
                )
        _event(db, invocation_id, "invocation_finalized", {
            "status": status, "provider_settled": bool(provider_settled),
            "usage_known": usage is not None,
        })
        return True
    return workspaces._write(store, operation)


def mark_stale_dispatch_leases_abandoned(store, *, stale_after_seconds=15, now=None):
    if isinstance(stale_after_seconds, bool) or not isinstance(stale_after_seconds, int) or not 5 <= stale_after_seconds <= 300:
        raise ValueError("stale_after_seconds must be between 5 and 300")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = (now.astimezone(timezone.utc) - __import__("datetime").timedelta(seconds=stale_after_seconds)).isoformat().replace("+00:00", "Z")

    def operation(db):
        rows = db.execute(
            "SELECT invocation_id FROM dispatch_leases WHERE state='active' AND heartbeat_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            invocation_id = row["invocation_id"]
            db.execute(
                "UPDATE dispatch_leases SET state='abandoned' WHERE invocation_id=? AND state='active'",
                (invocation_id,),
            )
            db.execute(
                """UPDATE participant_invocations SET status='abandoned',updated_at=?
                   WHERE invocation_id=? AND status IN ('admitted','running')""",
                (utc_now(), invocation_id),
            )
            _event(db, invocation_id, "lease_marked_abandoned", {"reason": "heartbeat_stale"})
        return len(rows)
    return workspaces._write(store, operation)


def acknowledge_abandoned_dispatch_recovery(
    store, *, actor, reason, endpoint_idle_confirmed,
):
    """Release an abandoned global lease only after explicit operator attestation."""
    if endpoint_idle_confirmed is not True:
        raise AdmissionError("operator must explicitly confirm endpoint idleness")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise AdmissionError("recovery actor is required")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise AdmissionError("recovery reason is required")

    def operation(db):
        lease = db.execute(
            "SELECT * FROM dispatch_leases WHERE lease_key=?",
            (GLOBAL_PROVIDER_LEASE,),
        ).fetchone()
        if lease is None:
            return {"released": False, "reason": "no_lease"}
        if lease["state"] != "abandoned":
            raise AdmissionError("active leases cannot be manually released")
        invocation_id = lease["invocation_id"]
        db.execute("DELETE FROM dispatch_leases WHERE lease_key=?", (GLOBAL_PROVIDER_LEASE,))
        _event(db, invocation_id, "abandoned_lease_operator_recovery", {
            "actor": actor.strip(), "reason": reason.strip(),
            "endpoint_idle_confirmed": True,
        })
        return {"released": True, "invocation_id": invocation_id}
    return workspaces._write(store, operation)


def get_invocation_lifecycle(store, invocation_id):
    with store.lock:
        row = store.db.execute(
            "SELECT * FROM participant_invocations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return None
        events = store.db.execute(
            "SELECT event_type,payload_json,created_at FROM invocation_lifecycle_events WHERE invocation_id=? ORDER BY event_id",
            (invocation_id,),
        ).fetchall()
    result = dict(row)
    result["decision"] = json.loads(result.pop("decision_json"))
    result["usage"] = json.loads(result.pop("usage_json")) if result.get("usage_json") else None
    result["events"] = [
        {"event_type": item["event_type"], "payload": json.loads(item["payload_json"]), "created_at": item["created_at"]}
        for item in events
    ]
    return result
