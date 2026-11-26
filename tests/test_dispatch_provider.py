import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from evo_core.ai_configurations import create_configuration
from evo_core.config import EvoConfig
from evo_core.dispatch_admission import (
    ProviderBudget, get_invocation_lifecycle, initialize_invocation_lifecycle,
)
from evo_core.dispatch_provider import DispatchProviderError, DispatchingProvider
from evo_core.openai_compatible_adapter import OpenAICompatibleParticipantAdapter
from evo_core.participant_contracts import (
    ParticipantDescriptor, resolve_adapter_contract, stable_integration_id,
    stable_participant_id,
)
from evo_core.runtime_binding import RuntimeBindingError
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.provider_approvals import ProviderApproval
from evo_core.runtime_binding import build_workspace_runtime, RegistryDispatchDisabledError
from evo_core.provider import ProviderTimeoutError
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace


def schema2_definition():
    return {
        "schema_version": 2,
        "components": {
            "model": {
                "type": "model", "component_version": 1,
                "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
                "settings": {
                    "endpoint": "http://127.0.0.1:18997/v1",
                    "model": "dispatch-test-model",
                    "timeout_seconds": 30,
                },
            },
            "assistant": {
                "type": "assistant_runtime", "component_version": 1,
                "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                "settings": {
                    "model_component": "model", "persona_prompt": "",
                    "max_output_tokens": 256, "temperature": 0.2,
                    "context_window_tokens": 8192, "history_messages": 4,
                    "max_history_chars": 4000, "memory_limit": 2,
                },
            },
            "policy": {
                "type": "command_policy", "component_version": 1,
                "adapter": {"id": "evo_command_policy", "contract_version": 1},
                "settings": {"allowed_commands": [["python", "-m", "unittest"]]},
            },
        },
        "entrypoints": {"assistant": "assistant"},
    }


def telemetry():
    return {
        "sampled_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "ram_available_bytes": 8 * 1024 * 1024 * 1024,
        "cpu_logical_cores": 8,
        "load_average_1m": 1.0,
        "cpu_utilization_percent": 30.0,
        "gpu_available": False,
        "gpu_memory_used_mib": None,
        "gpu_memory_total_mib": None,
        "gpu_temperature_c": None,
    }


class FakeProvider:
    def __init__(self):
        self.calls = 0
        self.failure = None
        self.content = "admitted answer"

    def chat(self, messages, max_tokens=2048, temperature=0.2, on_token=None,
             tools=None, *, timeout_seconds=None):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if on_token:
            on_token("admitted ")
            on_token("answer")
        return {
            "content": self.content, "tool_calls": [],
            "finish_reason": "stop", "truncated": False,
            "prompt_tokens": 12, "completion_tokens": 2,
        }


class DispatchProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "dispatch.sqlite3")
        initialize_platform_registry(self.store)
        project = register_project(self.store, "Dispatch project")
        checkout_path = self.root / "checkout"
        checkout_path.mkdir()
        checkout = register_checkout(self.store, project["project_id"], checkout_path)
        created = create_configuration(self.store, schema2_definition(), name="Dispatch config")
        self.workspace = create_workspace(
            self.store, "Dispatch workspace", project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.base_config = EvoConfig(
            base_url="http://127.0.0.1:18997/v1", api_key="no-key",
            model="global-model", timeout_seconds=30,
            database=self.root / "dispatch.sqlite3", max_tokens=256,
            temperature=0.2, system_prompt="Trusted policy",
            memory_limit=8, history_messages=16,
            workspace_root=self.root, allowed_commands=(("python",),),
            max_history_chars=40000, context_window_tokens=8192,
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def _enabled_config(self, *, with_budget=True):
        runtime = build_workspace_runtime(
            self.store, self.base_config, self.workspace["workspace_id"],
        )
        integration_id = runtime.participant.integration_id
        budget = (
            (ProviderBudget(integration_id, 20, 256, 8192),)
            if with_budget else ()
        )
        profile = {
            "compute_mode": "cpu", "cpu_cores": 0.1,
            "ram_mib": 64, "memory_mode": "cold_load",
        }
        approval = ProviderApproval(
            origin="http://127.0.0.1:18997",
            adapter_id="openai_compatible_chat",
            uses=("chat_completion",), status="local_only",
            reviewed_at="2026-11-25", terms_reference=None,
            data_handling_reference="local test endpoint",
        )
        config = replace(
            self.base_config, dispatch_enabled=True,
            provider_budgets=budget,
            local_resource_profiles=((integration_id, profile),),
            provider_approvals=(approval,),
        )
        runtime = build_workspace_runtime(
            self.store, config, self.workspace["workspace_id"],
        )
        fake = FakeProvider()
        runtime.participant_adapter._providers[runtime.participant.participant_id] = fake
        return runtime, fake

    def test_dispatch_disabled_by_default_and_runtime_fails_closed(self):
        runtime = build_workspace_runtime(
            self.store, self.base_config, self.workspace["workspace_id"],
        )
        self.assertFalse(runtime.dispatch_enabled)
        with self.assertRaises(RegistryDispatchDisabledError):
            runtime.require_dispatch_enabled()

    def test_each_completion_is_snapshotted_admitted_and_settled(self):
        runtime, fake = self._enabled_config()
        tokens = []
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            results = [
                runtime.assistant.provider.chat(
                    [{"role": "user", "content": f"hello {index}"}],
                    max_tokens=64, temperature=0.2, on_token=tokens.append,
                    parent_task_id="parent-request",
                )
                for index in range(2)
            ]
        self.assertEqual(fake.calls, 2)
        self.assertEqual([item["content"] for item in results], ["admitted answer", "admitted answer"])
        self.assertEqual(tokens, ["admitted ", "answer", "admitted ", "answer"])
        with self.store.lock:
            snapshots = self.store.db.execute(
                "SELECT invocation_id FROM runtime_invocation_snapshots"
            ).fetchall()
            usage = self.store.db.execute(
                "SELECT requests_reserved,output_tokens_reserved,output_tokens_used "
                "FROM provider_budget_usage"
            ).fetchone()
        self.assertEqual(len(snapshots), 2)
        for snapshot in snapshots:
            lifecycle = get_invocation_lifecycle(self.store, snapshot["invocation_id"])
            self.assertEqual(lifecycle["status"], "succeeded")
            self.assertEqual(lifecycle["usage"]["output_tokens"], 2)
            self.assertTrue(any(
                event["event_type"] == "invocation_started"
                for event in lifecycle["events"]
            ))
        self.assertEqual(tuple(usage), (2, 0, 4))

    def test_proposal_task_role_persists_exact_structured_provider_output(self):
        from evo_core.cooperative_handoffs import get_handoff, create_handoff, HandoffBudget
        import json
        runtime, fake = self._enabled_config()
        payload = {
            "summary": "Proposed change.",
            "plan": [{"step_id": "S1", "description": "Add a safe validator."}],
        }
        fake.content = json.dumps(payload, separators=(",", ":"))
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            runtime.assistant.provider.chat(
                [{"role": "user", "content": "return a proposal JSON object"}],
                max_tokens=64, temperature=0.2, task_role="proposal",
            )
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT invocation_id FROM participant_invocations ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            output = self.store.db.execute(
                "SELECT output_hash,output_json FROM participant_invocation_outputs WHERE invocation_id=?",
                (row["invocation_id"],),
            ).fetchone()
        self.assertIsNotNone(output)
        self.assertEqual(json.loads(output["output_json"])["content"], fake.content)
        self.assertEqual(len(output["output_hash"]), 64)

    def test_missing_budget_blocks_before_provider_request(self):
        runtime, fake = self._enabled_config(with_budget=False)
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            with self.assertRaisesRegex(DispatchProviderError, "provider_budget_not_configured"):
                runtime.assistant.provider.chat(
                    [{"role": "user", "content": "must not dispatch"}],
                    max_tokens=64, temperature=0.2,
                )
        self.assertEqual(fake.calls, 0)
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT status FROM participant_invocations"
            ).fetchone()
        self.assertEqual(row["status"], "denied")


    def test_provider_timeout_retains_lease_and_unknown_usage_reservation(self):
        runtime, fake = self._enabled_config()
        fake.failure = ProviderTimeoutError("simulated timeout")
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            with self.assertRaises(DispatchProviderError):
                runtime.assistant.provider.chat(
                    [{"role": "user", "content": "timeout"}],
                    max_tokens=64, temperature=0.2,
                )
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT invocation_id,status FROM participant_invocations"
            ).fetchone()
            lease = self.store.db.execute(
                "SELECT state FROM dispatch_leases WHERE lease_key='global_provider_dispatch'"
            ).fetchone()
            usage = self.store.db.execute(
                "SELECT requests_reserved,output_tokens_reserved,output_tokens_used "
                "FROM provider_budget_usage"
            ).fetchone()
        self.assertEqual(row["status"], "timed_out")
        self.assertEqual(lease["state"], "abandoned")
        self.assertEqual(tuple(usage), (1, 64, 0))

    def test_pre_dispatch_cancellation_creates_no_snapshot_or_lease(self):
        import threading
        runtime, fake = self._enabled_config()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(DispatchProviderError, "cancelled before admission"):
            runtime.assistant.provider.chat(
                [{"role": "user", "content": "cancel"}],
                max_tokens=64, temperature=0.2,
                cancellation_event=cancelled,
            )
        self.assertEqual(fake.calls, 0)
        initialize_invocation_lifecycle(self.store)
        with self.store.lock:
            snapshots = self.store.db.execute(
                "SELECT COUNT(*) FROM runtime_invocation_snapshots"
            ).fetchone()[0]
            invocations = self.store.db.execute(
                "SELECT COUNT(*) FROM participant_invocations"
            ).fetchone()[0]
        self.assertEqual((snapshots, invocations), (0, 0))


class SelectedParticipantAdmissionTests(unittest.TestCase):
    def setUp(self):
        DispatchProviderIntegrationTests.setUp(self)

    def tearDown(self):
        DispatchProviderIntegrationTests.tearDown(self)

    def _enabled_config(self, *, with_budget=True):
        return DispatchProviderIntegrationTests._enabled_config(self, with_budget=with_budget)

    def _runtime_with_secondary(self, *, include_budget=True, include_profile=True, include_approval=True):
        runtime, primary_fake = self._enabled_config()
        controller = runtime.assistant.provider.controller
        endpoint = "http://127.0.0.1:18997/v1"
        model = "secondary-dispatch-test-model"
        origin = "http://127.0.0.1:18997"
        integration_id = stable_integration_id(
            "openai_compatible_chat", origin, model
        )
        participant_id = stable_participant_id(
            integration_id, runtime.configuration_id, runtime.revision_id,
            "secondary_model", 1,
        )
        contract = resolve_adapter_contract(
            "openai_compatible_chat", 1, "model"
        )
        descriptor = ParticipantDescriptor(
            participant_id=participant_id,
            integration_id=integration_id,
            participant_type="model",
            display_name=model,
            adapter_id="openai_compatible_chat",
            adapter_contract_version=1,
            adapter_implementation_version=contract.implementation_version,
            capabilities=contract.capabilities,
            input_contract_versions=(1,),
            output_contract_versions=(1,),
            execution_location=contract.execution_location,
            availability="unknown",
            availability_observed_at=None,
            resource_requirements=(),
            limits=(
                ("timeout_seconds", 25),
                ("max_output_tokens", 256),
                ("context_window_tokens", 8192),
            ),
            configuration_id=runtime.configuration_id,
            configuration_revision_id=runtime.revision_id,
            component_key="secondary_model",
            component_version=1,
            compliance_reference=None,
        )
        component = {
            "type": "model",
            "component_version": 1,
            "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
            "settings": {
                "endpoint": endpoint, "model": model, "timeout_seconds": 25,
            },
        }
        adapter_reference = {}
        adapter = OpenAICompatibleParticipantAdapter(
            allowed_origins=(origin,),
            dispatch_authorizer=controller.authorizer_for(adapter_reference),
        )
        adapter_reference["adapter"] = adapter
        bound = adapter.bind_component(
            component,
            {
                "participant_id": participant_id,
                "project_id": runtime.project_id,
                "workspace_id": runtime.workspace_id,
                "configuration_id": runtime.configuration_id,
                "configuration_revision_id": runtime.revision_id,
                "component_key": "secondary_model",
                "component_version": 1,
            },
            runtime_settings={"max_output_tokens": 256, "temperature": 0.2},
        )
        fake = FakeProvider()
        adapter._providers[participant_id] = fake
        additional_provenance = (
            (participant_id, {
                "secret_reference_names": (("api_key", "env:EVO_SECONDARY_TEST_KEY"),),
            }),
        )
        selected_runtime = replace(
            runtime,
            additional_participants=(descriptor,),
            additional_participant_bindings=((adapter, bound),),
            additional_participant_provenance=additional_provenance,
        )
        controller.runtime = selected_runtime
        profile = {
            "compute_mode": "cpu", "cpu_cores": 0.1,
            "ram_mib": 64, "memory_mode": "cold_load",
        }
        budgets = tuple(controller.config.provider_budgets)
        profiles = tuple(controller.config.local_resource_profiles)
        if include_budget:
            budgets += (ProviderBudget(integration_id, 20, 256, 8192),)
        if include_profile:
            profiles += ((integration_id, profile),)
        approvals = tuple(controller.config.provider_approvals)
        if include_approval:
            approvals += (ProviderApproval(
                origin=origin,
                adapter_id="openai_compatible_chat",
                uses=("chat_completion",),
                status="local_only",
                reviewed_at="2026-11-25",
                terms_reference=None,
                data_handling_reference="secondary local test endpoint",
                integration_id=integration_id,
            ),)
        controller.config = replace(
            controller.config,
            provider_budgets=budgets,
            local_resource_profiles=profiles,
            provider_approvals=approvals,
        )
        provider = DispatchingProvider(
            self.store, selected_runtime, controller,
            participant_id=participant_id,
        )
        return selected_runtime, provider, fake, descriptor, integration_id

    def test_non_primary_participant_uses_its_own_snapshot_approval_budget_and_profile(self):
        runtime, provider, fake, descriptor, integration_id = self._runtime_with_secondary()
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            result = provider.chat(
                [{"role": "user", "content": "secondary participant request"}],
                max_tokens=64, temperature=0.2, task_role="independent_challenge",
            )
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result["content"], "admitted answer")
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT invocation_id,participant_id,integration_id,status "
                "FROM participant_invocations"
            ).fetchone()
            snapshot_row = self.store.db.execute(
                "SELECT snapshot_json FROM runtime_invocation_snapshots WHERE invocation_id=?",
                (row["invocation_id"],),
            ).fetchone()
            usage = self.store.db.execute(
                "SELECT requests_reserved,output_tokens_used FROM provider_budget_usage "
                "WHERE integration_id=?",
                (integration_id,),
            ).fetchone()
        import json
        snapshot = json.loads(snapshot_row["snapshot_json"])
        self.assertEqual(row["participant_id"], descriptor.participant_id)
        self.assertEqual(row["integration_id"], integration_id)
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(snapshot["participant"]["participant_id"], descriptor.participant_id)
        self.assertEqual(snapshot["runtime_config"]["model"], "secondary-dispatch-test-model")
        self.assertIn(
            ["api_key", "env:EVO_SECONDARY_TEST_KEY"],
            snapshot["provenance"]["secret_reference_names"],
        )
        self.assertNotIn("resolved", repr(snapshot).lower())
        self.assertEqual(tuple(usage), (1, 2))

    def test_non_primary_wrong_integration_budget_fails_before_provider_request(self):
        runtime, provider, fake, descriptor, integration_id = self._runtime_with_secondary(
            include_budget=False,
        )
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            with self.assertRaises(DispatchProviderError):
                provider.chat([{"role": "user", "content": "must be denied"}], max_tokens=64)
        self.assertEqual(fake.calls, 0)
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT participant_id,integration_id,status,decision_json FROM participant_invocations"
            ).fetchone()
        self.assertEqual(row["participant_id"], descriptor.participant_id)
        self.assertEqual(row["integration_id"], integration_id)
        self.assertEqual(row["status"], "denied")
        self.assertIn("provider_budget_not_configured", row["decision_json"])

    def test_non_primary_stale_telemetry_fails_closed(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        stale = telemetry()
        stale["sampled_at"] = "2000-01-01T00:00:00Z"
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=stale):
            with self.assertRaises(DispatchProviderError):
                provider.chat([{"role": "user", "content": "stale telemetry"}], max_tokens=64)
        self.assertEqual(fake.calls, 0)
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT status,decision_json FROM participant_invocations"
            ).fetchone()
        self.assertEqual(row["status"], "denied")
        self.assertIn("telemetry_stale", row["decision_json"])

    def test_non_primary_missing_resource_profile_fails_closed(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary(
            include_profile=False,
        )
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            with self.assertRaises(DispatchProviderError):
                provider.chat([{"role": "user", "content": "missing profile"}], max_tokens=64)
        self.assertEqual(fake.calls, 0)
        # Resource declaration fails before the admission transaction. The
        # immutable snapshot remains for audit; no invocation or lease exists.
        with self.store.lock:
            invocations = self.store.db.execute(
                "SELECT COUNT(*) FROM participant_invocations"
            ).fetchone()[0]
            leases = self.store.db.execute(
                "SELECT COUNT(*) FROM dispatch_leases"
            ).fetchone()[0]
        self.assertEqual((invocations, leases), (0, 0))


    def test_non_primary_unscoped_primary_approval_does_not_authorize_secondary(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary(
            include_approval=False,
        )
        with patch("evo_experiments.monitor.sample_nvidia_smi", return_value=telemetry()):
            with self.assertRaises(DispatchProviderError):
                provider.chat([{"role": "user", "content": "approval must be scoped"}], max_tokens=64)
        self.assertEqual(fake.calls, 0)
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT status,decision_json FROM participant_invocations"
            ).fetchone()
        self.assertEqual(row["status"], "denied")
        self.assertIn("provider_compliance_not_approved", row["decision_json"])


    def test_snapshot_and_envelope_must_match_selected_descriptor_and_config(self):
        import hashlib
        import json
        from types import SimpleNamespace
        from evo_core.dispatch_admission import AdmissionError, _snapshot_matches
        from evo_core.runtime_invocation_snapshots import create_runtime_invocation_snapshot

        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        selected = runtime.select_participant(descriptor.participant_id)
        invocation_id = "selected-snapshot-integrity-test"
        create_runtime_invocation_snapshot(
            self.store, selected, invocation_id=invocation_id,
            invocation_kind="participant_completion",
        )
        valid = SimpleNamespace(
            invocation_id=invocation_id,
            participant_id=descriptor.participant_id,
            adapter_id=descriptor.adapter_id,
            adapter_contract_version=descriptor.adapter_contract_version,
            configuration_id=descriptor.configuration_id,
            configuration_revision_id=descriptor.configuration_revision_id,
            component_key=descriptor.component_key,
            component_version=descriptor.component_version,
        )
        wrong_envelope = SimpleNamespace(**{
            **valid.__dict__, "component_key": "primary_model",
        })
        with self.assertRaises(AdmissionError):
            _snapshot_matches(self.store.db, selected, wrong_envelope)

        row = self.store.db.execute(
            "SELECT snapshot_json FROM runtime_invocation_snapshots WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        snapshot = json.loads(row["snapshot_json"])
        snapshot["participant"]["integration_id"] = "integration_substituted"
        encoded = json.dumps(
            snapshot, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.store.db.execute("DROP TRIGGER runtime_snapshots_no_update")
        self.store.db.execute(
            "UPDATE runtime_invocation_snapshots SET snapshot_json=?,snapshot_hash=? WHERE invocation_id=?",
            (encoded, digest, invocation_id),
        )
        self.store.db.commit()
        with self.assertRaises(AdmissionError):
            _snapshot_matches(self.store.db, selected, valid)
        self.assertEqual(fake.calls, 0)


    def test_selected_runtime_rejects_adapter_that_does_not_own_bound_instance(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        wrong_adapter_reference = {}
        wrong_adapter = OpenAICompatibleParticipantAdapter(
            allowed_origins=("http://127.0.0.1:18997",),
            dispatch_authorizer=runtime.assistant.provider.controller.authorizer_for(
                wrong_adapter_reference
            ),
        )
        wrong_adapter_reference["adapter"] = wrong_adapter
        tampered = replace(
            runtime,
            additional_participant_bindings=((wrong_adapter, runtime.additional_participant_bindings[0][1]),),
        )
        with self.assertRaises(RuntimeBindingError):
            tampered.select_participant(descriptor.participant_id)
        self.assertEqual(fake.calls, 0)

    def test_controller_rejects_authorization_without_adapter_bound_callback(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        controller = runtime.assistant.provider.controller
        bound = runtime.additional_participant_bindings[0][1]
        self.assertFalse(controller.authorize("participant_invocation", bound, None))
        self.assertEqual(fake.calls, 0)

    def test_selected_runtime_rejects_duplicate_participant_ids(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        duplicate = replace(
            descriptor,
            participant_id=runtime.participant.participant_id,
        )
        tampered = replace(runtime, additional_participants=(duplicate,))
        with self.assertRaises(RuntimeBindingError):
            tampered.select_participant(runtime.participant.participant_id)
        self.assertEqual(fake.calls, 0)

    def test_non_primary_descriptor_substitution_is_rejected(self):
        runtime, provider, fake, descriptor, _ = self._runtime_with_secondary()
        bad_descriptor = replace(
            descriptor, integration_id="integration_substituted",
        )
        tampered = replace(
            runtime, additional_participants=(bad_descriptor,),
        )
        with self.assertRaises(RuntimeBindingError):
            tampered.select_participant(descriptor.participant_id)
        self.assertEqual(fake.calls, 0)



if __name__ == "__main__":
    unittest.main()
