"""Bounded deterministic verifier participant.

This is a local, non-model participant. It validates the shape and size of
structured output and evidence-reference strings; it does not execute tools,
resolve references, prove claims, or grant authority.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping
from uuid import uuid4

from .participant_contracts import (
    AvailabilityEvidence,
    DeterministicVerificationResult,
    InvocationEnvelope,
    ParticipantDescriptor,
    ParticipantEvent,
    ParticipantResult,
    resolve_adapter_contract,
    stable_integration_id,
    stable_participant_id,
    validate_participant_event,
    validate_participant_result,
    verify_structured_output,
)


class DeterministicVerifierError(RuntimeError):
    """Safe verifier failure."""


class VerifierDispatchDisabledError(DeterministicVerifierError):
    """Verifier invocation requires the P3.5 authorization/admission boundary."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_json_object(value: str, label: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise DeterministicVerifierError(f"{label} must be JSON text")

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise DeterministicVerifierError(f"{label} is malformed") from exc
    if not isinstance(parsed, dict):
        raise DeterministicVerifierError(f"{label} must be a JSON object")
    return parsed


@dataclass(frozen=True)
class BoundDeterministicVerifier:
    participant_id: str
    project_id: str
    workspace_id: str
    configuration_id: str
    configuration_revision_id: str
    component_key: str
    component_version: int
    required_fields: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    max_output_bytes: int
    allow_additional_fields: bool


class DeterministicVerifierParticipantAdapter:
    """Code-owned local verifier with no arbitrary tool or network capability."""

    adapter_id = "evo_deterministic_verifier"
    contract_version = 1
    _MAX_INPUT_BYTES = 1_052_672

    def __init__(self, *, dispatch_authorizer=None):
        if dispatch_authorizer is not None and not callable(dispatch_authorizer):
            raise TypeError("dispatch_authorizer must be callable or None")
        self._dispatch_authorizer = dispatch_authorizer

    def validate_component(self, component: Mapping[str, Any]) -> None:
        if not isinstance(component, Mapping) or set(component) != {
            "type", "component_version", "adapter", "settings"
        }:
            raise DeterministicVerifierError("verifier component has unsupported fields")
        if component.get("type") != "deterministic_verifier":
            raise DeterministicVerifierError("verifier adapter requires deterministic_verifier component")
        if isinstance(component.get("component_version"), bool) or component.get("component_version") != 1:
            raise DeterministicVerifierError("verifier component version is unsupported")
        adapter = component.get("adapter")
        if not isinstance(adapter, Mapping):
            raise DeterministicVerifierError("verifier adapter declaration is invalid")
        try:
            resolve_adapter_contract(
                adapter.get("id"), adapter.get("contract_version"), "deterministic_verifier"
            )
        except (TypeError, ValueError) as exc:
            raise DeterministicVerifierError("verifier adapter declaration is unsupported") from exc
        if adapter.get("id") != self.adapter_id or adapter.get("contract_version") != self.contract_version:
            raise DeterministicVerifierError("verifier component targets another adapter version")
        settings = component.get("settings")
        required = {
            "required_fields", "evidence_fields", "max_output_bytes", "allow_additional_fields"
        }
        if not isinstance(settings, Mapping) or set(settings) != required:
            raise DeterministicVerifierError("verifier settings are incomplete or contain unknown fields")
        for name in ("required_fields", "evidence_fields"):
            values = settings.get(name)
            if (
                not isinstance(values, (list, tuple))
                or len(values) > 128
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                raise DeterministicVerifierError(f"verifier {name} is invalid")
        if not set(settings["evidence_fields"]).issubset(set(settings["required_fields"])):
            raise DeterministicVerifierError("evidence fields must be required fields")
        maximum = settings.get("max_output_bytes")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 1_048_576:
            raise DeterministicVerifierError("verifier output limit is invalid")
        if not isinstance(settings.get("allow_additional_fields"), bool):
            raise DeterministicVerifierError("allow_additional_fields must be boolean")

    def bind_component(
        self,
        component: Mapping[str, Any],
        provenance: Mapping[str, Any],
        *,
        secret_values=None,
        runtime_settings=None,
    ) -> BoundDeterministicVerifier:
        self.validate_component(component)
        if secret_values not in (None, {}):
            raise DeterministicVerifierError("deterministic verifier does not accept secrets")
        if runtime_settings not in (None, {}):
            raise DeterministicVerifierError("deterministic verifier does not accept runtime settings")
        required_provenance = (
            "participant_id", "project_id", "workspace_id", "configuration_id",
            "configuration_revision_id", "component_key", "component_version",
        )
        if not isinstance(provenance, Mapping) or any(
            not isinstance(provenance.get(key), str) or not provenance.get(key)
            for key in required_provenance[:-1]
        ):
            raise DeterministicVerifierError("verifier provenance is incomplete")
        if isinstance(provenance.get("component_version"), bool) or provenance.get("component_version") != 1:
            raise DeterministicVerifierError("verifier provenance component version is invalid")
        settings = component["settings"]
        return BoundDeterministicVerifier(
            participant_id=provenance["participant_id"],
            project_id=provenance["project_id"],
            workspace_id=provenance["workspace_id"],
            configuration_id=provenance["configuration_id"],
            configuration_revision_id=provenance["configuration_revision_id"],
            component_key=provenance["component_key"],
            component_version=provenance["component_version"],
            required_fields=tuple(settings["required_fields"]),
            evidence_fields=tuple(settings["evidence_fields"]),
            max_output_bytes=settings["max_output_bytes"],
            allow_additional_fields=settings["allow_additional_fields"],
        )

    def describe(self, participant: BoundDeterministicVerifier) -> ParticipantDescriptor:
        if not isinstance(participant, BoundDeterministicVerifier):
            raise DeterministicVerifierError("bound verifier is invalid")
        contract = resolve_adapter_contract(self.adapter_id, self.contract_version, "deterministic_verifier")
        integration_id = stable_integration_id(
            self.adapter_id, "local://evo", "structured-output-verifier"
        )
        return ParticipantDescriptor(
            participant_id=participant.participant_id,
            integration_id=integration_id,
            participant_type="deterministic_tool",
            display_name="Structured output verifier",
            adapter_id=self.adapter_id,
            adapter_contract_version=self.contract_version,
            adapter_implementation_version=contract.implementation_version,
            capabilities=contract.capabilities,
            input_contract_versions=(1,),
            output_contract_versions=(1,),
            execution_location="local_process",
            availability="available",
            availability_observed_at=_utc_now(),
            resource_requirements=(("cpu", "bounded_local_json_validation"),),
            limits=(("max_output_bytes", participant.max_output_bytes),),
            configuration_id=participant.configuration_id,
            configuration_revision_id=participant.configuration_revision_id,
            component_key=participant.component_key,
            component_version=participant.component_version,
            compliance_reference="local_only",
        )

    def preflight(self, participant: BoundDeterministicVerifier, *, timeout_seconds: int) -> AvailabilityEvidence:
        if not isinstance(participant, BoundDeterministicVerifier):
            raise DeterministicVerifierError("bound verifier is invalid")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds is invalid")
        return AvailabilityEvidence(None, None, None, _utc_now(), "local verifier loaded; no invocation performed")

    def probe_completion(self, participant: BoundDeterministicVerifier, *, timeout_seconds: int) -> AvailabilityEvidence:
        if not isinstance(participant, BoundDeterministicVerifier):
            raise DeterministicVerifierError("bound verifier is invalid")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds is invalid")
        sample = {}
        for field in participant.required_fields:
            sample[field] = ["evo://probe"] if field in participant.evidence_fields else "probe"
        outcome = verify_structured_output(
            {
                "required_fields": list(participant.required_fields),
                "evidence_fields": list(participant.evidence_fields),
                "max_output_bytes": participant.max_output_bytes,
                "allow_additional_fields": participant.allow_additional_fields,
            },
            json.dumps(sample, separators=(",", ":")),
        )
        return AvailabilityEvidence(True, True, outcome.valid, _utc_now(), "local deterministic self-test")

    def invoke(self, participant: BoundDeterministicVerifier, envelope: InvocationEnvelope, *, cancellation_event=None):
        if not isinstance(participant, BoundDeterministicVerifier):
            raise DeterministicVerifierError("bound verifier is invalid")
        if not isinstance(envelope, InvocationEnvelope):
            raise TypeError("invocation envelope is required")
        identity = (
            envelope.participant_id == participant.participant_id
            and envelope.adapter_id == self.adapter_id
            and envelope.adapter_contract_version == self.contract_version
            and envelope.configuration_id == participant.configuration_id
            and envelope.configuration_revision_id == participant.configuration_revision_id
            and envelope.component_key == participant.component_key
            and envelope.component_version == participant.component_version
            and envelope.project_id == participant.project_id
            and envelope.workspace_id == participant.workspace_id
        )
        if not identity:
            raise DeterministicVerifierError("invocation identity does not match the bound verifier")
        if self._dispatch_authorizer is None:
            raise VerifierDispatchDisabledError("verifier dispatch requires P3.5 authorization and admission")
        try:
            authorized = self._dispatch_authorizer(participant, envelope)
        except Exception as exc:
            raise VerifierDispatchDisabledError("verifier invocation was not authorized") from exc
        if authorized is not True:
            raise VerifierDispatchDisabledError("verifier invocation was not authorized")

        now = datetime.now(timezone.utc)
        try:
            deadline = datetime.fromisoformat(envelope.deadline_utc.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DeterministicVerifierError("invocation deadline is invalid") from exc
        if deadline.tzinfo is None:
            raise DeterministicVerifierError("invocation deadline must include a timezone")
        if deadline <= now:
            yield ParticipantResult(
                envelope.invocation_id, participant.participant_id, "timed_out", _utc_now(),
                error_code="deadline_expired", error_message="invocation deadline expired",
            )
            return
        if cancellation_event is not None and cancellation_event.is_set():
            yield ParticipantResult(
                envelope.invocation_id, participant.participant_id, "cancelled", _utc_now(),
                error_code="cancelled", error_message="invocation was cancelled before verification",
            )
            return

        started = ParticipantEvent(
            str(uuid4()), envelope.invocation_id, participant.participant_id, 0,
            "started", _utc_now(), "{}", "evo_deterministic_verifier",
        )
        validate_participant_event(started)
        yield started

        if cancellation_event is not None and cancellation_event.is_set():
            yield ParticipantResult(
                envelope.invocation_id, participant.participant_id, "cancelled", _utc_now(),
                error_code="cancelled", error_message="invocation was cancelled before verification",
            )
            return
        if datetime.now(timezone.utc) >= deadline:
            yield ParticipantResult(
                envelope.invocation_id, participant.participant_id, "timed_out", _utc_now(),
                error_code="deadline_expired", error_message="invocation deadline expired",
            )
            return

        if len(envelope.input_json.encode("utf-8")) > self._MAX_INPUT_BYTES:
            yield ParticipantResult(
                envelope.invocation_id, participant.participant_id, "malformed_output", _utc_now(),
                error_code="input_too_large", error_message="verifier input exceeds the size limit",
            )
            return
        try:
            request = _strict_json_object(envelope.input_json, "verifier input")
            if set(request) != {"output"} or not isinstance(request["output"], str):
                raise DeterministicVerifierError("verifier input must contain only output text")
            outcome = verify_structured_output(
                {
                    "required_fields": list(participant.required_fields),
                    "evidence_fields": list(participant.evidence_fields),
                    "max_output_bytes": participant.max_output_bytes,
                    "allow_additional_fields": participant.allow_additional_fields,
                },
                request["output"],
            )
            evidence = []
            if "malformed_json" not in outcome.issues and "output_must_be_object" not in outcome.issues:
                parsed = _strict_json_object(request["output"], "participant output")
                for field in participant.evidence_fields:
                    values = parsed.get(field)
                    if isinstance(values, list):
                        evidence.extend(value for value in values if isinstance(value, str) and value.strip())
            result_payload = {
                "valid": outcome.valid,
                "issues": list(outcome.issues),
                "output_bytes": outcome.output_bytes,
                "evidence_reference_shape_only": True,
            }
            result = ParticipantResult(
                envelope.invocation_id,
                participant.participant_id,
                "succeeded",
                _utc_now(),
                output_json=json.dumps(result_payload, sort_keys=True, separators=(",", ":")),
                evidence_references=tuple(evidence[:128]) if outcome.valid else (),
            )
        except (DeterministicVerifierError, TypeError, ValueError, UnicodeEncodeError):
            result = ParticipantResult(
                envelope.invocation_id, participant.participant_id, "malformed_output", _utc_now(),
                error_code="invalid_verifier_input", error_message="verifier input or target output is invalid",
            )
        validate_participant_result(result)
        yield result
