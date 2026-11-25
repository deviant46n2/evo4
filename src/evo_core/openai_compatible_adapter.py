"""Registry adapter for the OpenAI-compatible chat participant.

This adapter consumes the connection-pinned transport. It has no dispatch
authority of its own: invocation and completion probes require a code-supplied
authorization callback, which is intentionally absent before P3.5.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from queue import Empty, Queue
import threading
import time
from typing import Any, Mapping
from uuid import uuid4

from .participant_contracts import (
    AvailabilityEvidence,
    InvocationEnvelope,
    ParticipantEvent,
    ParticipantResult,
    resolve_adapter_contract,
    validate_participant_result,
)
from .provider import (
    InvalidToolCallError,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderHTTPError,
    ProviderMalformedResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from .provider_endpoint import EndpointPolicy, PinnedProviderTransport


class ParticipantAdapterError(RuntimeError):
    """Safe adapter failure; messages never include provider credentials."""


class ParticipantDispatchDisabledError(ParticipantAdapterError):
    """No P3.5 dispatch authorization callback has been installed."""


@dataclass(frozen=True)
class BoundOpenAICompatibleParticipant:
    participant_id: str
    project_id: str
    workspace_id: str
    configuration_id: str
    configuration_revision_id: str
    component_key: str
    component_version: int
    endpoint: str
    model: str
    timeout_seconds: int
    max_output_tokens: int
    temperature: float


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_json_object(value, label):
    if not isinstance(value, str):
        raise ParticipantAdapterError(f"{label} must be JSON text")

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=unique_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ParticipantAdapterError(f"{label} is malformed") from exc
    if not isinstance(parsed, dict):
        raise ParticipantAdapterError(f"{label} must be a JSON object")
    return parsed


class OpenAICompatibleParticipantAdapter:
    __slots__ = (
        "_endpoint_policy", "_resolver", "_provider_factory",
        "_dispatch_authorizer", "_providers", "_sealed",
    )
    adapter_id = "openai_compatible_chat"
    contract_version = 1

    def __init__(
        self,
        *,
        allowed_origins=(),
        resolver=None,
        provider_factory=OpenAICompatibleProvider,
        dispatch_authorizer=None,
    ):
        object.__setattr__(self, "_endpoint_policy", EndpointPolicy(tuple(allowed_origins)))
        object.__setattr__(self, "_resolver", resolver)
        object.__setattr__(self, "_provider_factory", provider_factory)
        object.__setattr__(self, "_dispatch_authorizer", dispatch_authorizer)
        object.__setattr__(self, "_providers", {})
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("participant adapter configuration is immutable")
        object.__setattr__(self, name, value)

    def _provider_for(self, participant):
        if not isinstance(participant, BoundOpenAICompatibleParticipant):
            raise ParticipantAdapterError("bound participant is invalid")
        provider = self._providers.get(participant.participant_id)
        if provider is None:
            raise ParticipantAdapterError("bound participant is not owned by this adapter")
        return provider

    def validate_component(self, component: Mapping[str, Any]) -> None:
        if not isinstance(component, Mapping) or component.get("type") != "model":
            raise ParticipantAdapterError("OpenAI-compatible adapter requires a model component")
        adapter = component.get("adapter")
        if not isinstance(adapter, Mapping):
            raise ParticipantAdapterError("model adapter declaration is invalid")
        try:
            resolve_adapter_contract(
                adapter.get("id"), adapter.get("contract_version"), "model"
            )
        except (TypeError, ValueError) as exc:
            raise ParticipantAdapterError("model adapter declaration is unsupported") from exc
        if adapter.get("id") != self.adapter_id or adapter.get("contract_version") != self.contract_version:
            raise ParticipantAdapterError("model component does not target this adapter version")
        settings = component.get("settings")
        if not isinstance(settings, Mapping) or set(settings) != {
            "endpoint", "model", "timeout_seconds"
        }:
            raise ParticipantAdapterError("model settings are incomplete or contain unknown fields")
        endpoint = settings.get("endpoint")
        model = settings.get("model")
        timeout = settings.get("timeout_seconds")
        if not isinstance(endpoint, str) or not endpoint:
            raise ParticipantAdapterError("model endpoint is invalid")
        if not isinstance(model, str) or not model.strip() or len(model) > 512:
            raise ParticipantAdapterError("model identifier is invalid")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
            raise ParticipantAdapterError("model timeout is invalid")
        if isinstance(component.get("component_version"), bool) or component.get("component_version") != 1:
            raise ParticipantAdapterError("model component version is unsupported")
        if set(component) - {"type", "component_version", "adapter", "settings", "secret_refs"}:
            raise ParticipantAdapterError("model component contains unsupported fields")
        secret_refs = component.get("secret_refs", {})
        if (
            not isinstance(secret_refs, Mapping)
            or set(secret_refs) - {"api_key"}
            or any(
                not isinstance(value, str)
                or re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", value) is None
                for value in secret_refs.values()
            )
        ):
            raise ParticipantAdapterError("model secret references are unsupported")
        transport = PinnedProviderTransport(self._endpoint_policy, resolver=self._resolver)
        try:
            transport.validate_origin(endpoint)
        except Exception as exc:
            raise ParticipantAdapterError("model endpoint violates operator transport policy") from exc

    def bind_component(
        self,
        component: Mapping[str, Any],
        provenance: Mapping[str, str],
        *,
        secret_values: Mapping[str, str] | None = None,
        runtime_settings: Mapping[str, Any] | None = None,
    ) -> BoundOpenAICompatibleParticipant:
        self.validate_component(component)
        if not isinstance(provenance, Mapping):
            raise ParticipantAdapterError("participant provenance is required")
        required_provenance = (
            "participant_id", "project_id", "workspace_id", "configuration_id",
            "configuration_revision_id", "component_key", "component_version",
        )
        if any(key not in provenance for key in required_provenance):
            raise ParticipantAdapterError("complete participant provenance is required")
        participant_id = provenance.get("participant_id")
        if any(not isinstance(provenance.get(key), str) or not provenance.get(key) for key in required_provenance[:-1]):
            raise ParticipantAdapterError("participant provenance identity is invalid")
        component_version = provenance.get("component_version")
        if isinstance(component_version, bool) or not isinstance(component_version, int) or component_version != 1:
            raise ParticipantAdapterError("participant component version is invalid")
        secrets = secret_values or {}
        if not isinstance(secrets, Mapping) or set(secrets) - {"api_key"}:
            raise ParticipantAdapterError("resolved provider secret material is invalid")
        api_key = secrets.get("api_key", "no-key")
        if not isinstance(api_key, str) or not api_key:
            raise ParticipantAdapterError("resolved provider credential is invalid")
        if bool(component.get("secret_refs")) != ("api_key" in secrets):
            raise ParticipantAdapterError("resolved provider credentials do not match declared secret references")
        if runtime_settings is not None and not isinstance(runtime_settings, Mapping):
            raise ParticipantAdapterError("assistant generation settings are invalid")
        generation = runtime_settings or {}
        max_output_tokens = generation.get("max_output_tokens", 32768)
        temperature = generation.get("temperature", 0.2)
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 1 <= max_output_tokens <= 32768
            or isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= temperature <= 2
        ):
            raise ParticipantAdapterError("assistant generation settings are invalid")
        settings = component["settings"]
        transport = PinnedProviderTransport(self._endpoint_policy, resolver=self._resolver)
        try:
            provider = self._provider_factory(
                settings["endpoint"], api_key, settings["model"],
                settings["timeout_seconds"], transport=transport,
            )
        except Exception as exc:
            raise ParticipantAdapterError("provider participant could not be constructed") from exc
        self._providers[participant_id] = provider
        return BoundOpenAICompatibleParticipant(
            participant_id=participant_id,
            project_id=provenance["project_id"],
            workspace_id=provenance["workspace_id"],
            configuration_id=provenance["configuration_id"],
            configuration_revision_id=provenance["configuration_revision_id"],
            component_key=provenance["component_key"],
            component_version=component_version,
            endpoint=settings["endpoint"],
            model=settings["model"],
            timeout_seconds=settings["timeout_seconds"],
            max_output_tokens=max_output_tokens,
            temperature=float(temperature),
        )

    def preflight(
        self,
        participant: BoundOpenAICompatibleParticipant,
        *,
        timeout_seconds: int,
    ) -> AvailabilityEvidence:
        """Check transport/model advertisement only; never issue a completion."""
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 10:
            raise ValueError("preflight timeout must be between 1 and 10 seconds")
        provider = self._provider_for(participant)
        try:
            models = provider.list_models(timeout_seconds=timeout_seconds)
            return AvailabilityEvidence(
                True, participant.model in models, None, _utc_now(),
                "openai_compatible:/v1/models",
            )
        except ProviderHTTPError as exc:
            if exc.status_code in {404, 405, 501}:
                return AvailabilityEvidence(
                    True, None, None, _utc_now(),
                    "openai_compatible:model_listing_unsupported",
                )
            return AvailabilityEvidence(
                True, None, None, _utc_now(),
                "openai_compatible:model_listing_http_error",
            )
        except (InvalidToolCallError, ProviderMalformedResponseError):
            return AvailabilityEvidence(
                True, None, None, _utc_now(),
                "openai_compatible:model_listing_malformed",
            )
        except (ProviderTimeoutError, ProviderTransportError):
            return AvailabilityEvidence(
                False, None, None, _utc_now(),
                "openai_compatible:model_listing_unreachable",
            )
        except ProviderError:
            return AvailabilityEvidence(
                None, None, None, _utc_now(),
                "openai_compatible:model_listing_unverified",
            )
        
    def probe_completion(
        self,
        participant: BoundOpenAICompatibleParticipant,
        *,
        timeout_seconds: int,
    ) -> AvailabilityEvidence:
        """Completion probes are billable invocations and remain P3.5-gated."""
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 30:
            raise ValueError("completion probe timeout must be between 1 and 30 seconds")
        self._authorize("availability_probe", participant, None)
        timeout = min(participant.timeout_seconds, timeout_seconds)
        try:
            result = self._provider_for(participant).chat(
                [{"role": "user", "content": "Reply with OK."}],
                max_tokens=1, temperature=0.0, timeout_seconds=timeout,
            )
            verified = bool(result.get("content")) and not result.get("truncated")
            return AvailabilityEvidence(
                True, None, verified, _utc_now(),
                "openai_compatible:bounded_completion_probe",
            )
        except (InvalidToolCallError, ProviderMalformedResponseError):
            return AvailabilityEvidence(
                True, None, False, _utc_now(),
                "openai_compatible:completion_probe_malformed",
            )
        except ProviderHTTPError:
            return AvailabilityEvidence(
                True, None, None, _utc_now(),
                "openai_compatible:completion_probe_rejected",
            )
        except ProviderTimeoutError:
            return AvailabilityEvidence(
                False, None, None, _utc_now(),
                "openai_compatible:completion_probe_timed_out",
            )
        except ProviderTransportError:
            return AvailabilityEvidence(
                False, None, None, _utc_now(),
                "openai_compatible:completion_probe_unreachable",
            )
        except ProviderError:
            # Transport-policy and transient failures do not prove that the
            # configured model is unavailable or that transport was reached.
            return AvailabilityEvidence(
                None, None, None, _utc_now(),
                "openai_compatible:completion_probe_unverified",
            )

    def _authorize(self, operation, participant, envelope):
        if self._dispatch_authorizer is None:
            raise ParticipantDispatchDisabledError(
                "Registry participant dispatch remains disabled until P3.5 authorization and admission"
            )
        try:
            authorized = self._dispatch_authorizer(operation, participant, envelope)
        except Exception as exc:
            raise ParticipantAdapterError("participant dispatch authorization failed") from exc
        if authorized is not True:
            raise ParticipantDispatchDisabledError("participant dispatch was not admitted")

    def invoke(self, participant, envelope: InvocationEnvelope, *, cancellation_event=None):
        """Yield normalized events and a terminal result after explicit admission.

        Cancellation suppresses further event forwarding and records a cancelled
        outcome. The blocking HTTP request itself remains bounded by timeout;
        the current transport cannot forcibly interrupt an in-flight read.
        """
        self._authorize("participant_invocation", participant, envelope)
        if not isinstance(envelope, InvocationEnvelope):
            raise TypeError("invocation envelope is required")
        for field_name in ("invocation_id", "objective", "task_role", "correlation_id"):
            field_value = getattr(envelope, field_name, None)
            if not isinstance(field_value, str) or not field_value.strip() or len(field_value) > 1024:
                raise ParticipantAdapterError(f"invocation {field_name} is invalid")
        if isinstance(envelope.retry_limit, bool) or not isinstance(envelope.retry_limit, int) or envelope.retry_limit != 0:
            raise ParticipantAdapterError("this adapter version does not implement retries")
        if (
            envelope.participant_id != participant.participant_id
            or envelope.adapter_id != self.adapter_id
            or envelope.adapter_contract_version != self.contract_version
            or envelope.project_id != participant.project_id
            or envelope.workspace_id != participant.workspace_id
            or envelope.configuration_id != participant.configuration_id
            or envelope.configuration_revision_id != participant.configuration_revision_id
            or envelope.component_key != participant.component_key
            or envelope.component_version != participant.component_version
        ):
            raise ParticipantAdapterError("invocation identity does not match the bound participant")
        if not isinstance(envelope.deadline_utc, str) or not envelope.deadline_utc:
            raise ParticipantAdapterError("invocation deadline is invalid")
        try:
            deadline = datetime.fromisoformat(envelope.deadline_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ParticipantAdapterError("invocation deadline is invalid") from exc
        if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
            raise ParticipantAdapterError("invocation deadline is expired or lacks a timezone")
        remaining_seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining_seconds <= 0:
            raise ParticipantAdapterError("invocation deadline has expired")
        request_timeout = min(float(participant.timeout_seconds), remaining_seconds)
        if not isinstance(envelope.input_json, str):
            raise ParticipantAdapterError("invocation input must be JSON text")
        try:
            input_bytes = envelope.input_json.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ParticipantAdapterError("invocation input encoding is invalid") from exc
        if len(input_bytes) > 1_048_576:
            raise ParticipantAdapterError("invocation input exceeds the size limit")
        request = _strict_json_object(envelope.input_json, "invocation input")
        try:
            json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise ParticipantAdapterError("invocation input contains unsupported values") from exc
        if set(request) - {"messages", "max_tokens", "temperature", "tools"}:
            raise ParticipantAdapterError("invocation input contains unsupported fields")
        messages = request.get("messages")
        max_tokens = request.get("max_tokens")
        temperature = request.get("temperature")
        if not isinstance(messages, list) or not messages or len(messages) > 256:
            raise ParticipantAdapterError("invocation messages are invalid")
        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"system", "developer", "user", "assistant", "tool"}
                or set(message) - {"role", "content", "name", "tool_call_id", "tool_calls"}
                or not isinstance(message.get("content", ""), (str, list, type(None)))
            ):
                raise ParticipantAdapterError("invocation message shape is invalid")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= participant.max_output_tokens
        ):
            raise ParticipantAdapterError("invocation output token limit exceeds the pinned assistant runtime")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or float(temperature) != participant.temperature
        ):
            raise ParticipantAdapterError("invocation temperature differs from the pinned assistant runtime")
        tools = request.get("tools")
        if tools is not None and (not isinstance(tools, list) or len(tools) > 128):
            raise ParticipantAdapterError("invocation tools are invalid")

        if cancellation_event is not None and not callable(getattr(cancellation_event, "is_set", None)):
            raise TypeError("cancellation_event must expose is_set()")
        events = Queue(maxsize=32)
        stop = threading.Event()
        provider_completed = threading.Event()
        finished = object()
        streamed_text = []

        def publish(event_type, payload):
            while not stop.is_set():
                try:
                    events.put((event_type, payload), timeout=0.1)
                    return
                except Exception:
                    continue

        def run_provider():
            try:
                result = self._provider_for(participant).chat(
                    messages, max_tokens=max_tokens, temperature=float(temperature),
                    tools=tools, on_token=lambda token: publish("text_delta", {"text": token}),
                    timeout_seconds=request_timeout,
                )
                provider_completed.set()
                publish("terminal", result)
            except Exception as exc:
                provider_completed.set()
                publish("error", exc)
            finally:
                publish("finished", finished)

        worker = threading.Thread(target=run_provider, name="evo-participant-provider", daemon=True)
        sequence = 0
        yield ParticipantEvent(
            str(uuid4()), envelope.invocation_id, participant.participant_id,
            sequence, "started", _utc_now(), "{}", "openai_compatible_chat/1",
        )
        sequence += 1
        if cancellation_event is not None and cancellation_event.is_set():
            cancelled = ParticipantResult(
                envelope.invocation_id, participant.participant_id,
                "cancelled", _utc_now(), error_code="cancelled",
                error_message="Cancellation was observed before provider dispatch",
            )
            validate_participant_result(cancelled)
            yield cancelled
            return
        worker.start()
        deadline_monotonic = time.monotonic() + request_timeout
        try:
            while True:
                if (
                    cancellation_event is not None
                    and cancellation_event.is_set()
                    and not provider_completed.is_set()
                ):
                    stop.set()
                    partial = {"content": "".join(streamed_text), "partial": True}
                    partial_json = json.dumps(partial, separators=(",", ":"), ensure_ascii=False) if streamed_text else None
                    cancelled = ParticipantResult(
                        envelope.invocation_id, participant.participant_id,
                        "cancelled", _utc_now(), output_json=partial_json,
                        error_code="cancelled",
                        error_message="Cancellation observed; provider request may continue until timeout",
                        partial_output=bool(partial_json),
                    )
                    validate_participant_result(cancelled)
                    yield cancelled
                    return
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    stop.set()
                    partial = {"content": "".join(streamed_text), "partial": True}
                    partial_json = json.dumps(partial, separators=(",", ":"), ensure_ascii=False) if streamed_text else None
                    result = ParticipantResult(
                        envelope.invocation_id, participant.participant_id,
                        "timed_out", _utc_now(), output_json=partial_json,
                        error_code="provider_timeout",
                        error_message="Provider response exceeded its bounded timeout",
                        partial_output=bool(partial_json),
                    )
                    validate_participant_result(result)
                    yield result
                    return
                try:
                    event_type, payload = events.get(timeout=min(0.1, remaining + 0.1))
                except Empty:
                    continue
                if event_type == "finished":
                    return
                if event_type == "text_delta":
                    streamed_text.append(payload.get("text", ""))
                    yield ParticipantEvent(
                        str(uuid4()), envelope.invocation_id, participant.participant_id,
                        sequence, "text_delta", _utc_now(),
                        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                        "openai_compatible_chat/1",
                    )
                    sequence += 1
                elif event_type == "terminal":
                    output = {
                        "content": payload.get("content", ""),
                        "tool_calls": payload.get("tool_calls", []),
                        "finish_reason": payload.get("finish_reason"),
                        "truncated": bool(payload.get("truncated")),
                    }
                    encoded = json.dumps(output, separators=(",", ":"), ensure_ascii=False)
                    status = "malformed_output" if output["truncated"] else "succeeded"
                    terminal = ParticipantResult(
                        envelope.invocation_id, participant.participant_id,
                        status, _utc_now(), output_json=encoded,
                        partial_output=output["truncated"],
                        usage=tuple(
                            (key, value) for key, value in (
                                ("prompt_tokens", payload.get("prompt_tokens")),
                                ("completion_tokens", payload.get("completion_tokens")),
                            ) if isinstance(value, (int, float)) and not isinstance(value, bool)
                        ),
                    )
                    validate_participant_result(terminal)
                    yield terminal
                    return
                elif event_type == "error":
                    exc = payload
                    if isinstance(exc, ProviderTimeoutError):
                        status, code, message = "timed_out", "provider_timeout", "Provider request timed out"
                    elif isinstance(exc, ProviderHTTPError) and exc.status_code == 429:
                        status, code, message = "rate_limited", "provider_rate_limited", "Provider rate limit was reached"
                    elif isinstance(exc, ProviderHTTPError) and exc.status_code in {404, 503}:
                        status, code, message = "unavailable", "provider_unavailable", "Configured provider or model is unavailable"
                    elif isinstance(exc, ProviderTransportError):
                        status, code, message = "unavailable", "provider_unavailable", "Provider transport is unavailable"
                    elif isinstance(exc, ProviderHTTPError) and exc.status_code in {401, 403}:
                        status, code, message = "denied", "provider_denied", "Provider rejected the request"
                    elif isinstance(exc, ProviderHTTPError) and exc.status_code in {408, 504}:
                        status, code, message = "timed_out", "provider_timeout", "Provider request timed out"
                    elif isinstance(exc, (InvalidToolCallError, ProviderMalformedResponseError)):
                        status, code, message = "malformed_output", "malformed_provider_output", "Provider returned malformed output"
                    else:
                        status, code, message = "provider_failed", "provider_error", "Provider request failed"
                    terminal = ParticipantResult(
                        envelope.invocation_id, participant.participant_id,
                        status, _utc_now(), error_code=code, error_message=message,
                    )
                    validate_participant_result(terminal)
                    yield terminal
                    return
        finally:
            stop.set()
