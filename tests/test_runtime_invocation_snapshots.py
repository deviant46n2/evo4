import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.config import EvoConfig
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.runtime_binding import build_workspace_runtime, RuntimeBindingError
from evo_core.runtime_invocation_snapshots import (
    RuntimeSnapshotError,
    create_runtime_invocation_snapshot,
    get_runtime_invocation_snapshot,
    list_runtime_invocation_snapshots,
)
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace, archive_workspace


def definition(secret=False):
    model = {
        "type": "model", "component_version": 1,
        "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
        "settings": {"endpoint": "http://127.0.0.1:18997/v1", "model": "snapshot-model",
                     "timeout_seconds": 45},
    }
    if secret:
        model["secret_refs"] = {"api_key": "env:EVO_SNAPSHOT_TEST_KEY"}
    return {
        "schema_version": 2,
        "components": {
            "model": model,
            "assistant": {
                "type": "assistant_runtime", "component_version": 1,
                "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                "settings": {"model_component": "model", "persona_prompt": "Snapshot persona",
                             "max_output_tokens": 512, "temperature": 0.2,
                             "context_window_tokens": 8192, "history_messages": 4,
                             "max_history_chars": 4000, "memory_limit": 2},
            },
            "policy": {
                "type": "command_policy", "component_version": 1,
                "adapter": {"id": "evo_command_policy", "contract_version": 1},
                "settings": {"allowed_commands": [["python", "-m", "unittest"]]},
            },
        },
        "entrypoints": {"assistant": "assistant"},
    }


class FakeProvider:
    def __init__(self, endpoint, api_key, model, timeout):
        self.base_url, self.api_key, self.model, self.timeout = endpoint, api_key, model, timeout


class RuntimeInvocationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "snapshot.sqlite3")
        initialize_platform_registry(self.store)
        project = register_project(self.store, "Snapshot project")
        checkout_path = self.root / "checkout"
        checkout_path.mkdir()
        checkout = register_checkout(self.store, project["project_id"], checkout_path)
        created = create_configuration(self.store, definition(), name="Snapshot config")
        self.workspace = create_workspace(
            self.store, "Snapshot workspace", project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.base_config = EvoConfig(
            base_url="http://global.invalid/v1", api_key="GLOBAL-SECRET",
            model="global-model", timeout_seconds=600, database=self.root / "snapshot.sqlite3",
            max_tokens=2048, temperature=0.1, system_prompt="Trusted policy",
            memory_limit=8, history_messages=16, workspace_root=self.root,
            allowed_commands=(("python",),), max_history_chars=40000,
            context_window_tokens=49152, allowed_secret_env_vars=(),
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def build(self, config=None):
        return build_workspace_runtime(
            self.store, config or self.base_config, self.workspace["workspace_id"],
            provider_factory=FakeProvider,
        )

    def test_persists_exact_secret_safe_snapshot_and_integrity_hash(self):
        runtime = self.build()
        record = create_runtime_invocation_snapshot(
            self.store, runtime, invocation_id="invocation-001"
        )
        loaded = get_runtime_invocation_snapshot(self.store, "invocation-001")
        self.assertEqual(record["snapshot_hash"], loaded["snapshot_hash"])
        self.assertEqual(loaded["snapshot"]["revision_id"], runtime.revision_id)
        self.assertEqual(loaded["snapshot"]["runtime_config"]["model"], "snapshot-model")
        self.assertFalse(loaded["snapshot"]["dispatch_enabled"])
        encoded = repr(loaded["snapshot"])
        self.assertNotIn("GLOBAL-SECRET", encoded)
        self.assertNotIn("api_key", loaded["snapshot"]["runtime_config"])
        self.assertEqual(len(list_runtime_invocation_snapshots(
            self.store, self.workspace["workspace_id"]
        )), 1)

    def test_secret_reference_is_recorded_but_resolved_value_is_not(self):
        created = create_configuration(self.store, definition(secret=True), name="Secret config")
        from evo_core.workspace_binding_history import rebind_workspace
        rebind_workspace(
            self.store, self.workspace["workspace_id"],
            configuration_id=created["configuration"]["configuration_id"],
            configuration_revision_id=created["revision"]["revision_id"],
            checkout_id=self.workspace["checkout_id"], expected_version=1,
            actor="test", reason="secret snapshot test",
        )
        os.environ["EVO_SNAPSHOT_TEST_KEY"] = "DO-NOT-PERSIST-THIS"
        try:
            config = replace(self.base_config, allowed_secret_env_vars=("EVO_SNAPSHOT_TEST_KEY",))
            runtime = self.build(config)
            record = create_runtime_invocation_snapshot(self.store, runtime, invocation_id="inv-secret")
            loaded = get_runtime_invocation_snapshot(self.store, "inv-secret")
            self.assertIn(["api_key", "env:EVO_SNAPSHOT_TEST_KEY"],
                          loaded["snapshot"]["provenance"]["secret_reference_names"])
            self.assertNotIn("DO-NOT-PERSIST-THIS", repr(loaded))
            self.assertNotIn("api_key", loaded["snapshot"]["runtime_config"])
        finally:
            os.environ.pop("EVO_SNAPSHOT_TEST_KEY", None)

    def test_stale_runtime_cannot_be_snapshotted(self):
        runtime = self.build()
        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=1)
        with self.assertRaises(RuntimeBindingError):
            create_runtime_invocation_snapshot(self.store, runtime, invocation_id="inv-stale")
        self.assertIsNone(get_runtime_invocation_snapshot(self.store, "inv-stale"))

    def test_snapshot_is_append_only_and_invocation_id_unique(self):
        runtime = self.build()
        create_runtime_invocation_snapshot(self.store, runtime, invocation_id="inv-unique")
        with self.assertRaises(Exception):
            create_runtime_invocation_snapshot(self.store, runtime, invocation_id="inv-unique")
        with self.assertRaises(Exception):
            self.store.db.execute(
                "UPDATE runtime_invocation_snapshots SET snapshot_hash='changed' WHERE invocation_id='inv-unique'"
            )
        with self.assertRaises(Exception):
            self.store.db.execute(
                "DELETE FROM runtime_invocation_snapshots WHERE invocation_id='inv-unique'"
            )
        self.store.db.rollback()

    def test_read_detects_snapshot_tampering(self):
        runtime = self.build()
        create_runtime_invocation_snapshot(self.store, runtime, invocation_id="inv-tamper")
        self.store.db.execute(
            "DROP TRIGGER runtime_snapshots_no_update"
        )
        self.store.db.execute(
            "UPDATE runtime_invocation_snapshots SET snapshot_json='{}' WHERE invocation_id='inv-tamper'"
        )
        self.store.db.commit()
        with self.assertRaises(RuntimeSnapshotError):
            get_runtime_invocation_snapshot(self.store, "inv-tamper")


if __name__ == "__main__":
    unittest.main()
