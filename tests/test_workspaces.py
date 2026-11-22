import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import (
    register_checkout,
    register_project,
    update_checkout,
)
from evo_core.store import EvoStore
from evo_core.workspaces import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspaceRelationshipError,
    WorkspaceValidationError,
    archive_workspace,
    create_workspace,
    get_workspace,
    list_workspaces,
    reactivate_workspace,
)

VALID_DEFINITION = {"schema_version": 1, "components": {}}


def make_store(db_path):
    store = EvoStore(db_path)
    initialize_platform_registry(store)
    return store


def make_project(store, temp_root):
    project = register_project(store, "Project")
    directory = temp_root / f"checkout-{project['project_id']}"
    directory.mkdir()
    checkout = register_checkout(store, project["project_id"], directory)
    return project, checkout, directory


def make_configuration(store):
    result = create_configuration(store, VALID_DEFINITION, name="cfg")
    return result["configuration"], result["revision"]


class WorkspaceCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "ws.sqlite3"
        self.store = make_store(self.db_path)
        self.project, self.checkout, self.directory = make_project(self.store, self.root)
        self.configuration, self.revision = make_configuration(self.store)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_create_without_checkout(self):
        ws = create_workspace(
            self.store,
            "Workspace",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
        )
        self.assertEqual(ws["status"], "active")
        self.assertEqual(ws["version"], 1)
        self.assertIsNone(ws["checkout_id"])
        self.assertEqual(ws["configuration_revision_id"], self.revision["revision_id"])

    def test_create_with_checkout(self):
        ws = create_workspace(
            self.store,
            "Workspace",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        self.assertEqual(ws["checkout_id"], self.checkout["checkout_id"])

    def test_get_and_list(self):
        ws = create_workspace(
            self.store,
            "Workspace",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
        )
        fetched = get_workspace(self.store, ws["workspace_id"])
        self.assertEqual(fetched["workspace_id"], ws["workspace_id"])
        listed = list_workspaces(self.store)
        self.assertEqual(len(listed), 1)
        by_project = list_workspaces(self.store, project_id=self.project["project_id"])
        self.assertEqual(len(by_project), 1)
        by_config = list_workspaces(self.store, configuration_id=self.configuration["configuration_id"])
        self.assertEqual(len(by_config), 1)
        by_status = list_workspaces(self.store, status="active")
        self.assertEqual(len(by_status), 1)

    def test_invalid_inputs(self):
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, "   ", self.project["project_id"], self.configuration["configuration_id"], self.revision["revision_id"])
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, 123, self.project["project_id"], self.configuration["configuration_id"], self.revision["revision_id"])
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, "ws", "", self.configuration["configuration_id"], self.revision["revision_id"])
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, "ws", self.project["project_id"], "", self.revision["revision_id"])
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], "")
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], self.revision["revision_id"], checkout_id="")

    def test_description_none_rejected(self):
        before = len(list_workspaces(self.store))
        with self.assertRaises(WorkspaceValidationError):
            create_workspace(
                self.store,
                "ws",
                self.project["project_id"],
                self.configuration["configuration_id"],
                self.revision["revision_id"],
                description=None,
            )
        after = len(list_workspaces(self.store))
        self.assertEqual(before, after)

    def test_list_status_invalid_type(self):
        with self.assertRaises(WorkspaceValidationError):
            list_workspaces(self.store, status=["active"])
        with self.assertRaises(WorkspaceValidationError):
            list_workspaces(self.store, status={"status": "active"})

    def test_nonexistent_project(self):
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", "missing", self.configuration["configuration_id"], self.revision["revision_id"])

    def test_archived_project(self):
        from evo_core.project_checkouts import archive_project

        archive_project(self.store, self.project["project_id"], expected_version=1)
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], self.revision["revision_id"])

    def test_nonexistent_configuration(self):
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", self.project["project_id"], "missing", self.revision["revision_id"])

    def test_archived_configuration(self):
        from evo_core.ai_configurations import archive_configuration

        archive_configuration(self.store, self.configuration["configuration_id"], expected_version=1)
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], self.revision["revision_id"])

    def test_nonexistent_revision(self):
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], "missing")

    def test_revision_from_other_configuration(self):
        other_config, other_revision = make_configuration(self.store)
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(self.store, "ws", self.project["project_id"], self.configuration["configuration_id"], other_revision["revision_id"])

    def test_older_revision_accepted(self):
        newer = create_revision_for_test(self.store, self.configuration["configuration_id"], self.configuration["version"])
        ws = create_workspace(
            self.store,
            "ws",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
        )
        self.assertEqual(ws["configuration_revision_id"], self.revision["revision_id"])

    def test_nonexistent_checkout(self):
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(
                self.store,
                "ws",
                self.project["project_id"],
                self.configuration["configuration_id"],
                self.revision["revision_id"],
                checkout_id="missing",
            )

    def test_checkout_wrong_project(self):
        other_project, other_checkout, _ = make_project(self.store, self.root)
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(
                self.store,
                "ws",
                self.project["project_id"],
                self.configuration["configuration_id"],
                self.revision["revision_id"],
                checkout_id=other_checkout["checkout_id"],
            )

    def test_checkout_missing_status(self):
        update_checkout(self.store, self.checkout["checkout_id"], {}, expected_version=self.checkout["version"]) if False else None
        from evo_core.project_checkouts import refresh_checkout_availability

        self.directory.rename(self.root / "moved")
        refresh_checkout_availability(self.store, self.checkout["checkout_id"])
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(
                self.store,
                "ws",
                self.project["project_id"],
                self.configuration["configuration_id"],
                self.revision["revision_id"],
                checkout_id=self.checkout["checkout_id"],
            )
        (self.root / "moved").rename(self.directory)

    def test_checkout_unavailable_status(self):
        self.directory.rmdir() if False else None
        # Make directory a file to force unavailable.
        for child in self.directory.iterdir():
            child.unlink()
        self.directory.rmdir()
        self.directory.write_text("not dir")
        from evo_core.project_checkouts import refresh_checkout_availability

        refresh_checkout_availability(self.store, self.checkout["checkout_id"])
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(
                self.store,
                "ws",
                self.project["project_id"],
                self.configuration["configuration_id"],
                self.revision["revision_id"],
                checkout_id=self.checkout["checkout_id"],
            )
        self.directory.unlink()
        self.directory.mkdir()
        (self.directory / "file.txt").write_text("data", encoding="utf-8")

    def test_shared_checkout(self):
        ws1 = create_workspace(
            self.store,
            "ws1",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        ws2 = create_workspace(
            self.store,
            "ws2",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        self.assertEqual(ws1["checkout_id"], ws2["checkout_id"])


class WorkspaceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "ws.sqlite3"
        self.store = make_store(self.db_path)
        self.project, self.checkout, self.directory = make_project(self.store, self.root)
        self.configuration, self.revision = make_configuration(self.store)
        self.workspace = create_workspace(
            self.store,
            "Workspace",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_archive_reactivate(self):
        ws_id = self.workspace["workspace_id"]
        archived = archive_workspace(self.store, ws_id, expected_version=1)
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["version"], 2)
        reactivated = reactivate_workspace(self.store, ws_id, expected_version=2)
        self.assertEqual(reactivated["status"], "active")
        self.assertEqual(reactivated["version"], 3)

    def test_stale_versions(self):
        ws_id = self.workspace["workspace_id"]
        with self.assertRaises(WorkspaceConflictError):
            archive_workspace(self.store, ws_id, expected_version=999)
        ws = get_workspace(self.store, ws_id)
        self.assertEqual(ws["version"], 1)
        self.assertEqual(ws["status"], "active")

    def test_invalid_expected_versions(self):
        ws_id = self.workspace["workspace_id"]
        for value in (True, False, 1.0, "1", 0, -1, None):
            with self.subTest(value=value):
                with self.assertRaises(WorkspaceValidationError):
                    archive_workspace(self.store, ws_id, expected_version=value)

    def test_reactivation_project_archived(self):
        from evo_core.project_checkouts import archive_project

        ws_id = self.workspace["workspace_id"]
        archive_workspace(self.store, ws_id, expected_version=1)
        archive_project(self.store, self.project["project_id"], expected_version=1)
        with self.assertRaises(WorkspaceRelationshipError):
            reactivate_workspace(self.store, ws_id, expected_version=2)

    def test_reactivation_configuration_archived(self):
        from evo_core.ai_configurations import archive_configuration

        ws_id = self.workspace["workspace_id"]
        archive_workspace(self.store, ws_id, expected_version=1)
        archive_configuration(self.store, self.configuration["configuration_id"], expected_version=1)
        with self.assertRaises(WorkspaceRelationshipError):
            reactivate_workspace(self.store, ws_id, expected_version=2)

    def test_reactivation_checkout_unavailable(self):
        ws_id = self.workspace["workspace_id"]
        archive_workspace(self.store, ws_id, expected_version=1)
        from evo_core.project_checkouts import refresh_checkout_availability

        self.directory.rmdir() if False else None
        for child in self.directory.iterdir():
            child.unlink()
        self.directory.rmdir()
        self.directory.write_text("not dir")
        refresh_checkout_availability(self.store, self.checkout["checkout_id"])
        with self.assertRaises(WorkspaceRelationshipError):
            reactivate_workspace(self.store, ws_id, expected_version=2)
        self.directory.unlink()
        self.directory.mkdir()
        (self.directory / "file.txt").write_text("data", encoding="utf-8")
        refresh_checkout_availability(self.store, self.checkout["checkout_id"])

    def test_pinned_revision_unchanged(self):
        ws_id = self.workspace["workspace_id"]
        original_revision = self.workspace["configuration_revision_id"]
        archive_workspace(self.store, ws_id, expected_version=1)
        reactivate_workspace(self.store, ws_id, expected_version=2)
        ws = get_workspace(self.store, ws_id)
        self.assertEqual(ws["configuration_revision_id"], original_revision)

    def test_failed_operation_leaves_no_partial_row(self):
        before = len(list_workspaces(self.store))
        with self.assertRaises(WorkspaceRelationshipError):
            create_workspace(
                self.store,
                "bad",
                self.project["project_id"],
                self.configuration["configuration_id"],
                "missing-revision",
            )
        after = len(list_workspaces(self.store))
        self.assertEqual(before, after)
        # A subsequent valid operation succeeds.
        ws = create_workspace(
            self.store,
            "good",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
        )
        self.assertIsNotNone(ws["workspace_id"])


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "ws.sqlite3"
        self.store = make_store(self.db_path)
        self.project, self.checkout, self.directory = make_project(self.store, self.root)
        self.configuration, self.revision = make_configuration(self.store)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_cross_project_checkout_rejected(self):
        other_project, other_checkout, _ = make_project(self.store, self.root)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(
                        "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        ("ws-x", "ws", self.project["project_id"], other_checkout["checkout_id"], self.configuration["configuration_id"], self.revision["revision_id"], "active", now, now),
                    )
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()

    def test_cross_configuration_revision_rejected(self):
        other_config, other_revision = make_configuration(self.store)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(
                        "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        ("ws-y", "ws", self.project["project_id"], None, self.configuration["configuration_id"], other_revision["revision_id"], "active", now, now),
                    )
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()


def create_revision_for_test(store, configuration_id, expected_version):
    from evo_core.ai_configurations import create_revision

    return create_revision(store, configuration_id, VALID_DEFINITION, expected_version=expected_version)


if __name__ == "__main__":
    unittest.main()
