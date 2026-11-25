import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from evo_core.ai_configurations import create_configuration, create_revision
from evo_core.config import EvoConfig
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.openai_compatible_adapter import ParticipantDispatchDisabledError
from evo_core.provider_endpoint import PinnedProviderTransport
from evo_core.runtime_binding import (
    RegistryDispatchDisabledError,
    RuntimeBindingError,
    build_workspace_runtime,
)
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace


def schema2_definition(*, model="model-a", endpoint="http://127.0.0.1:18997/v1",
                       persona="Persona A", max_tokens=777, context=16384,
                       allowed_commands=None, secret_refs=None):
    model_component = {
        "type": "model",
        "component_version": 1,
        "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
        "settings": {"endpoint": endpoint, "model": model, "timeout_seconds": 90},
    }
    if secret_refs is not None:
        model_component["secret_refs"] = secret_refs
    return {
        "schema_version": 2,
        "components": {
            "primary_model": model_component,
            "assistant_runtime": {
                "type": "assistant_runtime",
                "component_version": 1,
                "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                "settings": {
                    "model_component": "primary_model",
                    "persona_prompt": persona,
                    "max_output_tokens": max_tokens,
                    "temperature": 0.35,
                    "context_window_tokens": context,
                    "history_messages": 7,
                    "max_history_chars": 9000,
                    "memory_limit": 3,
                },
            },
            "project_policy": {
                "type": "command_policy",
                "component_version": 1,
                "adapter": {"id": "evo_command_policy", "contract_version": 1},
                "settings": {"allowed_commands": allowed_commands or [["python", "-m", "unittest"]]},
            },
        },
        "entrypoints": {"assistant": "assistant_runtime"},
    }


class RegistryRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "runtime.sqlite3")
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Runtime project")
        self.checkout_path = self.root / "checkout"
        self.checkout_path.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.checkout_path)
        created = create_configuration(
            self.store, schema2_definition(), name="Runtime config"
        )
        self.configuration = created["configuration"]
        self.revision = created["revision"]
        self.workspace = create_workspace(
            self.store, "Runtime workspace", self.project["project_id"],
            self.configuration["configuration_id"], self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        self.base_config = EvoConfig(
            base_url="http://global.invalid/v1",
            api_key="global-key",
            model="global-model",
            timeout_seconds=600,
            database=self.root / "runtime.sqlite3",
            max_tokens=2048,
            temperature=0.2,
            system_prompt="Trusted Evo policy.",
            memory_limit=8,
            history_messages=16,
            workspace_root=self.root,
            allowed_commands=(("python",),),
            max_history_chars=40000,
            context_window_tokens=49152,
            allowed_secret_env_vars=(),
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def build(self):
        return build_workspace_runtime(
            self.store, self.base_config, self.workspace["workspace_id"]
        )

    def test_runtime_uses_exact_revision_not_global_toml(self):
        runtime = self.build()
        self.assertEqual(runtime.assistant.config.model, "model-a")
        self.assertEqual(runtime.assistant.config.base_url, "http://127.0.0.1:18997/v1")
        self.assertEqual(runtime.assistant.config.max_tokens, 777)
        self.assertEqual(runtime.assistant.config.temperature, 0.35)
        self.assertEqual(runtime.assistant.config.context_window_tokens, 16384)
        self.assertEqual(runtime.assistant.config.history_messages, 7)
        self.assertEqual(runtime.assistant.config.max_history_chars, 9000)
        self.assertEqual(runtime.assistant.config.memory_limit, 3)
        self.assertIn("Persona A", runtime.assistant.config.system_prompt)
        self.assertIn("Trusted Evo policy.", runtime.assistant.config.system_prompt)
        self.assertEqual(runtime.assistant.provider.model, "model-a")
        self.assertEqual(runtime.participant.configuration_revision_id, self.revision["revision_id"])
        self.assertEqual(runtime.bound_participant.model, "model-a")
        self.assertEqual(runtime.bound_participant.max_output_tokens, 777)
        self.assertEqual(runtime.bound_participant.temperature, 0.35)
        self.assertIsInstance(runtime.participant_adapter._provider_for(runtime.bound_participant).transport, PinnedProviderTransport)
        self.assertEqual(runtime.effective_allowed_commands, (("python", "-m", "unittest"),))

    def test_global_model_changes_do_not_change_bound_runtime(self):
        changed = replace(self.base_config, model="other-global", base_url="https://elsewhere.invalid",
                          max_tokens=123, temperature=1.7, context_window_tokens=8192)
        runtime = build_workspace_runtime(
            self.store, changed, self.workspace["workspace_id"]
        )
        self.assertEqual(runtime.assistant.config.model, "model-a")
        self.assertEqual(runtime.assistant.config.max_tokens, 777)
        self.assertEqual(runtime.assistant.config.context_window_tokens, 16384)

    def test_older_pinned_revision_remains_bound_after_new_revision(self):
        newer = create_revision(
            self.store, self.configuration["configuration_id"],
            schema2_definition(model="model-b", max_tokens=999),
            expected_version=self.configuration["version"],
            parent_revision_id=self.revision["revision_id"],
            change_summary="newer config",
        )
        runtime = self.build()
        self.assertEqual(runtime.revision_id, self.revision["revision_id"])
        self.assertEqual(runtime.assistant.config.model, "model-a")
        self.assertNotEqual(runtime.revision_id, newer["revision_id"])

    def test_registry_runtime_does_not_accept_provider_factory_override(self):
        with self.assertRaises(TypeError):
            build_workspace_runtime(
                self.store, self.base_config, self.workspace["workspace_id"],
                provider_factory=lambda *args, **kwargs: object(),
            )

    def test_live_dispatch_is_explicitly_disabled(self):
        runtime = build_workspace_runtime(
            self.store, self.base_config, self.workspace["workspace_id"]
        )
        self.assertFalse(runtime.dispatch_enabled)
        with self.assertRaises(RegistryDispatchDisabledError):
            runtime.require_dispatch_enabled()
        with self.assertRaises(RegistryDispatchDisabledError):
            runtime.assistant.provider.chat([])
        with self.assertRaises(ParticipantDispatchDisabledError):
            list(runtime.participant_adapter.invoke(runtime.bound_participant, None))

    def test_binding_change_invalidates_existing_runtime(self):
        runtime = self.build()
        from evo_core.workspaces import archive_workspace
        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=1)
        with self.assertRaises(RuntimeBindingError):
            runtime.assert_current(self.store)

    def test_schema1_workspace_is_not_executable(self):
        legacy = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="legacy")
        workspace = create_workspace(
            self.store, "Legacy workspace", self.project["project_id"],
            legacy["configuration"]["configuration_id"], legacy["revision"]["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        with self.assertRaises(RuntimeBindingError):
            build_workspace_runtime(self.store, self.base_config, workspace["workspace_id"])

    def test_missing_secret_allowlist_fails_closed(self):
        secret_config = schema2_definition(secret_refs={"api_key": "env:EVO_RUNTIME_TEST_KEY"})
        created = create_configuration(self.store, secret_config, name="secret config")
        workspace = create_workspace(
            self.store, "Secret workspace", self.project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        with self.assertRaises(RuntimeBindingError):
            build_workspace_runtime(self.store, self.base_config, workspace["workspace_id"])

    def test_secret_resolution_is_transient_and_not_in_provenance(self):
        secret_config = schema2_definition(secret_refs={"api_key": "env:EVO_RUNTIME_TEST_KEY"})
        created = create_configuration(self.store, secret_config, name="secret config")
        workspace = create_workspace(
            self.store, "Secret workspace", self.project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        os.environ["EVO_RUNTIME_TEST_KEY"] = "runtime-secret-value"
        try:
            config = replace(self.base_config, allowed_secret_env_vars=("EVO_RUNTIME_TEST_KEY",))
            runtime = build_workspace_runtime(self.store, config, workspace["workspace_id"])
            self.assertEqual(runtime.assistant.config.api_key, "no-key")
            self.assertEqual(runtime.participant_adapter._provider_for(runtime.bound_participant).api_key, "runtime-secret-value")
            self.assertNotIn("runtime-secret-value", repr(runtime.bound_participant))
            self.assertNotIn("runtime-secret-value", repr(runtime.provenance))
            self.assertNotIn("runtime-secret-value", repr(runtime.participant))
        finally:
            os.environ.pop("EVO_RUNTIME_TEST_KEY", None)


if __name__ == "__main__":
    unittest.main()
