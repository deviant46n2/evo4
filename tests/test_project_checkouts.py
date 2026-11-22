import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import (
    CheckoutInUseError,
    CheckoutNotFoundError,
    CheckoutPathConflictError,
    CheckoutPathError,
    ProjectArchivedError,
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectValidationError,
    archive_project,
    get_checkout,
    get_project,
    list_checkouts,
    list_projects,
    reactivate_project,
    refresh_checkout_availability,
    register_checkout,
    register_project,
    unregister_checkout,
    update_checkout,
    update_project,
)
from evo_core.store import EvoStore


def make_store(db_path):
    store = EvoStore(db_path)
    initialize_platform_registry(store)
    return store


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "proj.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_create_get_list(self):
        project = register_project(self.store, "Project", description="desc", project_type="software")
        self.assertEqual(project["status"], "active")
        self.assertEqual(project["version"], 1)
        fetched = get_project(self.store, project["project_id"])
        self.assertEqual(fetched["project_id"], project["project_id"])
        projects = list_projects(self.store)
        self.assertEqual(len(projects), 1)
        active = list_projects(self.store, status="active")
        self.assertEqual(len(active), 1)

    def test_invalid_name(self):
        with self.assertRaises(ProjectValidationError):
            register_project(self.store, "")
        with self.assertRaises(ProjectValidationError):
            register_project(self.store, 123)

    def test_metadata_update_and_stale_conflict(self):
        project = register_project(self.store, "Project")
        pid = project["project_id"]
        updated = update_project(self.store, pid, {"name": "Renamed", "description": "d"}, expected_version=1)
        self.assertEqual(updated["name"], "Renamed")
        self.assertEqual(updated["version"], 2)
        with self.assertRaises(ProjectConflictError):
            update_project(self.store, pid, {"name": "X"}, expected_version=1)
        with self.assertRaises(ProjectValidationError):
            update_project(self.store, pid, {}, expected_version=2)
        with self.assertRaises(ProjectValidationError):
            update_project(self.store, pid, {"unknown": "x"}, expected_version=2)

    def test_metadata_type_validation(self):
        project = register_project(self.store, "Project")
        pid = project["project_id"]
        with self.assertRaises(ProjectValidationError):
            update_project(self.store, pid, {"name": 123}, expected_version=1)
        with self.assertRaises(ProjectValidationError):
            update_project(self.store, pid, {"description": 123}, expected_version=1)

    def test_archive_reactivate(self):
        project = register_project(self.store, "Project")
        pid = project["project_id"]
        archived = archive_project(self.store, pid, expected_version=1)
        self.assertEqual(archived["status"], "archived")
        with self.assertRaises(ProjectArchivedError):
            register_checkout(self.store, pid, self.temp.name)
        reactivated = reactivate_project(self.store, pid, expected_version=2)
        self.assertEqual(reactivated["status"], "active")

    def test_stale_archive_conflict(self):
        project = register_project(self.store, "Project")
        pid = project["project_id"]
        with self.assertRaises(ProjectConflictError):
            archive_project(self.store, pid, expected_version=999)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "proj.sqlite3"
        self.store = make_store(self.db_path)
        self.project = register_project(self.store, "Project")
        self.pid = self.project["project_id"]
        self.checkout_dir = self.root / "checkout"
        self.checkout_dir.mkdir()
        (self.checkout_dir / "file.txt").write_text("data", encoding="utf-8")

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_register_and_get(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        self.assertEqual(checkout["availability_status"], "available")
        fetched = get_checkout(self.store, checkout["checkout_id"])
        self.assertEqual(fetched["canonical_path"], str(self.checkout_dir.resolve()))
        checkouts = list_checkouts(self.store, self.pid)
        self.assertEqual(len(checkouts), 1)

    def test_equivalent_paths_same_checkout(self):
        first = register_checkout(self.store, self.pid, self.checkout_dir)
        with self.assertRaises(CheckoutPathConflictError):
            register_checkout(self.store, self.pid, str(self.checkout_dir) + os.sep)
        self.assertEqual(first["canonical_path"], str(self.checkout_dir.resolve()))

    def test_symlink_alias_registers_canonical_target(self):
        link = self.root / "alias"
        try:
            link.symlink_to(self.checkout_dir, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks not supported")
        checkout = register_checkout(self.store, self.pid, link)
        self.assertEqual(checkout["canonical_path"], str(self.checkout_dir.resolve()))

    def test_broken_symlink_rejected(self):
        link = self.root / "broken"
        try:
            link.symlink_to(self.root / "missing", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks not supported")
        with self.assertRaises(CheckoutPathError):
            register_checkout(self.store, self.pid, link)

    def test_nonexistent_path_rejected(self):
        with self.assertRaises(CheckoutPathError):
            register_checkout(self.store, self.pid, self.root / "does-not-exist")

    def test_file_path_rejected(self):
        file_path = self.root / "file.txt"
        with self.assertRaises(CheckoutPathError):
            register_checkout(self.store, self.pid, file_path)

    def test_duplicate_canonical_path_rejected(self):
        register_checkout(self.store, self.pid, self.checkout_dir)
        other_project = register_project(self.store, "Other")
        with self.assertRaises(CheckoutPathConflictError):
            register_checkout(self.store, other_project["project_id"], self.checkout_dir)

    def test_register_archived_project_rejected(self):
        project = register_project(self.store, "ArchivedProject")
        archive_project(self.store, project["project_id"], expected_version=1)
        d = self.root / "another"
        d.mkdir()
        with self.assertRaises(ProjectArchivedError):
            register_checkout(self.store, project["project_id"], d)

    def test_update_checkout(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        updated = update_checkout(self.store, cid, {"branch_or_ref": "main", "last_known_commit": "abc"}, expected_version=1)
        self.assertEqual(updated["branch_or_ref"], "main")
        self.assertEqual(updated["last_known_commit"], "abc")
        self.assertEqual(updated["version"], 2)
        with self.assertRaises(ProjectConflictError):
            update_checkout(self.store, cid, {"branch_or_ref": "x"}, expected_version=1)

    def test_update_checkout_invalid_fields(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        with self.assertRaises(ProjectValidationError):
            update_checkout(self.store, cid, {"canonical_path": "/x"}, expected_version=1)
        with self.assertRaises(ProjectValidationError):
            update_checkout(self.store, cid, {}, expected_version=1)

    def test_refresh_availability_missing(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        self.checkout_dir.rmdir() if False else None
        # Simulate missing by renaming directory.
        moved = self.root / "moved"
        self.checkout_dir.rename(moved)
        refreshed = refresh_checkout_availability(self.store, cid)
        self.assertEqual(refreshed["availability_status"], "missing")
        # Restore for cleanup.
        moved.rename(self.checkout_dir)

    def test_refresh_availability_available(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        refreshed = refresh_checkout_availability(self.store, cid)
        self.assertEqual(refreshed["availability_status"], "available")

    def test_refresh_availability_unavailable_for_file(self):
        # Register a directory, then replace it with a file to make it unavailable.
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        for child in self.checkout_dir.iterdir():
            child.unlink()
        self.checkout_dir.rmdir()
        self.checkout_dir.write_text("not a dir")
        refreshed = refresh_checkout_availability(self.store, cid)
        self.assertEqual(refreshed["availability_status"], "unavailable")
        # Restore directory for cleanup.
        self.checkout_dir.unlink()
        self.checkout_dir.mkdir()
        (self.checkout_dir / "file.txt").write_text("data", encoding="utf-8")

    def test_unregister_checkout_removes_record_only(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        before_files = sorted(p.name for p in self.checkout_dir.iterdir())
        result = unregister_checkout(self.store, cid, expected_version=checkout["version"])
        self.assertTrue(result["unregistered"])
        with self.assertRaises(CheckoutNotFoundError):
            get_checkout(self.store, cid)
        after_files = sorted(p.name for p in self.checkout_dir.iterdir())
        self.assertEqual(before_files, after_files)

    def test_unregister_referenced_checkout_fails(self):
        checkout = register_checkout(self.store, self.pid, self.checkout_dir)
        cid = checkout["checkout_id"]
        # Seed a workspace reference directly.
        now = "2026-01-01T00:00:00Z"
        cfg_id = "cfg-ref"
        rev_id = "rev-ref"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cfg_id, "cfg", "active", rev_id, now, now),
                )
                self.store.db.execute(
                    "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (rev_id, cfg_id, 1, 1, "{}", "hash", now),
                )
                self.store.db.execute(
                    "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("ws-ref", "ws", self.pid, cid, cfg_id, rev_id, "active", now, now),
                )
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        with self.assertRaises(CheckoutInUseError):
            unregister_checkout(self.store, cid, expected_version=checkout["version"])
        # Record and directory remain.
        fetched = get_checkout(self.store, cid)
        self.assertEqual(fetched["checkout_id"], cid)
        self.assertTrue(self.checkout_dir.exists())


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "proj.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_foreign_key_project_checkout(self):
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(
                        "INSERT INTO project_checkouts(checkout_id,project_id,canonical_path,availability_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        ("chk-x", "missing-project", "/tmp/x", "available", now, now),
                    )
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()

    def test_unique_canonical_path(self):
        d1 = self.root / "d1"
        d2 = self.root / "d2"
        d1.mkdir()
        d2.mkdir()
        project = register_project(self.store, "Project")
        register_checkout(self.store, project["project_id"], d1)
        project2 = register_project(self.store, "Project2")
        with self.assertRaises(CheckoutPathConflictError):
            register_checkout(self.store, project2["project_id"], d1)


if __name__ == "__main__":
    unittest.main()
