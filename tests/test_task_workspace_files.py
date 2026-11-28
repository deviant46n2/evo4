import subprocess
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.task_workspaces import (
    create_task_workspace, _record, get_task_workspace_operation,
    get_task_workspace_review,
)
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

    def test_directory_scan_budget_bounds_work_and_marks_total_inexact(self):
        from unittest.mock import patch

        for name in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"):
            (self.task_root / name).write_text(name)
        with patch("evo_core.task_workspace_files.MAX_DIRECTORY_SCAN_ENTRIES", 3):
            result = list_task_workspace_files(
                self.store, self.operation["operation_id"], limit=2,
            )
        self.assertEqual(result["scan_limit"], 3)
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["total_exact"])
        self.assertTrue(result["scan_truncated"])
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["items"]), 2)

    def test_directory_scan_reports_exact_total_when_under_budget(self):
        (self.task_root / "one.txt").write_text("one")
        result = list_task_workspace_files(self.store, self.operation["operation_id"])
        self.assertTrue(result["total_exact"])
        self.assertFalse(result["scan_truncated"])

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

    def test_coding_agent_task_workspace_writes_use_approval_journal(self):
        from evo_core.coding_agent import CodingAgent

        assistant = type("Assistant", (), {"store": self.store})()
        agent = CodingAgent(
            assistant, self.task_root,
            task_workspace_operation_id=self.operation["operation_id"],
        )
        created = agent._execute("write_file", {
            "path": "agent-created.py", "content": "print('created')\n",
        })
        self.assertEqual(created["written"], "agent-created.py")
        self.assertEqual(created["file_change"]["status"], "applied")

        (self.task_root / "existing.py").write_text("old\n", encoding="utf-8")
        replaced = agent._execute("write_file", {
            "path": "existing.py", "content": "new\n", "overwrite": True,
        })
        self.assertEqual(replaced["written"], "existing.py")
        self.assertIsNotNone(replaced["file_change"]["before_sha256"])
        self.assertEqual((self.task_root / "existing.py").read_text(), "new\n")

        test_approval = agent.workspace.approve_test_write("test_guard.py")
        guarded = agent._execute(
            "write_file", {"path": "test_guard.py", "content": "assert True\n"},
            test_approval=test_approval,
        )
        self.assertEqual(guarded["file_change"]["status"], "applied")
        history = list_task_workspace_file_changes(self.store, self.operation["operation_id"])
        self.assertEqual(history["total"], 3)
        self.assertEqual({item["path"] for item in history["items"]},
                         {"agent-created.py", "existing.py", "test_guard.py"})

    def test_approved_overwrite_without_stale_editor_hash_records_before_and_after(self):
        target = self.task_root / "README.txt"
        before = target.read_bytes()
        result = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "README.txt",
            "agent approved replacement\n", overwrite=True, approved=True,
        )
        self.assertEqual(target.read_text(), "agent approved replacement\n")
        self.assertEqual(result["before_sha256"], __import__("hashlib").sha256(before).hexdigest())
        history = list_task_workspace_file_changes(self.store, self.operation["operation_id"])
        self.assertEqual(history["items"][0]["change_id"], result["change_id"])
        self.assertEqual(history["items"][0]["status"], "applied")

    def test_existing_file_still_requires_overwrite_or_expected_hash(self):
        with self.assertRaises(ValueError):
            apply_task_workspace_file(
                self.store, self.operation["operation_id"], "README.txt",
                "must not replace", approved=True,
            )
        self.assertEqual((self.task_root / "README.txt").read_text(), "baseline\n")

    def test_change_history_is_bounded_and_reports_total(self):
        first = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "first.txt",
            "one", approved=True,
        )
        second = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "second.txt",
            "two", approved=True,
        )
        result = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"], limit=1,
        )
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["change_id"], second["change_id"])
        complete = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"], limit=2,
        )
        self.assertEqual(complete["total"], 2)
        self.assertFalse(complete["truncated"])
        self.assertEqual(
            {item["change_id"] for item in complete["items"]},
            {first["change_id"], second["change_id"]},
        )

    def test_post_mutation_failure_remains_pending_for_recovery(self):
        import os
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        real_unlink = os.unlink
        calls = {"count": 0}

        def fail_first_unlink(path, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("simulated cleanup failure after link")
            return real_unlink(path, *args, **kwargs)

        with patch("evo_core.task_workspace_files.os.unlink", side_effect=fail_first_unlink):
            with self.assertRaises(ValueError):
                apply_task_workspace_file(
                    self.store, self.operation["operation_id"], "post-mutation.txt",
                    "persisted", approved=True,
                )
        target = self.task_root / "post-mutation.txt"
        self.assertEqual(target.read_text(), "persisted")
        with self.store.lock:
            self.store.db.execute(
                "UPDATE task_workspace_file_changes SET created_at=? WHERE path=?",
                ((datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),
                 "post-mutation.txt"),
            )
            self.store.db.commit()
        history = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"],
        )
        item = next(row for row in history["items"] if row["path"] == "post-mutation.txt")
        self.assertEqual(item["status"], "applied")

    def test_post_replace_fsync_failure_is_reconciled_as_applied(self):
        import hashlib
        import os
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        target = self.task_root / "README.txt"
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        real_fsync = os.fsync
        calls = {"count": 0}

        def fail_directory_fsync(fd):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated directory fsync failure after replace")
            return real_fsync(fd)

        with patch("evo_core.task_workspace_files.os.fsync", side_effect=fail_directory_fsync):
            with self.assertRaises(ValueError):
                apply_task_workspace_file(
                    self.store, self.operation["operation_id"], "README.txt",
                    "replacement persisted", expected_sha256=expected, approved=True,
                )
        self.assertEqual(target.read_text(), "replacement persisted")
        with self.store.lock:
            self.store.db.execute(
                "UPDATE task_workspace_file_changes SET created_at=? WHERE path=?",
                ((datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),
                 "README.txt"),
            )
            self.store.db.commit()
        history = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"],
        )
        item = next(row for row in history["items"] if row["path"] == "README.txt")
        self.assertEqual(item["status"], "applied")

    def test_recent_pending_write_is_not_reconciled_while_active(self):
        result = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "active.txt",
            "active", approved=True,
        )
        with self.store.lock:
            self.store.db.execute(
                "UPDATE task_workspace_file_changes SET status='pending' WHERE change_id=?",
                (result["change_id"],),
            )
            self.store.db.commit()
        recent = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"],
        )
        self.assertEqual(recent["items"][0]["status"], "pending")

    def test_legacy_change_history_schema_is_migrated(self):
        with self.store.lock:
            self.store.db.execute(
                """CREATE TABLE task_workspace_file_changes (
                    change_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL REFERENCES task_workspaces(operation_id)
                        ON DELETE RESTRICT,
                    path TEXT NOT NULL,
                    before_sha256 TEXT,
                    after_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            self.store.db.commit()
        result = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "migrated.txt",
            "migration", approved=True,
        )
        history = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"],
        )
        self.assertEqual(history["items"][0]["change_id"], result["change_id"])
        self.assertEqual(history["items"][0]["status"], "applied")
        self.assertIn("error_code", history["items"][0])
        self.assertIn("finalized_at", history["items"][0])

    def test_filesystem_failure_is_recorded_as_failed_attempt(self):
        from unittest.mock import patch

        with patch("evo_core.task_workspace_files.os.link", side_effect=FileExistsError):
            with self.assertRaises(ValueError):
                apply_task_workspace_file(
                    self.store, self.operation["operation_id"], "raced.txt",
                    "content", approved=True,
                )
        history = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"],
        )
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["path"], "raced.txt")
        self.assertEqual(history["items"][0]["status"], "failed")
        self.assertEqual(history["items"][0]["error_code"], "filesystem_error")

    def test_interrupted_file_change_journal_is_reconciled(self):
        import hashlib
        import uuid
        from datetime import datetime, timedelta, timezone

        stale_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=2)
        ).isoformat()
        applied = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "reconcile.txt",
            "current", approved=True,
        )
        with self.store.lock:
            self.store.db.execute(
                "UPDATE task_workspace_file_changes SET status='pending', created_at=? WHERE change_id=?",
                (stale_timestamp, applied["change_id"]),
            )
            failed_id = str(uuid.uuid4())
            self.store.db.execute(
                """INSERT INTO task_workspace_file_changes
                   (change_id, operation_id, path, before_sha256, after_sha256,
                    size_bytes, created_at, status)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, 'pending')""",
                (failed_id, self.operation["operation_id"], "not-created.txt",
                 hashlib.sha256(b"future").hexdigest(), 6, stale_timestamp),
            )
            uncertain_id = str(uuid.uuid4())
            self.store.db.execute(
                """INSERT INTO task_workspace_file_changes
                   (change_id, operation_id, path, before_sha256, after_sha256,
                    size_bytes, created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (uncertain_id, self.operation["operation_id"], "reconcile.txt",
                 hashlib.sha256(b"old").hexdigest(), hashlib.sha256(b"new").hexdigest(),
                 3, stale_timestamp),
            )
            self.store.db.commit()

        history = list_task_workspace_file_changes(
            self.store, self.operation["operation_id"], limit=10,
        )
        statuses = {item["change_id"]: item for item in history["items"]}
        self.assertEqual(statuses[applied["change_id"]]["status"], "applied")
        self.assertEqual(statuses[failed_id]["status"], "failed")
        self.assertEqual(statuses[uncertain_id]["status"], "indeterminate")
        self.assertEqual(
            statuses[failed_id]["error_code"], "interrupted_before_create",
        )

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
        self.assertEqual((self.source / "README.txt").read_text(), "baseline\n")
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
            apply_task_workspace_file(self.store, self.operation["operation_id"], "binary.txt", "a\x00b", approved=True)


    def test_apply_rejects_dot_empty_and_repeated_path_segments(self):
        for path in (".", "src/./new.py", "src//new.py", "src/../new.py", "/absolute.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                apply_task_workspace_file(
                    self.store, self.operation["operation_id"], path,
                    "unsafe", approved=True,
                )


    def test_approved_apply_can_create_empty_file_for_editor(self):
        result = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "new-module.py",
            "", approved=True,
        )
        self.assertEqual((self.task_root / "new-module.py").read_bytes(), b"")
        opened = read_task_workspace_file(
            self.store, self.operation["operation_id"], "new-module.py",
        )
        self.assertEqual(opened["content"], "")
        self.assertEqual(opened["sha256"], result["after_sha256"])

    def test_review_artifact_includes_bounded_approved_file_change_history(self):
        applied = apply_task_workspace_file(
            self.store, self.operation["operation_id"], "reviewed.py",
            "print('reviewed')\\n", approved=True,
        )

        review = get_task_workspace_review(self.store, self.operation["operation_id"])

        self.assertEqual(review["file_change_summary"], {
            "total": 1,
            "applied": 1,
            "pending": 0,
            "failed": 0,
            "indeterminate": 0,
            "truncated": False,
            "limit": 500,
        })
        self.assertEqual(len(review["file_change_history"]), 1)
        change = review["file_change_history"][0]
        self.assertEqual(change["change_id"], applied["change_id"])
        self.assertEqual(change["operation_id"], self.operation["operation_id"])
        self.assertEqual(change["path"], "reviewed.py")
        self.assertIsNone(change["before_sha256"])
        self.assertEqual(change["after_sha256"], applied["after_sha256"])
        self.assertEqual(change["status"], "applied")
        self.assertIn({"status": "A", "path": "reviewed.py"}, review["changed_files"])


if __name__ == "__main__":
    unittest.main()
