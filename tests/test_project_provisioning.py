import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_project, register_checkout, CheckoutPathConflictError
from evo_core.project_provisioning import (provision_project, ProvisioningConflictError, ProvisioningError,
    ProvisioningValidationError)
from evo_core.store import EvoStore


class ProjectProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "evo.sqlite3")
        initialize_platform_registry(self.store)
        self.parent = self.root / "projects"
        self.parent.mkdir()

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_successful_provision_creates_expected_files_and_git_commit(self):
        result = provision_project(self.store, "Demo", str(self.parent), description="demo")
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["workspace_bound"])
        self.assertIsNone(result["workspace"])
        target = Path(result["canonical_path"])
        self.assertTrue(target.is_dir())
        self.assertEqual(sorted(p.name for p in target.iterdir()), [".git", ".gitignore", "EVO_PROJECT.md", "README.md"])
        self.assertTrue((target / ".git").is_dir())
        completed = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(result["project"]["name"], "Demo")
        self.assertEqual(result["checkout"]["canonical_path"], str(target.resolve()))
        projects = self.store.db.execute("SELECT COUNT(*) FROM software_projects").fetchone()[0]
        checkouts = self.store.db.execute("SELECT COUNT(*) FROM project_checkouts").fetchone()[0]
        self.assertEqual(projects, 1)
        self.assertEqual(checkouts, 1)

    def test_explicit_configuration_creates_workspace_binding(self):
        config = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        result = provision_project(
            self.store,
            "Demo",
            str(self.parent),
            configuration_id=config["configuration"]["configuration_id"],
            configuration_revision_id=config["revision"]["revision_id"],
        )
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["workspace_bound"])
        self.assertEqual(result["workspace"]["project_id"], result["project"]["project_id"])
        self.assertEqual(result["workspace"]["checkout_id"], result["checkout"]["checkout_id"])

    def test_nonexistent_parent_is_rejected(self):
        with self.assertRaises(ProvisioningValidationError):
            provision_project(self.store, "Demo", str(self.root / "missing"))

    def test_unsafe_root_is_rejected(self):
        with self.assertRaises(ProvisioningValidationError):
            provision_project(self.store, "Demo", "/")

    def test_ancestor_checkout_overlap_is_rejected(self):
        project = register_project(self.store, "Existing")
        existing = self.parent / "existing"
        existing.mkdir()
        register_checkout(self.store, project["project_id"], existing)
        with self.assertRaises(ProvisioningConflictError):
            provision_project(self.store, "Demo", str(existing))

    def test_sibling_checkouts_remain_allowed(self):
        project = register_project(self.store, "Existing")
        sibling = self.parent / "sibling"
        sibling.mkdir()
        register_checkout(self.store, project["project_id"], sibling)
        result = provision_project(self.store, "Demo", str(self.parent))
        self.assertEqual(result["status"], "completed")

    def test_git_unavailable_does_not_report_success(self):
        with patch("evo_core.project_provisioning.shutil.which", return_value=None):
            with self.assertRaises(Exception):
                provision_project(self.store, "Demo", str(self.parent))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM software_projects").fetchone()[0], 0)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_registry_failure_records_recoverable_partial_state(self):
        from unittest.mock import patch

        with patch("evo_core.project_provisioning.register_project", side_effect=RuntimeError("registry boom")):
            with self.assertRaises(Exception):
                provision_project(self.store, "Demo", str(self.parent))
        rows = self.store.db.execute(
            "SELECT status, error, project_id, checkout_id FROM project_provisioning_operations"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("registry boom", rows[0]["error"])
        self.assertIsNone(rows[0]["project_id"])
        self.assertIsNone(rows[0]["checkout_id"])
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_invalid_configuration_raises(self):
        with self.assertRaises(Exception):
            provision_project(
                self.store,
                "Demo",
                str(self.parent),
                configuration_id="missing",
                configuration_revision_id="missing",
            )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 0)

    def test_no_workspace_when_unbound(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        self.assertIsNone(result["workspace"])
        self.assertFalse(result["workspace_bound"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 0)
