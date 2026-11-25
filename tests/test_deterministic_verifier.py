import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from evo_core.deterministic_verifier import (
    DeterministicVerifierParticipantAdapter,
    DeterministicVerifierError,
    VerifierDispatchDisabledError,
)
from evo_core.participant_contracts import InvocationEnvelope, ParticipantResult


def component():
    return {
        "type": "deterministic_verifier",
        "component_version": 1,
        "adapter": {"id": "evo_deterministic_verifier", "contract_version": 1},
        "settings": {
            "required_fields": ["status", "evidence"],
            "evidence_fields": ["evidence"],
            "max_output_bytes": 4096,
            "allow_additional_fields": False,
        },
    }


def provenance():
    return {
        "participant_id": "verifier-p1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "configuration_id": "config-1",
        "configuration_revision_id": "revision-1",
        "component_key": "verifier",
        "component_version": 1,
    }


def envelope(participant, output, **overrides):
    values = {
        "invocation_id": "invocation-1",
        "parent_task_id": None,
        "participant_id": participant.participant_id,
        "adapter_id": "evo_deterministic_verifier",
        "adapter_contract_version": 1,
        "configuration_id": participant.configuration_id,
        "configuration_revision_id": participant.configuration_revision_id,
        "component_key": participant.component_key,
        "component_version": participant.component_version,
        "project_id": participant.project_id,
        "workspace_id": participant.workspace_id,
        "objective": "Validate structured output",
        "task_role": "verifier",
        "input_json": json.dumps({"output": output}),
        "context_references": (),
        "output_contract_json": '{"type":"object"}',
        "acceptance_criteria": (),
        "effective_permissions": (),
        "approval_requirements": (),
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        "retry_limit": 0,
        "remaining_budgets": (),
        "correlation_id": "correlation-1",
    }
    values.update(overrides)
    return InvocationEnvelope(**values)


class DeterministicVerifierParticipantTests(unittest.TestCase):
    def bind(self, *, authorizer=None):
        adapter = DeterministicVerifierParticipantAdapter(dispatch_authorizer=authorizer)
        adapter.validate_component(component())
        participant = adapter.bind_component(component(), provenance())
        return adapter, participant

    def test_code_owned_contract_and_local_descriptor(self):
        adapter, participant = self.bind()
        descriptor = adapter.describe(participant)
        self.assertEqual(descriptor.adapter_id, "evo_deterministic_verifier")
        self.assertEqual(descriptor.participant_type, "deterministic_tool")
        self.assertEqual(descriptor.execution_location, "local_process")
        self.assertEqual(descriptor.compliance_reference, "local_only")
        self.assertIn("evidence_reference_shape_validation", descriptor.capabilities)
        self.assertEqual(descriptor.configuration_revision_id, "revision-1")

    def test_binding_rejects_secrets_and_incomplete_provenance(self):
        adapter = DeterministicVerifierParticipantAdapter()
        with self.assertRaises(DeterministicVerifierError):
            adapter.bind_component(component(), provenance(), secret_values={"api_key": "secret"})
        with self.assertRaises(DeterministicVerifierError):
            adapter.bind_component(component(), {"participant_id": "p"})

    def test_component_schema_is_strict_and_bounded(self):
        adapter = DeterministicVerifierParticipantAdapter()
        invalid = component()
        invalid["settings"]["arbitrary_tool"] = "shell"
        with self.assertRaises(DeterministicVerifierError):
            adapter.validate_component(invalid)
        invalid = component()
        invalid["settings"]["max_output_bytes"] = 1_048_577
        with self.assertRaises(DeterministicVerifierError):
            adapter.validate_component(invalid)

    def test_adapter_configuration_is_immutable(self):
        adapter, _ = self.bind()
        with self.assertRaises(AttributeError):
            adapter._dispatch_authorizer = lambda p, e: True
        invalid = component()
        invalid["settings"]["required_fields"] = ["bad field"]
        with self.assertRaises(DeterministicVerifierError):
            adapter.validate_component(invalid)

    def test_preflight_is_non_invoking_and_completion_probe_is_local(self):
        adapter, participant = self.bind()
        preflight = adapter.preflight(participant, timeout_seconds=2)
        self.assertEqual(preflight.state, "unknown")
        probe = adapter.probe_completion(participant, timeout_seconds=2)
        self.assertTrue(probe.transport_reachable)
        self.assertTrue(probe.model_advertised)
        self.assertTrue(probe.completion_verified)
        self.assertEqual(probe.state, "available")

    def test_invocation_is_disabled_without_p35_authorizer(self):
        adapter, participant = self.bind()
        request = envelope(participant, '{"status":"ok","evidence":["run:1"]}')
        with self.assertRaises(VerifierDispatchDisabledError):
            list(adapter.invoke(participant, request))

    def test_authorized_invocation_returns_deterministic_evidence_bearing_result(self):
        calls = []
        adapter, participant = self.bind(authorizer=lambda p, e: calls.append((p, e)) or True)
        request = envelope(participant, '{"status":"ok","evidence":["run:1","artifact:2"]}')
        events = list(adapter.invoke(participant, request))
        self.assertEqual(len(calls), 1)
        self.assertEqual(events[0].event_type, "started")
        result = events[-1]
        self.assertIsInstance(result, ParticipantResult)
        self.assertEqual(result.status, "succeeded")
        parsed = json.loads(result.output_json)
        self.assertTrue(parsed["valid"])
        self.assertTrue(parsed["evidence_reference_shape_only"])
        self.assertEqual(result.evidence_references, ("run:1", "artifact:2"))

    def test_invalid_target_json_is_a_successful_verification_failure(self):
        adapter, participant = self.bind(authorizer=lambda p, e: True)
        events = list(adapter.invoke(participant, envelope(participant, "{bad")))
        result = events[-1]
        self.assertEqual(result.status, "succeeded")
        parsed = json.loads(result.output_json)
        self.assertFalse(parsed["valid"])
        self.assertIn("malformed_json", parsed["issues"])
        self.assertEqual(result.evidence_references, ())

    def test_missing_fields_and_unexpected_fields_are_reported(self):
        adapter, participant = self.bind(authorizer=lambda p, e: True)
        output = '{"status":"ok","extra":true}'
        result = list(adapter.invoke(participant, envelope(participant, output)))[-1]
        parsed = json.loads(result.output_json)
        self.assertFalse(parsed["valid"])
        self.assertIn("missing_required_field:evidence", parsed["issues"])
        self.assertIn("unexpected_field:extra", parsed["issues"])

    def test_wrong_participant_identity_is_rejected(self):
        adapter, participant = self.bind(authorizer=lambda p, e: True)
        request = envelope(participant, '{"status":"ok","evidence":["run:1"]}', participant_id="other")
        with self.assertRaises(DeterministicVerifierError):
            list(adapter.invoke(participant, request))

    def test_pre_cancelled_invocation_does_not_start(self):
        adapter, participant = self.bind(authorizer=lambda p, e: True)
        cancellation = threading.Event()
        cancellation.set()
        events = list(adapter.invoke(
            participant, envelope(participant, '{"status":"ok","evidence":["run:1"]}'),
            cancellation_event=cancellation,
        ))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "cancelled")

    def test_expired_deadline_is_terminal_timeout(self):
        adapter, participant = self.bind(authorizer=lambda p, e: True)
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        events = list(adapter.invoke(
            participant,
            envelope(participant, '{"status":"ok","evidence":["run:1"]}', deadline_utc=expired),
        ))
        self.assertEqual(events[-1].status, "timed_out")

    def test_authorizer_denial_fails_closed(self):
        adapter, participant = self.bind(authorizer=lambda p, e: False)
        with self.assertRaises(VerifierDispatchDisabledError):
            list(adapter.invoke(participant, envelope(participant, '{"status":"ok","evidence":["run:1"]}')))


if __name__ == "__main__":
    unittest.main()
