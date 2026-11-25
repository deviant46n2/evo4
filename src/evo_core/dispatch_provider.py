"""Workspace-bound provider bridge for P3.5 admission.

Every model completion gets its own immutable runtime snapshot, invocation
envelope, provider approval check, resource sample, budget reservation, and
dispatch lease. This module is deliberately opt-in; config dispatch.enabled
must remain false until the P3.5 acceptance gate closes.
"""
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from uuid import uuid4

from .dispatch_admission import (
    AdmissionError,
    AdmissionPolicy,
    ProviderBudget,
    admit_invocation,
    finalize_invocation,
    get_invocation_lifecycle,
    heartbeat_dispatch_lease,
    mark_invocation_running,
)
from .openai_compatible_adapter import ParticipantAdapterError
from .participant_contracts import InvocationEnvelope, ParticipantEvent, ParticipantResult
from .provider_approvals import find_provider_approval
from .runtime_invocation_snapshots import create_runtime_invocation_snapshot


class DispatchProviderError(RuntimeError):
    """Safe, bounded failure from a Registry-bound completion."""


class _CombinedCancellation:
    def __init__(self, external, lease_lost):
        self.external = external
        self.lease_lost = lease_lost

    def is_set(self):
        return bool(
            (self.external is not None and self.external.is_set())
            or self.lease_lost.is_set()
        )


class RuntimeDispatchController:
    """Single-use admission authority installed into one pinned adapter."""

    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.runtime = None

    def bind_runtime(self, runtime):
        if self.runtime is not None:
            raise RuntimeError("dispatch controller is already bound")
        self.runtime = runtime

    def authorize(self, operation, participant, envelope):
        if operation != "participant_invocation" or self.runtime is None:
            return False
        runtime = self.runtime
        if participant is not runtime.bound_participant:
            return False
        if (
            envelope.workspace_id != runtime.workspace_id
            or envelope.project_id != runtime.project_id
            or envelope.configuration_revision_id != runtime.revision_id
        ):
            return False

        from urllib.parse import urlsplit
        from .provider_endpoint import normalize_provider_origin
        from evo_experiments.monitor import sample_nvidia_smi

        parsed = urlsplit(participant.endpoint)
        origin = normalize_provider_origin(f"{parsed.scheme}://{parsed.netloc}")
        approval = find_provider_approval(
            self.config.provider_approvals, origin,
            runtime.participant.adapter_id, "chat_completion",
        )
        budget = next(
            (item for item in self.config.provider_budgets
             if item.integration_id == runtime.participant.integration_id),
            None,
        )
        local_profile = next(
            (dict(profile) for integration_id, profile in self.config.local_resource_profiles
             if integration_id == runtime.participant.integration_id),
            None,
        )
        try:
            telemetry = sample_nvidia_smi()
        except Exception:
            # Unknown telemetry is a hard admission failure, not a reason to
            # fall back to cached dashboard data or guessed headroom.
            telemetry = None
        decision = admit_invocation(
            self.store, runtime, envelope,
            approval=approval,
            provider_budget=budget,
            telemetry=telemetry,
            local_profile=local_profile,
            policy=AdmissionPolicy(),
        )
        if not decision.get("allowed"):
            return False
        if not mark_invocation_running(self.store, envelope.invocation_id):
            # The provider worker has not been started yet. A serialized
            # admitted->cancelled transition safely releases the reservation.
            finalize_invocation(
                self.store, envelope.invocation_id, "cancelled",
                error_code="dispatch_start_rejected",
                error_message="Invocation could not cross the atomic start boundary",
                provider_settled=True,
            )
            return False
        return True


class DispatchingProvider:
    """EvoAssistant-compatible provider facade with durable P3.5 admission."""

    dispatch_enabled = True

    def __init__(self, store, runtime, controller):
        self.store = store
        self.runtime = runtime
        self.controller = controller
        self.adapter = runtime.participant_adapter
        self.participant = runtime.bound_participant
        self.base_url = self.participant.endpoint.rstrip("/")
        self.model = self.participant.model
        self.timeout = self.participant.timeout_seconds

    def chat(
        self, messages, max_tokens=2048, temperature=0.2, on_token=None,
        tools=None, *, timeout_seconds=None, cancellation_event=None,
        parent_task_id=None, task_role="assistant_completion",
    ):
        if cancellation_event is not None and not callable(getattr(cancellation_event, "is_set", None)):
            raise TypeError("cancellation_event must expose is_set()")
        if cancellation_event is not None and cancellation_event.is_set():
            raise DispatchProviderError("Invocation cancelled before admission")

        invocation_id = str(uuid4())
        started_at = time.monotonic()
        first_token_at = None
        effective_timeout = self.timeout
        if timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be positive")
            effective_timeout = min(effective_timeout, max(1, int(timeout_seconds)))
        effective_timeout = min(600, effective_timeout)
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=effective_timeout)
        deadline_utc = deadline.isoformat().replace("+00:00", "Z")
        # Leave time for snapshot persistence and the atomic admission
        # transaction; the transport itself remains bounded by the pinned
        # participant timeout and this envelope deadline.
        request_seconds = max(0.1, effective_timeout - 1.0)
        request = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools is not None:
            request["tools"] = tools
        try:
            input_json = json.dumps(
                request, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise DispatchProviderError("Provider request is not valid bounded JSON") from exc

        try:
            create_runtime_invocation_snapshot(
                self.store, self.runtime, invocation_id=invocation_id,
                invocation_kind="participant_completion",
            )
        except Exception as exc:
            raise DispatchProviderError("Could not persist the immutable invocation snapshot") from exc

        permissions = ("text_generation", "tool_call_generation") if tools is not None else ("text_generation",)
        envelope = InvocationEnvelope(
            invocation_id=invocation_id,
            parent_task_id=parent_task_id,
            participant_id=self.runtime.participant.participant_id,
            adapter_id=self.runtime.participant.adapter_id,
            adapter_contract_version=self.runtime.participant.adapter_contract_version,
            configuration_id=self.runtime.configuration_id,
            configuration_revision_id=self.runtime.revision_id,
            component_key=self.runtime.participant.component_key,
            component_version=self.runtime.participant.component_version,
            project_id=self.runtime.project_id,
            workspace_id=self.runtime.workspace_id,
            objective="Generate the next assistant completion for the current workspace-scoped request",
            task_role=task_role,
            input_json=input_json,
            context_references=(),
            output_contract_json='{"type":"object","required":["content","tool_calls"],"additionalProperties":false}',
            acceptance_criteria=(),
            effective_permissions=permissions,
            approval_requirements=("provider_compliance", "resource_admission", "provider_budget"),
            deadline_utc=deadline_utc,
            retry_limit=0,
            remaining_budgets=(
                ("output_tokens", max_tokens),
                ("request_seconds", request_seconds),
            ),
            correlation_id=str(uuid4()),
        )

        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        combined_cancel = _CombinedCancellation(cancellation_event, lease_lost)
        heartbeat_thread = None
        terminal = None
        admission_rejected = False

        def heartbeat_loop():
            while not heartbeat_stop.wait(4.0):
                try:
                    if not heartbeat_dispatch_lease(self.store, invocation_id):
                        lease_lost.set()
                        return
                except Exception:
                    lease_lost.set()
                    return

        try:
            for item in self.adapter.invoke(
                self.participant, envelope, cancellation_event=combined_cancel,
            ):
                if isinstance(item, ParticipantEvent):
                    if item.event_type == "started" and heartbeat_thread is None:
                        heartbeat_thread = threading.Thread(
                            target=heartbeat_loop,
                            name="evo-dispatch-lease-heartbeat",
                            daemon=True,
                        )
                        heartbeat_thread.start()
                    elif item.event_type == "text_delta":
                        payload = json.loads(item.payload_json)
                        token = payload.get("text", "")
                        if token and on_token is not None:
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                            on_token(token)
                elif isinstance(item, ParticipantResult):
                    terminal = item
                    break
            if terminal is None:
                raise DispatchProviderError("Provider adapter ended without a terminal result")

            status = terminal.status
            if status == "denied":
                # Provider-side 401/403 is not a policy admission denial. The
                # lifecycle vocabulary reserves denied for pre-dispatch gates.
                status = "provider_failed"
            usage_values = dict(terminal.usage)
            usage = {}
            if isinstance(usage_values.get("prompt_tokens"), int) and not isinstance(usage_values["prompt_tokens"], bool):
                usage["input_tokens"] = usage_values["prompt_tokens"]
            if isinstance(usage_values.get("completion_tokens"), int) and not isinstance(usage_values["completion_tokens"], bool):
                usage["output_tokens"] = usage_values["completion_tokens"]
            if "input_tokens" in usage and "output_tokens" in usage:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            provider_settled = terminal.status not in {"cancelled", "timed_out"}
            try:
                finalize_invocation(
                    self.store, invocation_id, status,
                    usage=usage or None,
                    error_code=terminal.error_code,
                    error_message=terminal.error_message,
                    provider_settled=provider_settled,
                )
            except Exception as exc:
                # Never turn a failed durable settlement into a successful
                # completion. The lease remains held or abandoned for recovery.
                raise DispatchProviderError("Provider completed but lifecycle settlement failed") from exc

            if terminal.status != "succeeded" or not terminal.output_json:
                raise DispatchProviderError(
                    terminal.error_message or f"Provider completion ended with status {terminal.status}"
                )
            try:
                output = json.loads(terminal.output_json)
            except (TypeError, ValueError) as exc:
                raise DispatchProviderError("Provider returned malformed normalized output") from exc
            return {
                "content": output.get("content", ""),
                "tool_calls": output.get("tool_calls", []),
                "finish_reason": output.get("finish_reason"),
                "truncated": bool(output.get("truncated", False)),
                "prompt_tokens": usage_values.get("prompt_tokens", 0),
                "completion_tokens": usage_values.get("completion_tokens", 0),
                "elapsed_seconds": max(0.0, time.monotonic() - started_at),
                "ttft_seconds": (
                    max(0.0, first_token_at - started_at)
                    if first_token_at is not None else None
                ),
            }
        except ParticipantAdapterError as exc:
            lifecycle = get_invocation_lifecycle(self.store, invocation_id)
            if lifecycle is not None and lifecycle.get("status") in {"denied", "deferred", "rate_limited", "budget_exhausted"}:
                decision = lifecycle.get("decision") or {}
                reason = decision.get("reason", "dispatch_not_admitted")
                admission_rejected = True
                raise DispatchProviderError(f"Provider dispatch was not admitted: {reason}") from exc
            self._abandon_if_running(invocation_id, "adapter_error")
            raise DispatchProviderError("Provider adapter rejected the invocation") from exc
        except DispatchProviderError:
            if terminal is None:
                self._abandon_if_running(invocation_id, "dispatch_error")
            raise
        except Exception as exc:
            self._abandon_if_running(invocation_id, "dispatch_error")
            raise DispatchProviderError("Workspace provider invocation failed") from exc
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)

    def _abandon_if_running(self, invocation_id, reason):
        try:
            lifecycle = get_invocation_lifecycle(self.store, invocation_id)
            if lifecycle is not None and lifecycle.get("status") in {"admitted", "running"}:
                finalize_invocation(
                    self.store, invocation_id, "provider_failed",
                    error_code=reason,
                    error_message="Provider execution did not reach a verified terminal result",
                    provider_settled=False,
                )
        except Exception:
            # Preserve the lease if even the recovery write cannot be proven.
            return
