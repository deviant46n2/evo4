import subprocess
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.task_workspaces import create_task_workspace, _record, get_task_workspace_operation
from evo_core.task_workspace_files import (
    list_task_workspace_files, read_task_workspace_file,
    apply_task_workspace_file, list_task_workspace_file_changes,
)
from evo_core.workspaces import create_workspace


DEFINITION = {"schema_version": 1, "components": {}}


class TaskWorkspaceFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "evo.sqlite3")
        initialize_platform_registry(self.store)
        project = register_project(self.store, "Files")
        self.source = self.root / "source"
        self.source.mkdir()
        self._git(self.source, "init", "--initial-branch=main")
        self._git(self.source, "config", "user.name", "Test")
        self._git(self.source, "config", "user.email", "test@example.invalid")
        (self.source / "README.txt").write_text("baseline\n", encoding="utf-8")
        self._git(self.source, "add", "README.txt")
        self._git(self.source, "commit", "-m", "initial")
        revision = self._git(self.source, "rev-parse", "HEAD")
        checkout = register_checkout(
            self.store, project["project_id"], self.source,
            branch_or_ref="main", last_known_commit=revision,
        )
        config = create_configuration(self.store, DEFINITION, name="config")
        self.parent = create_workspace(
            self.store, "Parent", project["project_id"],
            config["configuration"]["configuration_id"],
            config["revision"]["revision_id"], checkout_id=checkout["checkout_id"],
        )
        self.destination = self.root / "task-worktrees"
        self.destination.mkdir()
        self.operation = create_task_workspace(
            self.store, self.parent["workspace_id"], "files-task", self.destination,
        )
        self.task_root = Path(self.operation["canonical_path"])

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    @staticmethod
    def _git(path, *args):
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def test_lists_one_directory_level_and_returns_revision_provenance(self):
        (self.task_root / "src").mkdir()
        (self.task_root / "src" / "main.py").write_text("print('hello')\n")
        result = list_task_workspace_files(self.store, self.operation["operation_id"])
        self.assertEqual(result["source_revision"], self.operation["source_revision"])
        self.assertIn("src", {item["name"] for item in result["items"]})
        self.assertNotIn(".git", {item["name"] for item in result["items"]})
        nested = list_task_workspace_files(
            self.store, self.operation["operation_id"], path="src",
        )
        self.assertEqual(nested["items"][0]["path"], "src/main.py")

    def test_directory_symlinks_are_not_traversed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        (self.task_root / "linked-dir").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            list_task_workspace_files(
                self.store, self.operation["operation_id"], path="linked-dir",
            )
        listing = list_task_workspace_files(self.store, self.operation["operation_id"])
        entry = next(item for item in listing["items"] if item["name"] == "linked-dir")
        self.assertEqual(entry["kind"], "symlink")

    def test_listing_limit_is_bounded_and_reports_truncation(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.task_root / name).write_text(name)
        result = list_task_workspace_files(
            self.store, self.operation["operation_id"], limit=2,
        )
        self.assertEqual(len(result["items"]), 2)
        self.assertGreater(result["total"], 2)
        self.assertTrue(result["truncated"])

    def test_reads_utf8_file_with_size_and_revision_metadata(self):
        (self.task_root / "notes.txt").write_text("Evo workspace ✓\n", encoding="utf-8")
        result = read_task_workspace_file(
            self.store, self.operation["operation_id"], "notes.txt",
        )
        self.assertEqual(result["content"], "Evo workspace ✓\n")
        self.assertEqual(result["size_bytes"], len("Evo workspace ✓\n".encode()))
        self.assertEqual(result["source_revision"], self.operation["source_revision"])

    def test_rejects_traversal_absolute_paths_and_backslashes(self):
        for path in ("../outside", "/etc/passwd", "a/../../outside", "a\\..\\outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                list_task_workspace_files(self.store, self.operation["operation_id"], path=path)
        with self.assertRaises(ValueError):
            read_task_workspace_file(self.store, self.operation["operation_id"], "../outside")

    def test_symlinks_are_reported_but_never_followed(self):
        outside = self.root / "outside.txt"
        outside.write_text("secret")
        (self.task_root / "escape.txt").symlink_to(outside)
        listing = list_task_workspace_files(self.store, self.operation["operation_id"])
        entry = next(item for item in listing["items"] if item["name"] == "escape.txt")
        self.assertEqual(entry["kind"], "symlink")
        with self.assertRaises(ValueError):
            read_task_workspace_file(self.store, self.operation["operation_id"], "escape.txt")

    def test_rejects_binary_oversized_and_excluded_files(self):
        (self.task_root / "binary.dat").write_bytes(b"abc\x00def")
        (self.task_root / "large.txt").write_text("x" * 20)
        with self.assertRaises(ValueError):
            read_task_workspace_file(self.store, self.operation["operation_id"], "binary.dat")
        with self.assertRaises(ValueError):
            read_task_workspace_file(
                self.store, self.operation["operation_id"], "large.txt", max_bytes=10,
            )
        with self.assertRaises(ValueError):
            read_task_workspace_file(self.store, self.operation["operation_id"], ".git/HEAD")

    def test_rejects_unfinished_operation_and_invalid_limits(self):
        _record(self.store, self.operation["operation_id"], status="recovery_required")
        with self.assertRaises(ValueError):
            list_task_workspace_files(self.store, self.operation["operation_id"])
        self.assertEqual(
            get_task_workspace_operation(self.store, self.operation["operation_id"])["status"],
            "recovery_required",
        )
        with self.assertRaises(ValueError):
            list_task_workspace_files(self.store, self.operation["operation_id"], limit=0)
        with self.assertRaises(ValueError):
            read_task_workspace_file(self.store, self.operation["operation_id"], "README.txt", max_bytes=0)



    def test_approved_apply_creates_file_and_records_audit(self):
        (self.task_root / "src").mkdir()
        result = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "src/new.py",
            "print('created')\\n", approved=True,
        )
        self.assertEqual((self.task_root / "src" / "new.py").read_text(), "print('created')\\n")
        self.assertIsNone(result["before_sha256"])
        history = list_task_workspace_file_changes(self.store, self.operation["operation_id"])
        self.assertEqual(history["items"][0]["change_id"], result["change_id"])

    def test_apply_requires_approval_and_expected_hash_for_replacement(self):
        import hashlib
        target = self.task_root / "README.txt"
        original = target.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "README.txt", "unapproved", expected_sha256=digest)
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "README.txt", "stale", expected_sha256="0" * 64, approved=True)
        self.assertEqual(target.read_bytes(), original)
        result = apply_task_workspace_file(self.store, self.operation["operation_id"], "README.txt", "approved update\\n", expected_sha256=digest, approved=True)
        self.assertEqual(target.read_text(), "approved update\\n")
        self.assertEqual(result["before_sha256"], digest)

    def test_apply_does_not_replace_existing_file_without_expected_hash(self):
        target = self.task_root / "README.txt"
        original = target.read_bytes()
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "README.txt", "replacement", approved=True)
        self.assertEqual(target.read_bytes(), original)

    def test_apply_rejects_symlinks_hardlinks_and_excluded_paths(self):
        import hashlib
        import os
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        (self.task_root / "linked.txt").symlink_to(outside)
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "linked.txt", "nope", approved=True)
        hard = self.task_root / "hard.txt"
        os.link(outside, hard)
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "hard.txt", "nope", expected_sha256=hashlib.sha256(b"outside").hexdigest(), approved=True)
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], ".git/config", "nope", approved=True)

    def test_apply_rejects_oversized_and_binary_content(self):
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "large.txt", "x" * (1024 * 1024 + 1), approved=True)
        with self.assertRaises(ValueError):
            apply_task_workspace_file(self.store, self.operation["operation_id"], "binary.txt", "a\\x00b", approved=True)

if __name__ == "__main__":
    unittest.main()
