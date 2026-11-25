"""Registry adapter for the OpenAI-compatible chat participant.

This adapter consumes the connection-pinned transport. It has no dispatch
authority of its own: invocation and completion probes require a code-supplied
authorization callback, which is intentionally absent before P3.5.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from queue import Empty, Queue
import threading
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
)
from .provider_endpoint import EndpointPolicy, PinnedProviderTransport


class ParticipantAdapterError(RuntimeError):
    """Safe adapter failure; messages never include provider credentials."""


class ParticipantDispatchDisabledError(ParticipantAdapterError):
    """No P3.5 dispatch authorization callback has been installed."""


@dataclass(frozen=True)
class BoundOpenAICompatibleParticipant:
    participant_id: str
    endpoint: str
    model: str
    timeout_seconds: int
    provider: OpenAICompatibleProvider = field(repr=False, compare=False)


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
    except (TypeError, ValueError) as exc:
        raise ParticipantAdapterError(f"{label} is malformed") from exc
    if not isinstance(parsed, dict):
        raise ParticipantAdapterError(f"{label} must be a JSON object")
    return parsed


class OpenAICompatibleParticipantAdapter:
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
        self._endpoint_policy = EndpointPolicy(tuple(allowed_origins))
        self._resolver = resolver
        self._provider_factory = provider_factory
        self._dispatch_authorizer = dispatch_authorizer

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
        if set(component) - {"type", "component_version", "adapter", "settings", "secret_refs"}:
            raise ParticipantAdapterError("model component contains unsupported fields")
        secret_refs = component.get("secret_refs", {})
        if not isinstance(secret_refs, Mapping) or set(secret_refs) - {"api_key"}:
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
    ) -> BoundOpenAICompatibleParticipant:
        self.validate_component(component)
        if not isinstance(provenance, Mapping):
            raise ParticipantAdapterError("participant provenance is required")
        participant_id = provenance.get("participant_id")
        if not isinstance(participant_id, str) or not participant_id:
            raise ParticipantAdapterError("participant identity is required")
        secrets = secret_values or {}
        if not isinstance(secrets, Mapping) or set(secrets) - {"api_key"}:
            raise ParticipantAdapterError("resolved provider secret material is invalid")
        api_key = secrets.get("api_key", "no-key")
        if not isinstance(api_key, str) or not api_key:
            raise ParticipantAdapterError("resolved provider credential is invalid")
        settings = component["settings"]
        transport = PinnedProviderTransport(self._endpoint_policy, resolver=self._resolver)
        try:
            provider = self._provider_factory(
                settings["endpoint"], api_key, settings["model"],
                settings["timeout_seconds"], transport=transport,
            )
        except Exception as exc:
            raise ParticipantAdapterError("provider participant could not be constructed") from exc
        return BoundOpenAICompatibleParticipant(
            participant_id=participant_id,
            endpoint=settings["endpoint"],
            model=settings["model"],
            timeout_seconds=settings["timeout_seconds"],
            provider=provider,
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
        provider = participant.provider
        original_timeout = provider.timeout
        provider.timeout = min(original_timeout, timeout_seconds)
        try:
            models = provider.list_models()
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
        except ProviderMalformedResponseError:
            return AvailabilityEvidence(
                True, None, None, _utc_now(),
                "openai_compatible:model_listing_malformed",
            )
        except (ProviderTimeoutError, ProviderError):
            return AvailabilityEvidence(
                False, None, None, _utc_now(),
                "openai_compatible:model_listing_unreachable",
            )
        finally:
            provider.timeout = original_timeout

    def probe_completion(
        self,
        participant: BoundOpenAICompatibleParticipant,
        *,
        timeout_seconds: int,
    ) -> AvailabilityEvidence:
        """Completion probes are billable invocations and remain P3.5-gated."""
        self._authorize("availability_probe", participant, None)
        timeout = min(participant.timeout_seconds, timeout_seconds)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 30:
            raise ValueError("completion probe timeout must be between 1 and 30 seconds")
        try:
            result = participant.provider.chat(
                [{"role": "user", "content": "Reply with OK."}],
                max_tokens=1, temperature=0.0,
            )
            verified = bool(result.get("content")) and not result.get("truncated")
            return AvailabilityEvidence(
                True, None, verified, _utc_now(),
                "openai_compatible:bounded_completion_probe",
            )
        except ProviderError:
            return AvailabilityEvidence(
                True, None, False, _utc_now(),
                "openai_compatible:completion_probe_failed",
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

    def invoke(self, participant, envelope: InvocationEnvelope):
        """Yield normalized events and one terminal result after explicit admission."""
        self._authorize("participant_invocation", participant, envelope)
        if not isinstance(envelope, InvocationEnvelope):
            raise TypeError("invocation envelope is required")
        if (
            envelope.participant_id != participant.participant_id
            or envelope.adapter_id != self.adapter_id
            or envelope.adapter_contract_version != self.contract_version
        ):
            raise ParticipantAdapterError("invocation identity does not match the bound participant")
        if envelope.deadline_utc and not isinstance(envelope.deadline_utc, str):
            raise ParticipantAdapterError("invocation deadline is invalid")
        request = _strict_json_object(envelope.input_json, "invocation input")
        if set(request) - {"messages", "max_tokens", "temperature", "tools"}:
            raise ParticipantAdapterError("invocation input contains unsupported fields")
        messages = request.get("messages")
        max_tokens = request.get("max_tokens")
        temperature = request.get("temperature", 0.2)
        if not isinstance(messages, list) or not messages or len(messages) > 256:
            raise ParticipantAdapterError("invocation messages are invalid")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32768:
            raise ParticipantAdapterError("invocation output token limit is invalid")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ParticipantAdapterError("invocation temperature is invalid")
        tools = request.get("tools")
        if tools is not None and (not isinstance(tools, list) or len(tools) > 128):
            raise ParticipantAdapterError("invocation tools are invalid")

        events = Queue(maxsize=32)
        stop = threading.Event()
        finished = object()

        def publish(event_type, payload):
            while not stop.is_set():
                try:
                    events.put((event_type, payload), timeout=0.1)
                    return
                except Exception:
                    continue

        def run_provider():
            try:
                result = participant.provider.chat(
                    messages, max_tokens=max_tokens, temperature=float(temperature),
                    tools=tools, on_token=lambda token: publish("text_delta", {"text": token}),
                )
                publish("terminal", result)
            except Exception as exc:
                publish("error", exc)
            finally:
                publish("finished", finished)

        worker = threading.Thread(target=run_provider, name="evo-participant-provider", daemon=True)
        worker.start()
        sequence = 0
        yield ParticipantEvent(
            str(uuid4()), envelope.invocation_id, participant.participant_id,
            sequence, "started", _utc_now(), "{}", "openai_compatible_chat/1",
        )
        sequence += 1
        try:
            while True:
                try:
                    event_type, payload = events.get(timeout=participant.timeout_seconds + 2)
                except Empty:
                    result = ParticipantResult(
                        envelope.invocation_id, participant.participant_id,
                        "timed_out", _utc_now(), error_code="provider_timeout",
                        error_message="Provider response exceeded its bounded timeout",
                    )
                    validate_participant_result(result)
                    yield result
                    return
                if event_type == "finished":
                    return
                if event_type == "text_delta":
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
                    elif isinstance(exc, ProviderHTTPError) and exc.status_code in {401, 403}:
                        status, code, message = "denied", "provider_denied", "Provider rejected the request"
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
