import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_project, register_checkout, CheckoutPathConflictError
from evo_core.project_provisioning import (get_provisioning_operation, provision_project,
    ProvisioningConflictError, ProvisioningError, ProvisioningValidationError,
    recover_provisioning_operation)
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
        tracked = subprocess.run(["git", "-C", str(target), "ls-files"], capture_output=True, text=True)
        self.assertEqual(sorted(tracked.stdout.splitlines()), [".gitignore", "EVO_PROJECT.md", "README.md"])
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

        with patch("evo_core.project_provisioning.register_project_and_checkout", side_effect=RuntimeError("registry boom")):
            with self.assertRaises(Exception):
                provision_project(self.store, "Demo", str(self.parent))
        rows = self.store.db.execute(
            "SELECT status, error, project_id, checkout_id FROM project_provisioning_operations"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "recovery_required")
        self.assertIn("registry boom", rows[0]["error"])
        self.assertIsNone(rows[0]["project_id"])
        self.assertIsNone(rows[0]["checkout_id"])
        self.assertEqual(len(list(self.parent.iterdir())), 1)

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


    def test_symlink_parent_is_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        link.symlink_to("/")
        with self.assertRaises(ProvisioningValidationError):
            provision_project(self.store, "Demo", str(link))

    def test_existing_target_is_not_adopted(self):
        target = self.parent / "Demo-fixed"
        target.mkdir()
        (target / "marker.txt").write_text("keep", encoding="utf-8")
        # Force the generated directory name by monkeypatching _safe_directory_name.
        with patch("evo_core.project_provisioning._safe_directory_name", return_value="Demo-fixed"):
            with self.assertRaises(ProvisioningConflictError):
                provision_project(self.store, "Demo", str(self.parent))
        self.assertEqual((target / "marker.txt").read_text(), "keep")

    def test_operation_status_and_recovery(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        operation = get_provisioning_operation(self.store, result["operation_id"])
        self.assertEqual(operation["status"], "completed")
        recovered = recover_provisioning_operation(self.store, result["operation_id"])
        self.assertEqual(recovered["status"], "completed")

    def test_no_workspace_when_unbound(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        self.assertIsNone(result["workspace"])
        self.assertFalse(result["workspace_bound"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 0)


class ProjectProvisioningRecoveryTests(unittest.TestCase):
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

    def _provision(self):
        return provision_project(self.store, "Demo", str(self.parent))

    def test_recovery_completes_valid_state(self):
        result = self._provision()
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "completed")

    def test_recovery_is_idempotent(self):
        result = self._provision()
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='files_written' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        first = recover_provisioning_operation(self.store, op_id)
        second = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")

    def test_recovery_requires_directory(self):
        result = self._provision()
        op_id = result["operation_id"]
        target = Path(result["canonical_path"])
        # Remove the directory after registration.
        import shutil
        shutil.rmtree(target)
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("missing", recovered["error"])

    def test_recovery_rejects_symlink_replacement(self):
        result = self._provision()
        op_id = result["operation_id"]
        target = Path(result["canonical_path"])
        replacement = self.root / "replacement"
        replacement.mkdir()
        target.rename(self.root / "original")
        target.symlink_to(replacement)
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        try:
            recovered = recover_provisioning_operation(self.store, op_id)
            self.assertEqual(recovered["status"], "recovery_required")
        finally:
            if target.is_symlink():
                target.unlink()
            if (self.root / "original").exists():
                (self.root / "original").rename(target)

    def test_recovery_rejects_mismatched_checkout_path(self):
        result = self._provision()
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("UPDATE project_checkouts SET canonical_path=? WHERE checkout_id=?",
                                  ("/tmp/elsewhere", result["checkout"]["checkout_id"]))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("does not match", recovered["error"])

    def test_recovery_rejects_missing_workspace(self):
        config_result = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        result = provision_project(
            self.store,
            "Demo",
            str(self.parent),
            configuration_id=config_result["configuration"]["configuration_id"],
            configuration_revision_id=config_result["revision"]["revision_id"],
        )
        op_id = result["operation_id"]
        # Remove workspace record
        with self.store.lock:
            self.store.db.execute("DELETE FROM workspaces WHERE workspace_id=?", (result["workspace"]["workspace_id"],))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("workspace binding is missing", recovered["error"])

    def test_recovery_rejects_workspace_bound_to_another_project(self):
        config_result = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        result = provision_project(
            self.store,
            "Demo",
            str(self.parent),
            configuration_id=config_result["configuration"]["configuration_id"],
            configuration_revision_id=config_result["revision"]["revision_id"],
        )
        op_id = result["operation_id"]
        other_project = register_project(self.store, "Other")
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute("UPDATE workspaces SET project_id=? WHERE workspace_id=?",
                                  (other_project["project_id"], result["workspace"]["workspace_id"]))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("mismatched", recovered["error"])
        first = recover_provisioning_operation(self.store, op_id)
        second = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(first["status"], "recovery_required")
        self.assertEqual(second["status"], "recovery_required")

    def test_recovery_rejects_workspace_bound_to_another_checkout(self):
        config_result = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        result = provision_project(
            self.store,
            "Demo",
            str(self.parent),
            configuration_id=config_result["configuration"]["configuration_id"],
            configuration_revision_id=config_result["revision"]["revision_id"],
        )
        op_id = result["operation_id"]
        other_project = register_project(self.store, "Other")
        other_dir = self.root / "other-checkout"
        other_dir.mkdir()
        other_checkout = register_checkout(self.store, other_project["project_id"], other_dir)
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute("UPDATE workspaces SET checkout_id=? WHERE workspace_id=?",
                                  (other_checkout["checkout_id"], result["workspace"]["workspace_id"]))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("mismatched", recovered["error"])

    def test_recovery_propagates_database_errors(self):
        result = self._provision()
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        with patch("evo_core.project_provisioning._project_row", side_effect=RuntimeError("db boom")):
            with self.assertRaises(RuntimeError):
                recover_provisioning_operation(self.store, op_id)


class ProjectProvisioningRecoveryAndRollbackTests(unittest.TestCase):
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

    def test_rollback_preserves_replaced_project_directory(self):
        def modifier(target):
            replacement = target.parent / "replacement"
            replacement.mkdir()
            (replacement / "external.txt").write_text("keep", encoding="utf-8")
            target.rename(target.parent / "original")
            replacement.rename(target)

        operation_id, caught, row = self._fail_at_registry(modifier)
        self.assertIsNotNone(caught)
        self.assertEqual(row["status"], "recovery_required")
        self.assertIn("registry boom", row["error"])
        dirs = list(self.parent.iterdir())
        self.assertEqual(len(dirs), 2)
        replacement_dirs = [p for p in dirs if (p / "external.txt").exists()]
        self.assertEqual(len(replacement_dirs), 1)
        self.assertTrue((replacement_dirs[0] / "external.txt").exists())
        original_dirs = [p for p in dirs if p.name.startswith("original")]
        self.assertEqual(len(original_dirs), 1)

    def test_recovery_rejects_directory_replacement(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        op_id = result["operation_id"]
        target = Path(result["canonical_path"])
        replacement = self.root / "replacement"
        replacement.mkdir()
        target.rename(self.root / "original")
        target.mkdir()
        with self.store.lock:
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("identity could not be verified", recovered["error"])
        # Restore for cleanup.
        if target.exists():
            target.rmdir()
        (self.root / "original").rename(target)

    def test_recovery_rejects_missing_project(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute("DELETE FROM software_projects WHERE project_id=?", (result["project"]["project_id"],))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("project record is missing", recovered["error"])

    def test_recovery_rejects_missing_checkout(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("DELETE FROM project_checkouts WHERE checkout_id=?", (result["checkout"]["checkout_id"],))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("checkout record is missing", recovered["error"])

    def test_recovery_rejects_mismatched_checkout_project(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        op_id = result["operation_id"]
        other_project = register_project(self.store, "Other")
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute("UPDATE project_checkouts SET project_id=? WHERE checkout_id=?",
                                  (other_project["project_id"], result["checkout"]["checkout_id"]))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        recovered = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("does not belong", recovered["error"])

    def test_recovery_repeated_does_not_complete_mismatched_state(self):
        result = provision_project(self.store, "Demo", str(self.parent))
        op_id = result["operation_id"]
        with self.store.lock:
            self.store.db.execute("DELETE FROM project_checkouts WHERE checkout_id=?", (result["checkout"]["checkout_id"],))
            self.store.db.execute("UPDATE project_provisioning_operations SET status='registry_created' WHERE operation_id=?", (op_id,))
            self.store.db.commit()
        first = recover_provisioning_operation(self.store, op_id)
        second = recover_provisioning_operation(self.store, op_id)
        self.assertEqual(first["status"], "recovery_required")
        self.assertEqual(second["status"], "recovery_required")

    def test_rollback_preserves_replaced_starter_file(self):
        def modifier(target):
            path = target / "README.md"
            path.unlink()
            path.write_text("external replacement", encoding="utf-8")

        operation_id, caught, row = self._fail_at_registry(modifier)
        self.assertIsNotNone(caught)
        self.assertEqual(row["status"], "recovery_required")
        self.assertIn("registry boom", row["error"])
        dirs = list(self.parent.iterdir())
        self.assertEqual(len(dirs), 1)
        self.assertEqual((dirs[0] / "README.md").read_text(), "external replacement")

    def test_rollback_preserves_unrelated_file(self):
        def modifier(target):
            (target / "UNRELATED.txt").write_text("keep", encoding="utf-8")

        operation_id, caught, row = self._fail_at_registry(modifier)
        self.assertIsNotNone(caught)
        self.assertEqual(row["status"], "recovery_required")
        self.assertIn("registry boom", row["error"])
        dirs = list(self.parent.iterdir())
        self.assertEqual(len(dirs), 1)
        self.assertTrue((dirs[0] / "UNRELATED.txt").exists())
        self.assertEqual((dirs[0] / "UNRELATED.txt").read_text(), "keep")

    def test_rollback_preserves_unrelated_git_content(self):
        def modifier(target):
            (target / ".git" / "UNRELATED").write_text("keep", encoding="utf-8")

        operation_id, caught, row = self._fail_at_registry(modifier)
        self.assertIsNotNone(caught)
        self.assertEqual(row["status"], "recovery_required")
        self.assertIn("registry boom", row["error"])
        dirs = list(self.parent.iterdir())
        self.assertEqual(len(dirs), 1)
        self.assertTrue((dirs[0] / ".git" / "UNRELATED").exists())

    def test_rollback_preserves_replaced_git_directory(self):
        def modifier(target):
            git_dir = target / ".git"
            if git_dir.exists():
                import shutil
                shutil.rmtree(git_dir)
            git_dir.mkdir()
            (git_dir / "external").write_text("keep", encoding="utf-8")

        operation_id, caught, row = self._fail_at_registry(modifier)
        self.assertIsNotNone(caught)
        self.assertEqual(row["status"], "recovery_required")
        self.assertIn("registry boom", row["error"])
        dirs = list(self.parent.iterdir())
        self.assertEqual(len(dirs), 1)
        self.assertTrue((dirs[0] / ".git" / "external").exists())

    def _fail_at_registry(self, modifier):
        from unittest.mock import patch

        def boom(store, name, *, path, **kwargs):
            target = Path(path)
            modifier(target)
            raise RuntimeError("registry boom")

        caught = None
        with patch("evo_core.project_provisioning.register_project_and_checkout", side_effect=boom):
            try:
                provision_project(self.store, "Demo", str(self.parent))
            except Exception as exc:
                caught = exc
        row = self.store.db.execute(
            "SELECT operation_id, status, error FROM project_provisioning_operations ORDER BY created_at DESC, operation_id DESC LIMIT 1"
        ).fetchone()
        return (row["operation_id"] if row else None, caught, dict(row) if row else None)
