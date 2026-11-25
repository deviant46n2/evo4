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
from evo_core.dispatch_provider import DispatchProviderError
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

    def chat(self, messages, max_tokens=2048, temperature=0.2, on_token=None,
             tools=None, *, timeout_seconds=None):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if on_token:
            on_token("admitted ")
            on_token("answer")
        return {
            "content": "admitted answer", "tool_calls": [],
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


if __name__ == "__main__":
    unittest.main()
