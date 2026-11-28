import subprocess
import threading
import time
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace
from evo_core.task_workspaces import (
    TaskWorkspaceConflictError,
    TaskWorkspaceValidationError,
    create_task_workspace,
    get_task_workspace_for_task,
    get_task_workspace_review,
    _git,
    get_task_workspace_review,
    get_task_workspace_operation,
)


DEFINITION = {"schema_version": 1, "components": {}}


class TaskWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "evo.sqlite3")
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.source = self.root / "source"
        self.source.mkdir()
        self._git(self.source, "init", "--initial-branch=main")
        self._git(self.source, "config", "user.name", "Test")
        self._git(self.source, "config", "user.email", "test@example.invalid")
        (self.source / "tracked.txt").write_text("original\n", encoding="utf-8")
        self._git(self.source, "add", "tracked.txt")
        self._git(self.source, "commit", "-m", "initial")
        self.revision = self._git(self.source, "rev-parse", "HEAD")
        self.checkout = register_checkout(
            self.store, self.project["project_id"], self.source,
            branch_or_ref="main", last_known_commit=self.revision,
        )
        config = create_configuration(self.store, DEFINITION, name="config")
        self.workspace = create_workspace(
            self.store, "Parent", self.project["project_id"],
            config["configuration"]["configuration_id"],
            config["revision"]["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )
        self.destinations = self.root / "task-worktrees"
        self.destinations.mkdir()

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    @staticmethod
    def _git(path, *args):
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def test_creates_detached_revision_pinned_workspace_and_preserves_source(self):
        before = self._git(self.source, "status", "--porcelain")
        result = create_task_workspace(
            self.store, self.workspace["workspace_id"], "task-123", self.destinations
        )
        task_path = Path(result["canonical_path"])
        self.assertEqual(result["source_revision"], self.revision)
        self.assertEqual(self._git(task_path, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(self._git(task_path, "status", "--porcelain"), "")
        self.assertEqual(self._git(task_path, "branch", "--show-current"), "")
        self.assertEqual(self._git(self.source, "status", "--porcelain"), before)
        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(result["workspace"]["configuration_revision_id"],
                         self.workspace["configuration_revision_id"])
        self.assertEqual(result["checkout"]["last_known_commit"], self.revision)
        operation = get_task_workspace_operation(self.store, result["operation_id"])
        self.assertEqual(operation["status"], "completed")
        self.assertEqual(operation["task_workspace_id"], result["workspace"]["workspace_id"])
        self.assertEqual(
            get_task_workspace_for_task(self.store, self.project["project_id"], "task-123")["operation_id"],
            result["operation_id"],
        )



    def test_inherited_git_repository_overrides_are_ignored(self):
        import os
        previous = os.environ.get("GIT_DIR")
        os.environ["GIT_DIR"] = str(self.root / "not-the-source")
        try:
            result = create_task_workspace(
                self.store, self.workspace["workspace_id"], "git-env-test", self.destinations
            )
        finally:
            if previous is None:
                os.environ.pop("GIT_DIR", None)
            else:
                os.environ["GIT_DIR"] = previous
        self.assertEqual(
            self._git(Path(result["canonical_path"]), "rev-parse", "HEAD"),
            self.revision,
        )

    def test_repository_post_checkout_hook_is_not_executed(self):
        marker = self.root / "hook-ran"
        hook = self.source / ".git" / "hooks" / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        hook.chmod(0o755)
        create_task_workspace(
            self.store, self.workspace["workspace_id"], "hook-test", self.destinations
        )
        self.assertFalse(marker.exists())

    def test_dirty_source_is_rejected_without_creating_worktree(self):
        (self.source / "tracked.txt").write_text("modified\n", encoding="utf-8")
        with self.assertRaises(TaskWorkspaceConflictError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "dirty-task", self.destinations
            )
        self.assertEqual(list(self.destinations.iterdir()), [])

    def test_untracked_source_is_rejected(self):
        (self.source / "untracked.txt").write_text("not committed", encoding="utf-8")
        with self.assertRaises(TaskWorkspaceConflictError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "untracked-task", self.destinations
            )

    def test_noncanonical_or_unknown_revision_is_rejected(self):
        with self.assertRaises(TaskWorkspaceValidationError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "bad-rev", self.destinations,
                source_revision="HEAD",
            )
        with self.assertRaises(Exception):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "missing-rev", self.destinations,
                source_revision="f" * 40,
            )


    def test_uppercase_full_commit_id_is_accepted(self):
        result = create_task_workspace(
            self.store, self.workspace["workspace_id"], "uppercase-revision",
            self.destinations, source_revision=self.revision.upper(),
        )
        self.assertEqual(result["source_revision"], self.revision)

    def test_duplicate_task_in_same_project_is_rejected(self):
        create_task_workspace(
            self.store, self.workspace["workspace_id"], "same-task", self.destinations
        )
        with self.assertRaises(TaskWorkspaceConflictError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "same-task", self.destinations
            )

    def test_parent_directory_inside_source_checkout_is_rejected_by_overlap(self):
        with self.assertRaises(TaskWorkspaceConflictError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "nested", self.source
            )


    def test_intermediate_symlink_in_destination_parent_is_rejected(self):
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        link_parent = self.root / "linked-parent"
        link_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(TaskWorkspaceValidationError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "symlink-parent",
                link_parent,
            )

    def test_invalid_destination_parent_and_task_id(self):
        with self.assertRaises(TaskWorkspaceValidationError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], "bad", self.root / "missing"
            )
        with self.assertRaises(TaskWorkspaceValidationError):
            create_task_workspace(
                self.store, self.workspace["workspace_id"], " ", self.destinations
            )



    def test_review_reports_tracked_and_untracked(self):
        result = create_task_workspace(
            self.store, self.workspace["workspace_id"], "task-review", self.destinations
        )
        task_path = Path(result["canonical_path"])
        (task_path / "tracked.txt").write_text("changed\n")
        (task_path / "new.txt").write_text("new file\n")
        review = get_task_workspace_review(self.store, result["operation_id"])
        self.assertEqual(review["status"], "ok")
        self.assertTrue(review["stable"])
        paths = {item["path"] for item in review["changed_files"]}
        self.assertIn("tracked.txt", paths)
        self.assertIn("new.txt", paths)
        self.assertIn("tracked.txt", review["patch"])
        self.assertIn("new.txt", review["patch"])

    def test_review_excludes_sensitive_and_reports_unreadable(self):
        result = create_task_workspace(
            self.store, self.workspace["workspace_id"], "task-review-2", self.destinations
        )
        task_path = Path(result["canonical_path"])
        (task_path / ".env").write_text("secret")
        (task_path / "binary.dat").write_bytes(b"\x00\x01")
        review = get_task_workspace_review(self.store, result["operation_id"])
        self.assertIn(".env", review["excluded_files"])
        reasons = {item["reason"] for item in review["unreadable_files"]}
        self.assertIn("binary", reasons)

    def test_review_rejects_incomplete_operation(self):
        with self.assertRaises(Exception):
            get_task_workspace_review(self.store, "missing-operation")


    def test_review_large_untracked_is_truncated_and_unstable(self):
        result = create_task_workspace(
            self.store, self.workspace["workspace_id"], "task-large", self.destinations
        )
        task_path = Path(result["canonical_path"])
        (task_path / "big.txt").write_text("x" * 10000)
        review = get_task_workspace_review(self.store, result["operation_id"], max_bytes=1024)
        self.assertTrue(review["truncated"])
        self.assertFalse(review["stable"])
        self.assertEqual(review["truncation_reason"], "output_limit")

    def test_git_combined_output_budget(self):
        import io
        from unittest.mock import patch

        class FakeProc:
            def __init__(self, stdout_text, stderr_text):
                self.stdout = io.StringIO(stdout_text)
                self.stderr = io.StringIO(stderr_text)
                self.pid = 999999
                self.returncode = 0
                self._killed = False
                self.args = ["git"]

            def kill(self):
                self._killed = True

            def wait(self, timeout=None):
                return 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def communicate(self, input=None, timeout=None):
                return self.stdout.read(), self.stderr.read()

            def poll(self):
                return 0

        # Combined output exceeds a 100-byte budget.
        big_out = "a" * 60
        big_err = "b" * 60
        calls = {"n": 0}
        def factory(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeProc("", "")
            return FakeProc(big_out, big_err)
        with patch("evo_core.task_workspaces.subprocess.Popen", side_effect=factory):
            truncated = []
            try:
                _git(Path("/tmp"), "status", max_output_bytes=100, truncated=truncated)
            except Exception:
                pass
            self.assertTrue(truncated)

        # Exact fit does not mark truncated.
        exact_out = "a" * 50
        exact_err = "b" * 50
        calls2 = {"n": 0}
        def factory2(*a, **k):
            calls2["n"] += 1
            if calls2["n"] == 1:
                return FakeProc("", "")
            return FakeProc(exact_out, exact_err)
        with patch("evo_core.task_workspaces.subprocess.Popen", side_effect=factory2):
            truncated2 = []
            _git(Path("/tmp"), "status", max_output_bytes=100, truncated=truncated2)
            self.assertFalse(truncated2)

    def test_git_output_limit_terminates_process(self):
        import tempfile, time
        d = Path(tempfile.mkdtemp())
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        big = d / "big.txt"
        big.write_text("x" * 100000)
        subprocess.run(["git", "-C", str(d), "add", "big.txt"], check=True, capture_output=True)
        truncated = []
        start = time.monotonic()
        try:
            _git(d, "diff", "--cached", max_output_bytes=100, truncated=truncated)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 5)
        self.assertTrue(truncated)

    def test_git_timeout_terminates(self):
        import io
        from unittest.mock import patch

        class BlockingProc:
            def __init__(self):
                self.stdout = io.StringIO("")
                self.stderr = io.StringIO("")
                self.pid = 999999
                self.returncode = None
                self._killed = False

            def kill(self):
                self._killed = True

            def wait(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired(cmd="git", timeout=timeout)
                return 0

        with patch("evo_core.task_workspaces.subprocess.Popen", return_value=BlockingProc()):
            truncated = []
            start = __import__("time").monotonic()
            with self.assertRaises(Exception):
                _git(Path("/tmp"), "status", timeout=0.01, max_output_bytes=1000, truncated=truncated)
            elapsed = __import__("time").monotonic() - start
            self.assertLess(elapsed, 5)

if __name__ == "__main__":
    unittest.main()
