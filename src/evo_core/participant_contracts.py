"""Versioned, code-owned participant and invocation contracts.

These contracts describe supported interfaces. They do not grant authorization,
availability, compliance approval, or permission to dispatch live work.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol


IMPLEMENTATION_VERSION = "0.2.0"


@dataclass(frozen=True)
class AdapterContract:
    adapter_id: str
    contract_version: int
    component_type: str
    implementation_version: str
    capabilities: tuple[str, ...]
    execution_location: str


_ADAPTERS = {
    "openai_compatible_chat": AdapterContract(
        "openai_compatible_chat", 1, "model", IMPLEMENTATION_VERSION,
        ("text_generation", "tool_call_generation"), "endpoint",
    ),
    "evo_assistant_runtime": AdapterContract(
        "evo_assistant_runtime", 1, "assistant_runtime", IMPLEMENTATION_VERSION,
        ("assistant_composition",), "local_process",
    ),
    "evo_command_policy": AdapterContract(
        "evo_command_policy", 1, "command_policy", IMPLEMENTATION_VERSION,
        ("command_policy_restriction",), "local_process",
    ),
    "evo_deterministic_verifier": AdapterContract(
        "evo_deterministic_verifier", 1, "deterministic_verifier", IMPLEMENTATION_VERSION,
        ("structured_output_validation", "evidence_reference_validation"), "local_process",
    ),
}
ADAPTER_CONTRACTS: Mapping[str, AdapterContract] = MappingProxyType(_ADAPTERS)


class UnsupportedAdapterError(ValueError):
    pass


def resolve_adapter_contract(adapter_id: str, contract_version: int, component_type: str) -> AdapterContract:
    """Resolve only exact code-registered adapter/type/version combinations."""
    if not isinstance(adapter_id, str):
        raise UnsupportedAdapterError("adapter id must be a string")
    contract = ADAPTER_CONTRACTS.get(adapter_id)
    if contract is None:
        raise UnsupportedAdapterError(f"unsupported adapter id: {adapter_id}")
    if (
        isinstance(contract_version, bool)
        or not isinstance(contract_version, int)
        or contract_version != contract.contract_version
    ):
        raise UnsupportedAdapterError(f"unsupported contract version for adapter {adapter_id}")
    if component_type != contract.component_type:
        raise UnsupportedAdapterError(f"adapter {adapter_id} cannot bind component type {component_type}")
    return contract


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def stable_integration_id(adapter_id: str, endpoint_origin: str, model_id: str) -> str:
    """Stable opaque integration identity; never includes credentials or secret refs."""
    material = _canonical_json([adapter_id, endpoint_origin, model_id]).encode("utf-8")
    return "integration_" + sha256(material).hexdigest()[:32]


def stable_participant_id(
    integration_id: str,
    configuration_id: str,
    revision_id: str,
    component_key: str,
    component_version: int,
) -> str:
    material = _canonical_json([
        integration_id, configuration_id, revision_id, component_key, component_version,
    ]).encode("utf-8")
    return "participant_" + sha256(material).hexdigest()[:32]


@dataclass(frozen=True)
class ParticipantDescriptor:
    participant_id: str
    integration_id: str
    participant_type: str
    display_name: str
    adapter_id: str
    adapter_contract_version: int
    adapter_implementation_version: str
    capabilities: tuple[str, ...]
    input_contract_versions: tuple[int, ...]
    output_contract_versions: tuple[int, ...]
    execution_location: str
    availability: str
    availability_observed_at: str | None
    resource_requirements: tuple[tuple[str, str], ...]
    limits: tuple[tuple[str, int | float | str], ...]
    configuration_id: str
    configuration_revision_id: str
    component_key: str
    component_version: int
    compliance_reference: str | None = None


@dataclass(frozen=True)
class ContextReference:
    reference_id: str
    source_type: str
    scope: str
    trust_label: str


@dataclass(frozen=True)
class InvocationEnvelope:
    invocation_id: str
    parent_task_id: str | None
    participant_id: str
    adapter_id: str
    adapter_contract_version: int
    configuration_id: str
    configuration_revision_id: str
    component_key: str
    component_version: int
    project_id: str | None
    workspace_id: str | None
    objective: str
    task_role: str
    input_json: str
    context_references: tuple[ContextReference, ...]
    output_contract_json: str
    acceptance_criteria: tuple[str, ...]
    effective_permissions: tuple[str, ...]
    approval_requirements: tuple[str, ...]
    deadline_utc: str
    retry_limit: int
    remaining_budgets: tuple[tuple[str, int | float], ...]
    correlation_id: str


@dataclass(frozen=True)
class ParticipantEvent:
    event_id: str
    invocation_id: str
    participant_id: str
    sequence: int
    event_type: str
    occurred_at: str
    payload_json: str
    provenance: str


@dataclass(frozen=True)
class ParticipantResult:
    invocation_id: str
    participant_id: str
    status: str
    completed_at: str
    output_json: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage: tuple[tuple[str, int | float | str], ...] = ()
    evidence_references: tuple[str, ...] = ()
    partial_output: bool = False


class ParticipantAdapter(Protocol):
    """Adapter surface. Implementations are code-owned and called only after admission."""

    adapter_id: str
    contract_version: int

    def validate_component(self, component: Mapping[str, Any]) -> None: ...

    def bind_component(self, component: Mapping[str, Any], provenance: Mapping[str, str]) -> Any: ...

    def preflight(self, participant: Any, *, timeout_seconds: int) -> "AvailabilityEvidence": ...

    def probe_completion(self, participant: Any, *, timeout_seconds: int) -> "AvailabilityEvidence": ...

    def invoke(
        self, participant: Any, envelope: InvocationEnvelope
    ) -> Iterable["ParticipantEvent | ParticipantResult"]: ...


def _reject_json_constant(value):
    raise ValueError("non-standard JSON constant is not permitted")


def _unique_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def validate_participant_event(event: ParticipantEvent, *, maximum_payload_bytes=65536) -> None:
    allowed_types = {"started", "progress", "text_delta", "tool_call_proposed", "usage", "diagnostic"}
    if not isinstance(event, ParticipantEvent):
        raise TypeError("event must be a ParticipantEvent")
    if any(not isinstance(value, str) or not value for value in (event.event_id, event.invocation_id, event.participant_id)):
        raise ValueError("participant event identity fields are required")
    if isinstance(event.sequence, bool) or not isinstance(event.sequence, int) or event.sequence < 0:
        raise ValueError("participant event sequence must be a non-negative integer")
    if not isinstance(event.event_type, str) or event.event_type not in allowed_types:
        raise ValueError("participant event type is unsupported")
    if not isinstance(event.provenance, str) or not event.provenance or len(event.provenance) > 512:
        raise ValueError("participant event provenance is invalid")
    if not isinstance(event.payload_json, str):
        raise ValueError("participant event payload must be JSON text")
    try:
        encoded = event.payload_json.encode("utf-8")
        if len(encoded) > maximum_payload_bytes:
            raise ValueError("participant event payload exceeds the size limit")
        payload = json.loads(
            event.payload_json,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object_pairs,
        )
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        raise ValueError("participant event payload is invalid or oversized") from exc
    if not isinstance(payload, dict):
        raise ValueError("participant event payload must be a JSON object")


def validate_participant_result(result: ParticipantResult) -> None:
    """Reject inconsistent terminal results before they can be persisted as success."""
    terminal = {
        "succeeded", "malformed_output", "unavailable", "denied", "rate_limited",
        "timed_out", "cancelled", "budget_exhausted", "provider_failed",
    }
    if not isinstance(result.status, str) or result.status not in terminal:
        raise ValueError("participant result has an unknown terminal status")
    if result.status == "succeeded":
        if result.output_json is None or result.error_code is not None or result.error_message is not None or result.partial_output:
            raise ValueError("successful participant result must contain complete output only")
        try:
            json.loads(
                result.output_json,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_unique_object_pairs,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("successful participant output must be valid JSON") from exc
    elif result.output_json is not None and not result.partial_output:
        raise ValueError("non-success output must be explicitly marked partial")
    if result.error_message is not None and len(result.error_message) > 2000:
        raise ValueError("participant error message exceeds the storage limit")


@dataclass(frozen=True)
class AvailabilityEvidence:
    transport_reachable: bool | None
    model_advertised: bool | None
    completion_verified: bool | None
    observed_at_utc: str
    evidence_reference: str | None = None

    def __post_init__(self):
        for field_name in ("transport_reachable", "model_advertised", "completion_verified"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field_name} must be boolean or unknown")
        if self.completion_verified is True and self.transport_reachable is not True:
            raise ValueError("verified completion requires observed transport reachability")

    @property
    def state(self) -> str:
        if self.completion_verified is True:
            return "available"
        if self.completion_verified is False:
            return "unavailable"
        return "unknown"


@dataclass(frozen=True)
class AuthorizationDecision:
    authorized: bool
    reason: str
    authority_source: str


@dataclass(frozen=True)
class ComplianceApproval:
    status: str
    origin: str
    adapter_id: str
    approved_use: str
    reviewed_at: str | None
    terms_reference: str | None
    data_handling_reference: str | None

    def __post_init__(self):
        if not isinstance(self.status, str) or self.status not in {"local_only", "approved", "restricted", "suspended", "unknown"}:
            raise ValueError("invalid compliance status")


@dataclass(frozen=True)
class DeterministicVerificationResult:
    valid: bool
    issues: tuple[str, ...]
    output_bytes: int


def verify_structured_output(settings: Mapping[str, Any], output: str) -> DeterministicVerificationResult:
    """Validate the deliberately small, deterministic verifier contract."""
    if not isinstance(settings, Mapping) or not isinstance(output, str):
        raise TypeError("verifier settings and output must be mappings and text")
    maximum = settings.get("max_output_bytes")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 1_048_576:
        raise ValueError("verifier maximum output size is invalid")
    try:
        encoded = output.encode("utf-8")
    except UnicodeEncodeError:
        return DeterministicVerificationResult(False, ("invalid_utf8_text",), 0)
    if len(encoded) > maximum:
        return DeterministicVerificationResult(False, ("output_exceeds_size_limit",), len(encoded))
    try:
        value = json.loads(
            output,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object_pairs,
        )
    except (TypeError, ValueError):
        return DeterministicVerificationResult(False, ("malformed_json",), len(encoded))
    if not isinstance(value, dict):
        return DeterministicVerificationResult(False, ("output_must_be_object",), len(encoded))
    required = settings.get("required_fields")
    evidence_fields = settings.get("evidence_fields")
    allow_additional = settings.get("allow_additional_fields")
    if (
        not isinstance(required, list)
        or not isinstance(evidence_fields, list)
        or not isinstance(allow_additional, bool)
        or any(not isinstance(field, str) for field in required + evidence_fields)
        or len(required) != len(set(required))
        or len(evidence_fields) != len(set(evidence_fields))
        or not set(evidence_fields).issubset(set(required))
    ):
        raise ValueError("verifier settings are invalid")
    issues = []
    for field in required:
        if field not in value:
            issues.append("missing_required_field:" + field)
    if not allow_additional:
        extras = set(value) - set(required)
        issues.extend("unexpected_field:" + field for field in sorted(extras))
    for field in evidence_fields:
        references = value.get(field)
        if not isinstance(references, list) or not references or any(
            not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 2048
            or any(ord(char) < 32 for char in reference)
            for reference in (references if isinstance(references, list) else [])
        ):
            issues.append("invalid_evidence_references:" + field)
    return DeterministicVerificationResult(not issues, tuple(issues), len(encoded))
