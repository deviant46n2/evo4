import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration, create_revision
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.workspace_binding_history import (
    list_workspace_binding_history,
    rebind_workspace,
)
from evo_core.workspaces import (
    WorkspaceConflictError,
    WorkspaceRelationshipError,
    WorkspaceValidationError,
    create_workspace,
)


class WorkspaceBindingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "registry.sqlite3")
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.checkout_path = self.root / "checkout"
        self.checkout_path.mkdir()
        self.checkout = register_checkout(
            self.store, self.project["project_id"], self.checkout_path
        )
        created = create_configuration(
            self.store, {"schema_version": 1, "components": {}}, name="Config"
        )
        self.configuration = created["configuration"]
        self.revision = created["revision"]
        self.workspace = create_workspace(
            self.store, "Workspace", self.project["project_id"],
            self.configuration["configuration_id"], self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_rebind_is_version_checked_and_records_old_and_new_binding(self):
        newer = create_revision(
            self.store, self.configuration["configuration_id"],
            {"schema_version": 1, "components": {"next": {}}},
            expected_version=self.configuration["version"],
            parent_revision_id=self.revision["revision_id"],
            change_summary="new revision",
        )
        rebound = rebind_workspace(
            self.store, self.workspace["workspace_id"],
            configuration_id=self.configuration["configuration_id"],
            configuration_revision_id=newer["revision_id"],
            checkout_id=self.checkout["checkout_id"],
            expected_version=1, actor="test-operator", reason="pin validated revision",
        )
        self.assertEqual(rebound["version"], 2)
        self.assertEqual(rebound["configuration_revision_id"], newer["revision_id"])
        history = list_workspace_binding_history(self.store, self.workspace["workspace_id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["from_version"], 1)
        self.assertEqual(history[0]["to_version"], 2)
        self.assertEqual(history[0]["old_revision_id"], self.revision["revision_id"])
        self.assertEqual(history[0]["new_revision_id"], newer["revision_id"])
        self.assertEqual(history[0]["actor"], "test-operator")
        self.assertEqual(history[0]["reason"], "pin validated revision")

    def test_stale_version_does_not_change_binding_or_history(self):
        with self.assertRaises(WorkspaceConflictError):
            rebind_workspace(
                self.store, self.workspace["workspace_id"],
                configuration_id=self.configuration["configuration_id"],
                configuration_revision_id=self.revision["revision_id"],
                checkout_id=None, expected_version=99, reason="stale attempt",
            )
        self.assertEqual(
            list_workspace_binding_history(self.store, self.workspace["workspace_id"]), []
        )

    def test_cross_project_checkout_rejected_without_partial_change(self):
        other = register_project(self.store, "Other project")
        other_path = self.root / "other-checkout"
        other_path.mkdir()
        other_checkout = register_checkout(self.store, other["project_id"], other_path)
        with self.assertRaises(WorkspaceRelationshipError):
            rebind_workspace(
                self.store, self.workspace["workspace_id"],
                configuration_id=self.configuration["configuration_id"],
                configuration_revision_id=self.revision["revision_id"],
                checkout_id=other_checkout["checkout_id"], expected_version=1,
                reason="must not cross projects",
            )
        self.assertEqual(
            list_workspace_binding_history(self.store, self.workspace["workspace_id"]), []
        )

    def test_history_is_append_only(self):
        newer = create_revision(
            self.store, self.configuration["configuration_id"],
            {"schema_version": 1, "components": {"next": {}}},
            expected_version=self.configuration["version"],
            parent_revision_id=self.revision["revision_id"],
            change_summary="new revision",
        )
        rebind_workspace(
            self.store, self.workspace["workspace_id"],
            configuration_id=self.configuration["configuration_id"],
            configuration_revision_id=newer["revision_id"],
            checkout_id=self.checkout["checkout_id"], expected_version=1,
            reason="create immutable history",
        )
        with self.store.lock:
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute(
                    "UPDATE workspace_binding_history SET reason='rewritten'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute("DELETE FROM workspace_binding_history")
            self.store.db.rollback()

    def test_unchanged_binding_rejected(self):
        with self.assertRaises(WorkspaceValidationError):
            rebind_workspace(
                self.store, self.workspace["workspace_id"],
                configuration_id=self.configuration["configuration_id"],
                configuration_revision_id=self.revision["revision_id"],
                checkout_id=self.checkout["checkout_id"], expected_version=1,
                reason="no-op",
            )


if __name__ == "__main__":
    unittest.main()
