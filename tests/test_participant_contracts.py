import unittest

from evo_core.participant_contracts import (
    AvailabilityEvidence,
    ComplianceApproval,
    ParticipantResult,
    ParticipantEvent,
    resolve_adapter_contract,
    stable_integration_id,
    stable_participant_id,
    validate_participant_result,
    validate_participant_event,
    verify_structured_output,
    UnsupportedAdapterError,
)


class ParticipantContractTests(unittest.TestCase):
    def test_code_registry_resolves_only_exact_adapter_contract(self):
        contract = resolve_adapter_contract("openai_compatible_chat", 1, "model")
        self.assertEqual(contract.capabilities, ("text_generation", "tool_call_generation"))
        with self.assertRaises(UnsupportedAdapterError):
            resolve_adapter_contract("user_supplied.python", 1, "model")
        with self.assertRaises(UnsupportedAdapterError):
            resolve_adapter_contract("openai_compatible_chat", 2, "model")
        with self.assertRaises(UnsupportedAdapterError):
            resolve_adapter_contract("openai_compatible_chat", 1, "assistant_runtime")

    def test_integration_identity_excludes_secret_material_and_is_stable(self):
        first = stable_integration_id("openai_compatible_chat", "https://api.example.test", "model-a")
        second = stable_integration_id("openai_compatible_chat", "https://api.example.test", "model-a")
        changed = stable_integration_id("openai_compatible_chat", "https://api.example.test", "model-b")
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertNotIn("api_key", first)

    def test_participant_identity_is_revision_specific(self):
        integration = stable_integration_id("openai_compatible_chat", "http://127.0.0.1:8000", "model")
        first = stable_participant_id(integration, "cfg", "rev-1", "model", 1)
        second = stable_participant_id(integration, "cfg", "rev-2", "model", 1)
        self.assertNotEqual(first, second)
        self.assertEqual(first, stable_participant_id(integration, "cfg", "rev-1", "model", 1))

    def test_availability_is_independent_and_unknown_by_default(self):
        evidence = AvailabilityEvidence(None, None, None, "2026-11-24T00:00:00Z")
        self.assertEqual(evidence.state, "unknown")
        self.assertEqual(
            AvailabilityEvidence(True, True, True, "now").state, "available"
        )
        self.assertEqual(
            AvailabilityEvidence(True, True, False, "now").state, "unavailable"
        )

    def test_compliance_status_is_explicit(self):
        record = ComplianceApproval(
            "approved", "https://api.example.test", "openai_compatible_chat",
            "chat_completion", "2026-11-24", "terms-v1", "handling-v1",
        )
        self.assertEqual(record.status, "approved")
        with self.assertRaises(ValueError):
            ComplianceApproval("available", "https://api.example.test",
                               "openai_compatible_chat", "chat_completion",
                               None, None, None)

    def test_success_result_requires_complete_json_output(self):
        result = ParticipantResult("i", "p", "succeeded", "now", output_json='{"ok":true}')
        validate_participant_result(result)
        with self.assertRaises(ValueError):
            validate_participant_result(
                ParticipantResult("i", "p", "succeeded", "now", output_json="not json")
            )
        with self.assertRaises(ValueError):
            validate_participant_result(
                ParticipantResult("i", "p", "succeeded", "now", output_json='{"ok":true}', partial_output=True)
            )


    def test_adapter_contract_version_requires_an_integer(self):
        with self.assertRaises(UnsupportedAdapterError):
            resolve_adapter_contract("openai_compatible_chat", 1.0, "model")

    def test_participant_event_requires_bounded_valid_object_payload(self):
        event = ParticipantEvent(
            "e1", "i1", "p1", 0, "progress", "2026-11-24T00:00:00Z",
            '{"step":"working"}', "adapter",
        )
        validate_participant_event(event)
        invalid = ParticipantEvent(
            "e2", "i1", "p1", 1, "progress", "now",
            '{"x":1,"x":2}', "adapter",
        )
        with self.assertRaises(ValueError):
            validate_participant_event(invalid)
        invalid = ParticipantEvent(
            "e3", "i1", "p1", 2, "progress", "now",
            '{"x":NaN}', "adapter",
        )
        with self.assertRaises(ValueError):
            validate_participant_event(invalid)

    def test_success_result_rejects_duplicate_keys_and_nonstandard_json(self):
        for output in ('{"ok":true,"ok":false}', '{"ok":NaN}'):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    validate_participant_result(
                        ParticipantResult("i", "p", "succeeded", "now", output_json=output)
                    )

    def test_non_success_output_must_be_marked_partial(self):
        with self.assertRaises(ValueError):
            validate_participant_result(
                ParticipantResult("i", "p", "timed_out", "now", output_json='{"partial":true}')
            )
        validate_participant_result(
            ParticipantResult("i", "p", "timed_out", "now", output_json='{"partial":true}', partial_output=True)
        )

    def test_deterministic_verifier_checks_fields_and_evidence_shape(self):
        settings = {
            "required_fields": ["status", "evidence"],
            "evidence_fields": ["evidence"],
            "max_output_bytes": 4096,
            "allow_additional_fields": False,
        }
        valid = verify_structured_output(settings, '{"status":"ok","evidence":["run:123"]}')
        self.assertTrue(valid.valid)
        missing = verify_structured_output(settings, '{"status":"ok","extra":true}')
        self.assertFalse(missing.valid)
        self.assertIn("missing_required_field:evidence", missing.issues)
        malformed_evidence = verify_structured_output(settings, '{"status":"ok","evidence":[""]}')
        self.assertFalse(malformed_evidence.valid)

    def test_deterministic_verifier_rejects_malformed_and_oversized_output(self):
        settings = {
            "required_fields": ["status"],
            "evidence_fields": [],
            "max_output_bytes": 8,
            "allow_additional_fields": False,
        }
        self.assertIn("malformed_json", verify_structured_output(settings, "{bad").issues)
        self.assertIn(
            "output_exceeds_size_limit",
            verify_structured_output(settings, '{"status":"too long"}').issues,
        )


if __name__ == "__main__":
    unittest.main()
