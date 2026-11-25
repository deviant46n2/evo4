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
    compute_mode: str | None = None
    memory_mode: str | None = None
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
            or self.gpu_vram_mib > 1_048_576.0
        ):
            raise ValueError("gpu_vram_mib must be a finite positive number or None")
        if self.locality == "local_endpoint":
            if self.compute_mode not in {"cpu", "gpu", "mixed"}:
                raise ValueError("local endpoint demand requires an explicit compute_mode")
            if self.compute_mode in {"gpu", "mixed"} and self.gpu_vram_mib is None:
                raise ValueError("GPU/mixed local endpoint demand requires an explicit VRAM estimate")
            if self.compute_mode == "cpu" and self.gpu_vram_mib is not None:
                raise ValueError("CPU-only local endpoint demand cannot declare GPU VRAM")
            if self.memory_mode not in {"cold_load", "persistent_incremental"}:
                raise ValueError("local endpoint demand requires an explicit memory_mode")
        elif self.compute_mode is not None or self.memory_mode is not None or self.gpu_vram_mib is not None:
            raise ValueError("compute_mode, memory_mode, and GPU VRAM are supported only for a local endpoint")
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
        if not 0 < self.cpu_pressure_percent <= 100:
            raise ValueError("cpu_pressure_percent must be greater than zero and at most 100")


@dataclass(frozen=True)
class ProviderBudget:
    integration_id: str
    maximum_requests_per_utc_day: int
    maximum_output_tokens_per_invocation: int
    maximum_reserved_output_tokens_per_utc_day: int

    def __post_init__(self):
        if not isinstance(self.integration_id, str) or not self.integration_id.strip() or len(self.integration_id) > 128:
            raise ValueError("provider budget integration_id is required")
        for name, value in (
            ("maximum_requests_per_utc_day", self.maximum_requests_per_utc_day),
            ("maximum_output_tokens_per_invocation", self.maximum_output_tokens_per_invocation),
            ("maximum_reserved_output_tokens_per_utc_day", self.maximum_reserved_output_tokens_per_utc_day),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_requests_per_utc_day > 1_000_000:
            raise ValueError("daily request limit exceeds the supported maximum")
        if self.maximum_output_tokens_per_invocation > 10_000_000:
            raise ValueError("per-invocation token limit exceeds the supported maximum")
        if self.maximum_reserved_output_tokens_per_utc_day > 100_000_000:
            raise ValueError("daily reserved-token limit exceeds the supported maximum")
        if self.maximum_output_tokens_per_invocation > self.maximum_reserved_output_tokens_per_utc_day:
            raise ValueError("per-invocation token limit cannot exceed the daily reservation limit")


def derive_resource_demand(runtime, *, local_profile=None):
    """Derive locality from the bound endpoint; never accept workspace locality claims.

    Remote and local-process estimates are code-owned. A loopback model endpoint
    requires an operator-owned profile; there are intentionally no guessed VRAM
    or cold-load defaults.
    """
    adapter_id = runtime.participant.adapter_id
    if adapter_id == "evo_deterministic_verifier":
        return ResourceDemand("local_process", 0.10, 64.0)
    if adapter_id != "openai_compatible_chat":
        raise AdmissionError("participant adapter has no registered resource declaration")
    from urllib.parse import urlsplit
    from .provider_endpoint import is_loopback_provider_origin, normalize_provider_origin
    endpoint = getattr(runtime.bound_participant, "endpoint", None)
    try:
        parsed = urlsplit(endpoint)
        origin = normalize_provider_origin(f"{parsed.scheme}://{parsed.netloc}")
        is_local = is_loopback_provider_origin(origin)
    except Exception as exc:
        raise AdmissionError("bound provider endpoint locality cannot be established") from exc
    if not is_local:
        return ResourceDemand("remote_service", 0.05, 64.0)
    if not isinstance(local_profile, dict):
        raise AdmissionError("loopback model endpoint requires an operator-owned resource profile")
    required = {"compute_mode", "cpu_cores", "ram_mib", "memory_mode"}
    allowed = required | {"gpu_vram_mib", "maximum_gpu_temperature_c"}
    if required - set(local_profile) or set(local_profile) - allowed:
        raise AdmissionError("local resource profile has missing or unsupported fields")
    try:
        return ResourceDemand(
            locality="local_endpoint",
            cpu_cores=local_profile["cpu_cores"],
            ram_mib=local_profile["ram_mib"],
            gpu_vram_mib=local_profile.get("gpu_vram_mib"),
            compute_mode=local_profile["compute_mode"],
            memory_mode=local_profile["memory_mode"],
            maximum_gpu_temperature_c=local_profile.get("maximum_gpu_temperature_c", 85.0),
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("operator-owned local resource profile is invalid") from exc


def _parse_utc(value, field):
    if not isinstance(value, str) or not value or len(value) > 64:
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
    now = datetime.now(timezone.utc) if now is None else now
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
    if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", event_type):
        raise AdmissionError("lifecycle event type is invalid")
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
    if digest != row["snapshot_hash"]:
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
    if not isinstance(participant, dict):
        raise AdmissionError("runtime snapshot participant descriptor is malformed")
    if (
        participant.get("participant_id") != envelope.participant_id
        or participant.get("adapter_id") != envelope.adapter_id
        or participant.get("configuration_revision_id") != envelope.configuration_revision_id
    ):
        raise AdmissionError("invocation participant does not match the immutable runtime snapshot")
    return row


def _output_token_request(envelope):
    try:
        payload = json.loads(
            envelope.input_json,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON value")),
            object_pairs_hook=_unique_pairs,
        )
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
    string_limits = {
        "invocation_id": 128,
        "participant_id": 128,
        "adapter_id": 128,
        "configuration_id": 128,
        "configuration_revision_id": 128,
        "component_key": 128,
        "objective": 1024,
        "task_role": 128,
        "correlation_id": 128,
    }
    for field, maximum in string_limits.items():
        value = getattr(envelope, field, None)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise AdmissionError(f"invocation {field} is invalid")
    if (
        envelope.participant_id != runtime.participant.participant_id
        or envelope.project_id != runtime.project_id
        or envelope.workspace_id != runtime.workspace_id
        or envelope.configuration_id != runtime.configuration_id
        or envelope.configuration_revision_id != runtime.revision_id
        or envelope.adapter_id != runtime.participant.adapter_id
        or envelope.adapter_contract_version != runtime.participant.adapter_contract_version
        or envelope.component_key != runtime.participant.component_key
        or envelope.component_version != runtime.participant.component_version
    ):
        raise AdmissionError("invocation scope or participant identity does not match the runtime")
    if envelope.parent_task_id is not None and (
        not isinstance(envelope.parent_task_id, str)
        or not envelope.parent_task_id.strip()
        or len(envelope.parent_task_id) > 128
    ):
        raise AdmissionError("invocation parent task identity is invalid")
    deadline = _parse_utc(envelope.deadline_utc, "invocation deadline")
    remaining = (deadline - now).total_seconds()
    if remaining <= 0 or remaining > 600:
        raise AdmissionError("invocation deadline must be in the next 1–600 seconds")
    if isinstance(envelope.retry_limit, bool) or not isinstance(envelope.retry_limit, int) or envelope.retry_limit != 0:
        raise AdmissionError("automatic retries are not enabled")
    if (
        not isinstance(envelope.input_json, str)
        or len(envelope.input_json) > 1_048_576
        or not isinstance(envelope.output_contract_json, str)
        or len(envelope.output_contract_json) > 65536
    ):
        raise AdmissionError("invocation input or output contract is missing or oversized")
    try:
        if len(envelope.input_json.encode("utf-8")) > 1_048_576:
            raise AdmissionError("invocation input is missing or oversized")
        contract = json.loads(
            envelope.output_contract_json,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON value")),
            object_pairs_hook=lambda pairs: _unique_pairs(pairs),
        )
    except (UnicodeEncodeError, TypeError, ValueError, RecursionError) as exc:
        raise AdmissionError("invocation input or output contract is malformed") from exc
    if not isinstance(contract, dict):
        raise AdmissionError("invocation output contract must be a JSON object")
    context_refs = envelope.context_references
    if not isinstance(context_refs, tuple) or len(context_refs) > 128:
        raise AdmissionError("invocation context references are invalid")
    for reference in context_refs:
        for field in ("reference_id", "source_type", "scope", "trust_label"):
            value = getattr(reference, field, None)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise AdmissionError("invocation context reference is invalid")
    if not isinstance(envelope.acceptance_criteria, tuple) or len(envelope.acceptance_criteria) > 64:
        raise AdmissionError("invocation acceptance criteria are invalid")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in envelope.acceptance_criteria):
        raise AdmissionError("invocation acceptance criteria are invalid")
    allowed_permissions = {"text_generation", "tool_call_generation"}
    if (
        not isinstance(envelope.effective_permissions, tuple)
        or "text_generation" not in envelope.effective_permissions
        or len(envelope.effective_permissions) > 8
        or any(not isinstance(item, str) or item not in allowed_permissions for item in envelope.effective_permissions)
        or len(set(envelope.effective_permissions)) != len(envelope.effective_permissions)
    ):
        raise AdmissionError("invocation permissions exceed the initial model capability boundary")
    if (
        not isinstance(envelope.approval_requirements, tuple)
        or len(envelope.approval_requirements) > 32
        or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in envelope.approval_requirements)
    ):
        raise AdmissionError("invocation approval requirements are invalid")
    if not isinstance(envelope.remaining_budgets, tuple) or len(envelope.remaining_budgets) > 16:
        raise AdmissionError("invocation budget envelope is invalid")
    budget = {}
    for item in envelope.remaining_budgets:
        if not isinstance(item, tuple) or len(item) != 2:
            raise AdmissionError("invocation budget entry is malformed")
        name, value = item
        if not isinstance(name, str) or name not in {"output_tokens", "request_seconds"} or name in budget:
            raise AdmissionError("invocation budget dimension is unsupported or duplicated")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise AdmissionError("invocation budget value is invalid")
        budget[name] = value
    requested_tokens = _output_token_request(envelope)
    if budget.get("output_tokens", 0) < requested_tokens:
        raise AdmissionError("invocation remaining output-token budget is insufficient")
    if budget.get("request_seconds", 0) > remaining:
        raise AdmissionError("invocation request-time budget exceeds its deadline")
    return deadline, requested_tokens


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def admit_invocation(
    store,
    runtime,
    envelope,
    *,
    approval=None,
    provider_budget: ProviderBudget | None = None,
    telemetry=None,
    local_profile=None,
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
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    deadline, requested_tokens = _validate_envelope(runtime, envelope, now)
    try:
        resource_demand = derive_resource_demand(runtime, local_profile=local_profile)
    except AdmissionError:
        raise
    except Exception as exc:
        raise AdmissionError("participant resource declaration is invalid") from exc
    if not isinstance(policy, AdmissionPolicy):
        raise AdmissionError("an explicit admission policy is required")
    participant_limits = dict(runtime.participant.limits)
    pinned_output_limit = participant_limits.get("max_output_tokens")
    if (
        isinstance(pinned_output_limit, bool)
        or not isinstance(pinned_output_limit, int)
        or requested_tokens > pinned_output_limit
    ):
        raise AdmissionError("requested output tokens exceed the pinned participant limit")
    if owner_id is None:
        owner_id = str(uuid.uuid4())
    if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 128:
        raise AdmissionError("lease owner identity is invalid")

    is_provider = runtime.participant.adapter_id == "openai_compatible_chat"
    endpoint = getattr(runtime.bound_participant, "endpoint", None)
    origin = None
    if is_provider:
        from urllib.parse import urlsplit
        from .provider_endpoint import is_loopback_provider_origin, normalize_provider_origin
        try:
            parsed_endpoint = urlsplit(endpoint)
            origin = normalize_provider_origin(f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}")
            endpoint_is_local = is_loopback_provider_origin(origin)
        except Exception as exc:
            raise AdmissionError("bound provider origin is invalid") from exc
        expected_locality = "local_endpoint" if endpoint_is_local else "remote_service"
        expected_status = "local_only" if endpoint_is_local else "approved"
        if resource_demand.locality != expected_locality:
            approval_result = {"decision": "denied", "reason": "resource_locality_does_not_match_endpoint"}
        elif (
            approval is None
            or getattr(approval, "status", None) != expected_status
            or getattr(approval, "adapter_id", None) != runtime.participant.adapter_id
            or getattr(approval, "origin", None) != origin
            or "chat_completion" not in getattr(approval, "uses", ())
        ):
            approval_result = {"decision": "denied", "reason": "provider_compliance_not_approved"}
        else:
            approval_result = {"decision": "admitted", "reason": "provider_compliance_approved"}
        if not isinstance(provider_budget, ProviderBudget):
            budget_result = {"decision": "denied", "reason": "provider_budget_not_configured"}
        elif provider_budget.integration_id != runtime.participant.integration_id:
            budget_result = {"decision": "denied", "reason": "provider_budget_integration_mismatch"}
        else:
            budget_result = {"decision": "admitted", "reason": "provider_budget_configured"}
    else:
        approval_result = {"decision": "admitted", "reason": "not_a_provider_integration"}
        budget_result = {"decision": "admitted", "reason": "not_a_provider_integration"}

    resource_result = evaluate_resource_admission(telemetry, resource_demand, policy, now=now)
    if is_provider and isinstance(provider_budget, ProviderBudget):
        if requested_tokens > provider_budget.maximum_output_tokens_per_invocation:
            budget_result = {"decision": "denied", "reason": "per_invocation_output_token_limit"}

    integration_id = runtime.participant.integration_id
    if not isinstance(integration_id, str) or not integration_id:
        raise AdmissionError("participant integration identity is invalid")
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
        if state == "unknown":
            state = "denied"
        if state == "admitted" and is_provider:
            lease = db.execute(
                "SELECT * FROM dispatch_leases WHERE lease_key=?",
                (GLOBAL_PROVIDER_LEASE,),
            ).fetchone()
            if lease is not None:
                state = "deferred" if lease["state"] == "active" else "denied"
                decision["decision"] = state
                decision["reason"] = (
                    "global_provider_dispatch_busy"
                    if lease["state"] == "active"
                    else "global_provider_lease_abandoned"
                )
        if state == "admitted" and is_provider:
            row = db.execute(
                """SELECT requests_reserved,output_tokens_reserved,output_tokens_used
                   FROM provider_budget_usage WHERE integration_id=? AND budget_day_utc=?""",
                (integration_id, budget_day),
            ).fetchone()
            requests = row["requests_reserved"] if row else 0
            reserved = row["output_tokens_reserved"] if row else 0
            used = row["output_tokens_used"] if row else 0
            if requests + 1 > provider_budget.maximum_requests_per_utc_day:
                state = "rate_limited"
                decision.update({"decision": state, "reason": "daily_request_budget_exhausted"})
            elif reserved + used + requested_tokens > provider_budget.maximum_reserved_output_tokens_per_utc_day:
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
            "SELECT status,adapter_id FROM participant_invocations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None or row["status"] != "admitted":
            return False
        if row["adapter_id"] == "openai_compatible_chat":
            lease = db.execute(
                "SELECT state FROM dispatch_leases WHERE invocation_id=?",
                (invocation_id,),
            ).fetchone()
            if lease is None or lease["state"] != "active":
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


def finalize_invocation(store, invocation_id, status, *, usage=None, error_code=None, error_message=None, provider_settled=False):
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise ValueError("invocation ID is invalid")
    if not isinstance(provider_settled, bool):
        raise ValueError("provider_settled must be a boolean")
    if status not in TERMINAL_STATUSES - {"denied", "abandoned"}:
        raise ValueError("invocation terminal status is invalid")
    if usage is not None:
        if not isinstance(usage, dict) or set(usage) - {"input_tokens", "output_tokens", "total_tokens"}:
            raise ValueError("invocation usage must contain only token counters")
        for key, value in usage.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invocation usage {key} must be a non-negative integer")
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
        previous_status = row["status"]
        if previous_status in TERMINAL_STATUSES and not (previous_status == "abandoned" and provider_settled):
            return False

        lease = db.execute(
            "SELECT * FROM dispatch_leases WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        provider_invocation = row["adapter_id"] == "openai_compatible_chat"

        # An admitted invocation has not crossed the worker's atomic start
        # transition. It may only be cancelled; that transaction wins against
        # mark_invocation_running and proves no provider request was started.
        not_started_cancel = previous_status == "admitted" and status == "cancelled"
        if previous_status == "admitted" and not not_started_cancel:
            return False
        if previous_status not in {"admitted", "running", "abandoned"}:
            return False
        if provider_invocation:
            if lease is None:
                return False
            if not_started_cancel:
                if lease["state"] != "active":
                    return False
            elif previous_status == "running":
                if lease["state"] != "active" and not provider_settled:
                    return False
            elif previous_status == "abandoned" and not provider_settled:
                return False
        elif lease is not None:
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
        if lease is not None:
            # A not-started cancellation is safe to release: the serialized
            # status transition prevented the worker from entering running.
            if not_started_cancel or provider_settled:
                db.execute("DELETE FROM dispatch_leases WHERE invocation_id=?", (invocation_id,))
            else:
                db.execute(
                    "UPDATE dispatch_leases SET state='abandoned',heartbeat_at=? WHERE invocation_id=?",
                    (now, invocation_id),
                )
        if not_started_cancel and row["budget_day_utc"] is not None:
            db.execute(
                """UPDATE provider_budget_usage
                   SET requests_reserved=MAX(0,requests_reserved-1),
                       output_tokens_reserved=MAX(0,output_tokens_reserved-?)
                   WHERE integration_id=? AND budget_day_utc=?""",
                (row["requested_output_tokens"], row["integration_id"], row["budget_day_utc"]),
            )
        # Unknown usage retains the full reservation: releasing it would permit
        # daily-budget oversubscription when the provider may have processed work.
        elif usage is not None and row["budget_day_utc"] is not None:
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
            "previous_status": previous_status,
            "status": status,
            "provider_settled": bool(provider_settled or not_started_cancel),
            "not_started_cancellation": not_started_cancel,
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
    from datetime import timedelta
    cutoff = (now.astimezone(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat().replace("+00:00", "Z")

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
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise ValueError("invocation ID is invalid")
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
