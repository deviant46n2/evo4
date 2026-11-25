import json
import socket
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from evo_core.openai_compatible_adapter import (
    OpenAICompatibleParticipantAdapter,
    ParticipantAdapterError,
    ParticipantDispatchDisabledError,
)
from evo_core.participant_contracts import InvocationEnvelope, ParticipantResult
from evo_core.provider import ProviderHTTPError, ProviderMalformedResponseError, ProviderTimeoutError
from evo_core.provider_endpoint import PinnedProviderTransport


class AdapterHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"data": [{"id": "model-a"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if getattr(self.server, "status_code", 200) != 200:
            self.send_response(self.server.status_code)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.server.malformed_sse:
            body = b'data: {"choices":"invalid"}\n\ndata: [DONE]\n\n'
        else:
            body = (
                b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class FakeProvider:
    def __init__(self, base_url, api_key, model, timeout, *, transport=None):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self.failure = None

    def list_models(self, *, timeout_seconds=None):
        if self.failure:
            raise self.failure
        return ["model-a"]

    def chat(self, messages, max_tokens=2048, temperature=0.2, on_token=None, tools=None, *, timeout_seconds=None):
        if self.failure:
            raise self.failure
        if on_token:
            on_token("fake answer")
        return {
            "content": "fake answer",
            "tool_calls": [],
            "finish_reason": "stop",
            "truncated": False,
            "prompt_tokens": 12,
            "completion_tokens": 2,
        }


def model_component(endpoint):
    return {
        "type": "model",
        "component_version": 1,
        "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
        "settings": {
            "endpoint": endpoint,
            "model": "model-a",
            "timeout_seconds": 5,
        },
        "secret_refs": {},
    }


def provenance(participant_id):
    return {
        "participant_id": participant_id,
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "configuration_id": "config-1",
        "configuration_revision_id": "revision-1",
        "component_key": "model",
        "component_version": 1,
    }


def envelope(participant_id, *, input_json=None):
    return InvocationEnvelope(
        invocation_id="invocation-1",
        parent_task_id=None,
        participant_id=participant_id,
        adapter_id="openai_compatible_chat",
        adapter_contract_version=1,
        configuration_id="config-1",
        configuration_revision_id="revision-1",
        component_key="model",
        component_version=1,
        project_id="project-1",
        workspace_id="workspace-1",
        objective="test bounded adapter",
        task_role="implementer",
        input_json=input_json or json.dumps({
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 8,
            "temperature": 0.2,
        }),
        context_references=(),
        output_contract_json='{"type":"object"}',
        acceptance_criteria=(),
        effective_permissions=(),
        approval_requirements=(),
        deadline_utc=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        retry_limit=0,
        remaining_budgets=(),
        correlation_id="correlation-1",
    )


class OpenAICompatibleParticipantAdapterTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterHandler)
        self.server.status_code = 200
        self.server.malformed_sse = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def resolver(self, host, port, type=socket.SOCK_STREAM):
        return socket.getaddrinfo("127.0.0.1", port, type=type)

    def test_registry_binding_uses_pinned_transport_and_exact_model_preflight(self):
        adapter = OpenAICompatibleParticipantAdapter(resolver=self.resolver)
        component = model_component(self.endpoint)
        adapter.validate_component(component)
        participant = adapter.bind_component(component, provenance("participant-1"))
        self.assertIsInstance(participant.provider.transport, PinnedProviderTransport)
        evidence = adapter.preflight(participant, timeout_seconds=3)
        self.assertTrue(evidence.transport_reachable)
        self.assertTrue(evidence.model_advertised)
        self.assertIsNone(evidence.completion_verified)
        self.assertEqual(evidence.state, "unknown")

    def test_model_listing_unsupported_remains_unknown_not_unavailable(self):
        class UnsupportedListing(FakeProvider):
            def list_models(self, *, timeout_seconds=None):
                raise ProviderHTTPError(404, "Model-list")
        adapter = OpenAICompatibleParticipantAdapter(provider_factory=UnsupportedListing)
        participant = adapter.bind_component(model_component(self.endpoint), provenance("p"))
        evidence = adapter.preflight(participant, timeout_seconds=3)
        self.assertTrue(evidence.transport_reachable)
        self.assertIsNone(evidence.model_advertised)
        self.assertIsNone(evidence.completion_verified)

    def test_dispatch_and_completion_probe_are_disabled_without_p35_authorizer(self):
        adapter = OpenAICompatibleParticipantAdapter(provider_factory=FakeProvider)
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        with self.assertRaises(ParticipantDispatchDisabledError):
            adapter.probe_completion(participant, timeout_seconds=2)
        with self.assertRaises(ParticipantDispatchDisabledError):
            list(adapter.invoke(participant, envelope("p")))

    def test_admitted_test_invocation_yields_normalized_events_and_result(self):
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=FakeProvider,
            dispatch_authorizer=lambda operation, participant, request: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        records = list(adapter.invoke(participant, envelope("p")))
        self.assertEqual(records[0].event_type, "started")
        self.assertEqual(records[1].event_type, "text_delta")
        result = records[-1]
        self.assertIsInstance(result, ParticipantResult)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(json.loads(result.output_json)["content"], "fake answer")
        self.assertEqual(dict(result.usage), {"prompt_tokens": 12, "completion_tokens": 2})

    def test_provider_http_rate_limit_is_normalized(self):
        class RateLimited(FakeProvider):
            def chat(self, *args, **kwargs):
                raise ProviderHTTPError(429, "Chat completion")
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=RateLimited,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        result = list(adapter.invoke(participant, envelope("p")))[-1]
        self.assertEqual(result.status, "rate_limited")
        self.assertEqual(result.error_code, "provider_rate_limited")

    def test_malformed_sse_is_normalized_as_malformed_output(self):
        self.server.malformed_sse = True
        adapter = OpenAICompatibleParticipantAdapter(
            resolver=self.resolver,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), provenance("p"))
        result = list(adapter.invoke(participant, envelope("p")))[-1]
        self.assertEqual(result.status, "malformed_output")
        self.assertEqual(result.error_code, "malformed_provider_output")

    def test_provider_malformed_error_is_normalized(self):
        class Malformed(FakeProvider):
            def chat(self, *args, **kwargs):
                raise ProviderMalformedResponseError("bad response")
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=Malformed,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), provenance("p"))
        result = list(adapter.invoke(participant, envelope("p")))[-1]
        self.assertEqual(result.status, "malformed_output")

    def test_real_pinned_transport_preserves_http_status_for_normalization(self):
        self.server.status_code = 429
        adapter = OpenAICompatibleParticipantAdapter(
            resolver=self.resolver,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        result = list(adapter.invoke(participant, envelope("p")))[-1]
        self.assertEqual(result.status, "rate_limited")
        self.assertEqual(result.error_code, "provider_rate_limited")

    def test_provider_timeout_is_normalized(self):
        class TimedOut(FakeProvider):
            def chat(self, *args, **kwargs):
                raise ProviderTimeoutError("timed out")
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=TimedOut,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        result = list(adapter.invoke(participant, envelope("p")))[-1]
        self.assertEqual(result.status, "timed_out")

    def test_real_pinned_transport_streams_provider_response(self):
        adapter = OpenAICompatibleParticipantAdapter(
            resolver=self.resolver,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        records = list(adapter.invoke(participant, envelope("p")))
        deltas = [json.loads(item.payload_json)["text"] for item in records if getattr(item, "event_type", None) == "text_delta"]
        self.assertEqual(deltas, ["hello"])
        self.assertEqual(records[-1].status, "succeeded")

    def test_invocation_rejects_workspace_or_revision_provenance_drift(self):
        from dataclasses import replace
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=FakeProvider,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), provenance("p"))
        mismatched = replace(envelope("p"), configuration_revision_id="revision-2")
        with self.assertRaisesRegex(ParticipantAdapterError, "identity"):
            list(adapter.invoke(participant, mismatched))

    def test_invocation_rejects_unknown_input_fields_before_provider_call(self):
        adapter = OpenAICompatibleParticipantAdapter(
            provider_factory=FakeProvider,
            dispatch_authorizer=lambda *args: True,
        )
        participant = adapter.bind_component(model_component(self.endpoint), {"participant_id": "p"})
        bad = envelope("p", input_json='{"messages":[{"role":"user","content":"hi"}],"max_tokens":8,"extra":true}')
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            list(adapter.invoke(participant, bad))


if __name__ == "__main__":
    unittest.main()
