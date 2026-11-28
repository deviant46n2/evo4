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
    get_task_workspace_operation,
)


DEFINITION = {"schema_version": 1, "components": {}}


SHIM = '#!/usr/bin/env python3\nimport os, sys, subprocess, time\nargs = sys.argv[1:]\nif "config" in args:\n    sys.exit(0)\nmode = os.environ.get("SHIM_MODE", "overflow")\nchild_pid_file = os.environ.get("SHIM_CHILD_PID_FILE")\nparent_pid_file = os.environ.get("SHIM_PARENT_PID_FILE")\npgid_file = os.environ.get("SHIM_PGID_FILE")\nready_file = os.environ.get("SHIM_READY_FILE")\nchild = subprocess.Popen(\n    [sys.executable, "-c", "import time; time.sleep(60)"],\n    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,\n)\nif parent_pid_file:\n    with open(parent_pid_file, "w") as handle:\n        handle.write(str(os.getpid()))\n        handle.flush()\n        os.fsync(handle.fileno())\nif child_pid_file:\n    with open(child_pid_file, "w") as handle:\n        handle.write(str(child.pid))\n        handle.flush()\n        os.fsync(handle.fileno())\nif pgid_file:\n    with open(pgid_file, "w") as handle:\n        handle.write(str(os.getpgrp()))\n        handle.flush()\n        os.fsync(handle.fileno())\nif ready_file:\n    with open(ready_file, "w") as handle:\n        handle.write("ready")\n        handle.flush()\n        os.fsync(handle.fileno())\nif mode == "overflow":\n    sys.stdout.write("a" * 60)\n    sys.stderr.write("b" * 60)\n    sys.stdout.flush()\n    sys.stderr.flush()\nelif mode == "exact":\n    count = int(os.environ.get("SHIM_BYTES", "100"))\n    sys.stdout.write("a" * count)\n    sys.stdout.flush()\n    time.sleep(0.2)\nelif mode == "timeout":\n    time.sleep(60)\nsys.exit(0)\n'

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

    def test_review_output_overflow_is_truncated(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(d), "config", "user.name", "T"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(d), "config", "user.email", "t@e.com"], check=True, capture_output=True)
        (d / "big.txt").write_text("x" * 100000)
        subprocess.run(["git", "-C", str(d), "add", "big.txt"], check=True, capture_output=True)
        from evo_core.task_workspaces import _git
        truncated = []
        out = _git(d, "diff", "--cached", max_output_bytes=100, truncated=truncated)
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), 100)




    def _pid_gone(self, pid):
        import os, time
        for _ in range(30):
            try:
                with open(f"/proc/{pid}/stat", "r") as handle:
                    stat = handle.read()
                if stat.split()[2] == "Z":
                    return True
            except FileNotFoundError:
                return True
            except OSError:
                pass
            time.sleep(0.1)
        try:
            with open(f"/proc/{pid}/stat", "r") as handle:
                stat = handle.read()
            return stat.split()[2] == "Z"
        except FileNotFoundError:
            return True
        except OSError:
            return False


    def test_review_subprocess_combined_output_overflow(self):
        import os, tempfile, time, threading
        from pathlib import Path
        from evo_core.task_workspaces import _git

        d = Path(tempfile.mkdtemp())
        shim = d / "git"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        child_pid_file = d / "child.pid"
        parent_pid_file = d / "parent.pid"
        pgid_file = d / "pgid"
        ready_file = d / "ready"
        env = {
            "PATH": str(d) + os.pathsep + os.environ.get("PATH", ""),
            "SHIM_MODE": "overflow",
            "SHIM_PGID_FILE": str(pgid_file),
            "SHIM_CHILD_PID_FILE": str(child_pid_file),
            "SHIM_PARENT_PID_FILE": str(parent_pid_file),
            "SHIM_PGID_FILE": str(pgid_file),
            "SHIM_READY_FILE": str(ready_file),
        }
        before_threads = set(threading.enumerate())
        truncated = []
        metrics = {}
        result_box = {}
        exc_box = {}
        def worker():
            try:
                result_box["out"] = _git(d, "status", max_output_bytes=100, truncated=truncated, timeout=5, env=env, metrics=metrics)
            except Exception as exc:
                exc_box["exc"] = exc
        t = threading.Thread(target=worker)
        t.start()
        for _ in range(50):
            if ready_file.exists():
                break
            time.sleep(0.1)
        self.assertTrue(ready_file.exists())
        t.join(timeout=10)
        self.assertFalse(t.is_alive(), "worker thread did not terminate")
        self.assertNotIn("exc", exc_box, f"unexpected worker exception: {exc_box.get('exc')}")
        out = result_box.get("out", "")
        self.assertTrue(truncated)
        self.assertLessEqual(metrics.get("captured_bytes", 0), 100)
        self.assertTrue(child_pid_file.exists())
        self.assertTrue(parent_pid_file.exists())
        self.assertTrue(pgid_file.exists())
        child_pid = int(child_pid_file.read_text())
        parent_pid = int(parent_pid_file.read_text())
        pgid = int(pgid_file.read_text())
        def _cleanup():
            for p in (pgid,):
                try:
                    os.killpg(p, 9)
                except (ProcessLookupError, OSError):
                    pass
        self.addCleanup(_cleanup)
        for _ in range(20):
            if self._pid_gone(child_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(child_pid))
        for _ in range(20):
            if self._pid_gone(parent_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(parent_pid))
        try:
            os.killpg(pgid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        except OSError:
            group_alive = False
        self.assertFalse(group_alive)
        after_threads = set(threading.enumerate())
        new_reader_threads = [th for th in after_threads if th not in before_threads and th.name.startswith("task-workspace-review-")]
        self.assertEqual(new_reader_threads, [])

    def test_review_subprocess_exact_fit_not_truncated(self):
        import os, tempfile, time, threading
        from pathlib import Path
        from evo_core.task_workspaces import _git

        d = Path(tempfile.mkdtemp())
        shim = d / "git"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        child_pid_file = d / "child.pid"
        parent_pid_file = d / "parent.pid"
        pgid_file = d / "pgid"
        ready_file = d / "ready"
        env = {
            "PATH": str(d) + os.pathsep + os.environ.get("PATH", ""),
            "SHIM_MODE": "exact",
            "SHIM_BYTES": "100",
            "SHIM_CHILD_PID_FILE": str(child_pid_file),
            "SHIM_PARENT_PID_FILE": str(parent_pid_file),
            "SHIM_PGID_FILE": str(pgid_file),
            "SHIM_READY_FILE": str(ready_file),
        }
        truncated = []
        metrics = {}
        result_box = {}
        exc_box = {}
        def worker():
            try:
                result_box["out"] = _git(d, "status", max_output_bytes=100, truncated=truncated, timeout=5, env=env, metrics=metrics)
            except Exception as exc:
                exc_box["exc"] = exc
        t = threading.Thread(target=worker)
        t.start()
        for _ in range(50):
            if ready_file.exists():
                break
            time.sleep(0.1)
        self.assertTrue(ready_file.exists())
        t.join(timeout=10)
        self.assertFalse(t.is_alive(), "worker thread did not terminate")
        self.assertNotIn("exc", exc_box, f"unexpected worker exception: {exc_box.get('exc')}")
        out = result_box.get("out", "")
        self.assertEqual(len(out), 100)
        self.assertFalse(truncated)
        self.assertEqual(metrics.get("captured_bytes"), 100)
        before_threads = set(threading.enumerate())
        after_threads = set(threading.enumerate())
        new_reader_threads = [t for t in after_threads if t not in before_threads and t.name.startswith("task-workspace-review-")]
        self.assertEqual(new_reader_threads, [])
        self.assertTrue(child_pid_file.exists())
        self.assertTrue(parent_pid_file.exists())
        self.assertTrue(pgid_file.exists())
        child_pid = int(child_pid_file.read_text())
        parent_pid = int(parent_pid_file.read_text())
        pgid = int(pgid_file.read_text())
        def _cleanup():
            try:
                os.killpg(pgid, 9)
            except (ProcessLookupError, OSError):
                pass
        self.addCleanup(_cleanup)
        for _ in range(20):
            if self._pid_gone(child_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(child_pid))
        for _ in range(20):
            if self._pid_gone(parent_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(parent_pid))
        try:
            os.killpg(pgid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        except OSError:
            group_alive = False
        self.assertFalse(group_alive)

    def test_review_subprocess_timeout_terminates(self):
        import os, tempfile, time, threading
        from pathlib import Path
        from evo_core.task_workspaces import _git, TaskWorkspaceProvisioningError

        d = Path(tempfile.mkdtemp())
        shim = d / "git"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        child_pid_file = d / "child.pid"
        parent_pid_file = d / "parent.pid"
        pgid_file = d / "pgid"
        ready_file = d / "ready"
        env = {
            "PATH": str(d) + os.pathsep + os.environ.get("PATH", ""),
            "SHIM_MODE": "timeout",
            "SHIM_CHILD_PID_FILE": str(child_pid_file),
            "SHIM_PARENT_PID_FILE": str(parent_pid_file),
            "SHIM_PGID_FILE": str(pgid_file),
            "SHIM_READY_FILE": str(ready_file),
        }
        before_threads = set(threading.enumerate())
        truncated = []
        result_box = {}
        exc_box = {}
        def worker():
            try:
                result_box["out"] = _git(d, "status", timeout=0.1, max_output_bytes=1000, truncated=truncated, env=env)
            except Exception as exc:
                exc_box["exc"] = exc
        t = threading.Thread(target=worker)
        t.start()
        for _ in range(50):
            if ready_file.exists():
                break
            time.sleep(0.1)
        self.assertTrue(ready_file.exists())
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "worker thread did not terminate")
        self.assertIsInstance(exc_box.get("exc"), TaskWorkspaceProvisioningError)
        self.assertTrue(child_pid_file.exists())
        self.assertTrue(parent_pid_file.exists())
        self.assertTrue(pgid_file.exists())
        child_pid = int(child_pid_file.read_text())
        parent_pid = int(parent_pid_file.read_text())
        pgid = int(pgid_file.read_text())
        def _cleanup():
            try:
                os.killpg(pgid, 9)
            except (ProcessLookupError, OSError):
                pass
        self.addCleanup(_cleanup)
        for _ in range(20):
            if self._pid_gone(child_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(child_pid))
        for _ in range(20):
            if self._pid_gone(parent_pid):
                break
            time.sleep(0.1)
        self.assertTrue(self._pid_gone(parent_pid))
        try:
            os.killpg(pgid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        except OSError:
            group_alive = False
        self.assertFalse(group_alive)
        after_threads = set(threading.enumerate())
        new_reader_threads = [t for t in after_threads if t not in before_threads and t.name.startswith("task-workspace-review-")]
        self.assertEqual(new_reader_threads, [])

    def test_normal_git_command_does_not_invoke_group_cleanup(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from evo_core.task_workspaces import _git
        d = Path(tempfile.mkdtemp())
        subprocess.run(["git", "-C", str(d), "init", "--initial-branch=main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(d), "config", "user.name", "T"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(d), "config", "user.email", "t@e.com"], check=True, capture_output=True)
        (d / "f.txt").write_text("hello")
        subprocess.run(["git", "-C", str(d), "add", "f.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(d), "commit", "-m", "i"], check=True, capture_output=True)
        truncated = []
        metrics = {}
        with patch("evo_core.task_workspaces._cleanup_process_group") as cleanup:
            out = _git(d, "show", "HEAD:f.txt", max_output_bytes=1000, truncated=truncated, metrics=metrics)
        cleanup.assert_not_called()
        self.assertFalse(truncated)
        self.assertEqual(out, "hello")

if __name__ == "__main__":
    unittest.main()
