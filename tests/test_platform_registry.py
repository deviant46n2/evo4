import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from evo_core.store import EvoStore
from evo_core.platform_registry import (
    MIGRATION_NAME,
    PLATFORM_REGISTRY_DDL,
    initialize_platform_registry,
)
from evo_experiments.db import ResultsDB


REGISTRY_TABLES = {
    "ai_configurations",
    "ai_configuration_revisions",
    "software_projects",
    "project_checkouts",
    "workspaces",
}
REGISTRY_INDEXES = {
    "idx_ai_configurations_status",
    "idx_ai_configuration_revisions_configuration",
    "idx_software_projects_status",
    "idx_project_checkouts_project",
    "idx_workspaces_project",
    "idx_workspaces_configuration",
}
REGISTRY_TRIGGERS = {
    "ai_configuration_revisions_no_update",
    "ai_configuration_revisions_no_delete",
}


def make_store(db_path):
    return EvoStore(db_path)


def seed_existing_data(store, lab_db):
    now = "2026-01-01T00:00:00Z"
    with store.lock:
        store.db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?)",
            ("conv-1", "title", now, now, "{}"),
        )
        store.db.execute(
            "INSERT INTO messages(conversation_id,role,content,created_at,metadata_json) VALUES(?,?,?,?,?)",
            ("conv-1", "user", "hello", now, "{}"),
        )
        store.db.execute(
            "INSERT INTO memories(id,content,category,tags_json,source,confidence,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("mem-1", "content", "general", "[]", "user", 1.0, "active", now, now),
        )
        store.db.execute(
            "INSERT INTO memories(id,content,category,tags_json,source,confidence,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("mem-2", "content2", "general", "[]", "user", 1.0, "active", now, now),
        )
        store.db.execute(
            "INSERT INTO memory_relations(id,source_memory_id,target_memory_id,relation_type,evidence,created_at) VALUES(?,?,?,?,?,?)",
            ("rel-1", "mem-1", "mem-2", "supports", "", now),
        )
        store.db.commit()
    lab_db.create_experiment(
        {
            "task_id": "task-1",
            "category": "cat",
            "repetition": 1,
            "model": "model",
            "base_url": "http://localhost",
            "config_json": "{}",
            "prompt": "prompt",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
        }
    )


class PlatformRegistrySchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "registry.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_schema_objects_and_fk(self):
        initialize_platform_registry(self.store)
        tables = {
            r[0]
            for r in self.store.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertTrue(REGISTRY_TABLES.issubset(tables))
        indexes = {
            r[0]
            for r in self.store.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        self.assertTrue(REGISTRY_INDEXES.issubset(indexes))
        triggers = {
            r[0]
            for r in self.store.db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        self.assertTrue(REGISTRY_TRIGGERS.issubset(triggers))
        self.assertEqual(self.store.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_immutable_revision_triggers(self):
        initialize_platform_registry(self.store)
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                cfg = "cfg-1"
                rev = "rev-1"
                now = "2026-01-01T00:00:00Z"
                self.store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cfg, "cfg", "active", rev, now, now),
                )
                self.store.db.execute(
                    "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (rev, cfg, 1, 1, "{}", "hash", now),
                )
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "UPDATE ai_configuration_revisions SET change_summary='x' WHERE revision_id=?",
                        (rev,),
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "DELETE FROM ai_configuration_revisions WHERE revision_id=?", (rev,)
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise

    def test_configuration_first_insertion_succeeds(self):
        initialize_platform_registry(self.store)
        cfg = "cfg-2"
        rev = "rev-2"
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cfg, "cfg", "active", rev, now, now),
                )
                self.store.db.execute(
                    "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (rev, cfg, 1, 1, "{}", "hash", now),
                )
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM ai_configurations WHERE configuration_id=?", (cfg,)
            ).fetchone()[0],
            1,
        )

    def test_revision_first_insertion_fails(self):
        initialize_platform_registry(self.store)
        cfg = "cfg-3"
        rev = "rev-3"
        now = "2026-01-01T00:00:00Z"
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                        (rev, cfg, 1, 1, "{}", "hash", now),
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise

    def test_configuration_without_current_revision_fails(self):
        initialize_platform_registry(self.store)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("cfg-4", "cfg", "active", "missing-rev", now, now),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()

    def test_cross_configuration_revision_fails(self):
        initialize_platform_registry(self.store)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                for cfg, rev in (("cfg-a", "rev-a"), ("cfg-b", "rev-b")):
                    self.store.db.execute(
                        "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (cfg, cfg, "active", rev, now, now),
                    )
                    self.store.db.execute(
                        "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                        (rev, cfg, 1, 1, "{}", "hash", now),
                    )
                self.store.db.execute(
                    "INSERT INTO software_projects(project_id,name,created_at,updated_at,status) VALUES(?,?,?,?,?)",
                    ("proj-1", "proj", now, now, "active"),
                )
                self.store.db.execute(
                    "INSERT INTO project_checkouts(checkout_id,project_id,canonical_path,availability_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("chk-1", "proj-1", "/tmp/chk", "available", now, now),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(
                        "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        ("ws-1", "ws", "proj-1", "chk-1", "cfg-a", "rev-b", "active", now, now),
                    )
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()

    def test_cross_project_checkout_fails(self):
        initialize_platform_registry(self.store)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO software_projects(project_id,name,created_at,updated_at,status) VALUES(?,?,?,?,?)",
                    ("proj-a", "a", now, now, "active"),
                )
                self.store.db.execute(
                    "INSERT INTO software_projects(project_id,name,created_at,updated_at,status) VALUES(?,?,?,?,?)",
                    ("proj-b", "b", now, now, "active"),
                )
                self.store.db.execute(
                    "INSERT INTO project_checkouts(checkout_id,project_id,canonical_path,availability_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("chk-a", "proj-a", "/tmp/chka", "available", now, now),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.db.execute(
                        "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        ("ws-x", "ws", "proj-b", "chk-a", "cfg-x", "rev-x", "active", now, now),
                    )
                    self.store.db.commit()
            finally:
                if self.store.db.in_transaction:
                    self.store.db.rollback()

    def test_shared_checkout_permitted(self):
        initialize_platform_registry(self.store)
        now = "2026-01-01T00:00:00Z"
        cfg = "cfg-s"
        rev = "rev-s"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cfg, "cfg", "active", rev, now, now),
                )
                self.store.db.execute(
                    "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (rev, cfg, 1, 1, "{}", "hash", now),
                )
                self.store.db.execute(
                    "INSERT INTO software_projects(project_id,name,created_at,updated_at,status) VALUES(?,?,?,?,?)",
                    ("proj-s", "proj", now, now, "active"),
                )
                self.store.db.execute(
                    "INSERT INTO project_checkouts(checkout_id,project_id,canonical_path,availability_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("chk-s", "proj-s", "/tmp/chks", "available", now, now),
                )
                for i in range(2):
                    self.store.db.execute(
                        "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (f"ws-s{i}", "ws", "proj-s", "chk-s", cfg, rev, "active", now, now),
                    )
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        count = self.store.db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        self.assertEqual(count, 2)

    def test_restrictive_deletion(self):
        initialize_platform_registry(self.store)
        now = "2026-01-01T00:00:00Z"
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                self.store.db.execute(
                    "INSERT INTO software_projects(project_id,name,created_at,updated_at,status) VALUES(?,?,?,?,?)",
                    ("proj-r", "proj", now, now, "active"),
                )
                self.store.db.execute(
                    "INSERT INTO project_checkouts(checkout_id,project_id,canonical_path,availability_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("chk-r", "proj-r", "/tmp/chkr", "available", now, now),
                )
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "DELETE FROM software_projects WHERE project_id=?", ("proj-r",)
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise


class PlatformRegistryIdempotenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "registry.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_repeated_initialization(self):
        first = initialize_platform_registry(self.store)
        second = initialize_platform_registry(self.store)
        self.assertIn(first, ("initialized", "already-initialized"))
        self.assertEqual(second, "already-initialized")
        count = self.store.db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name=?", ("platform_registry_v1",)
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_connection_and_lock_preserved(self):
        db_before = self.store.db
        lock_before = self.store.lock
        initialize_platform_registry(self.store)
        self.assertIs(self.store.db, db_before)
        self.assertIs(self.store.lock, lock_before)


class PlatformRegistryRealisticMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "evo.sqlite3"
        self.store = make_store(self.db_path)
        self.lab_db = ResultsDB(self.db_path)
        seed_existing_data(self.store, self.lab_db)
        self.store.db.close()
        self.lab_db.connection.close()
        self.backup_path = self.root / "backup.sqlite3"
        shutil.copyfile(self.db_path, self.backup_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_data_preserved(self):
        copied = self.root / "copied.sqlite3"
        shutil.copyfile(self.backup_path, copied)
        store = make_store(copied)
        lab_db = ResultsDB(copied)
        try:
            result = initialize_platform_registry(store)
            self.assertIn(result, ("initialized", "already-initialized"))
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1
            )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
            )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 2
            )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM memory_relations").fetchone()[0], 1
            )
            self.assertEqual(
                lab_db.connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0], 1
            )
            tables = {
                r[0]
                for r in store.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue(REGISTRY_TABLES.issubset(tables))
            marker_count = store.db.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE name=?", ("platform_registry_v1",)
            ).fetchone()[0]
            self.assertEqual(marker_count, 1)
        finally:
            store.db.close()
            lab_db.connection.close()


class PlatformRegistryConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "concurrent.sqlite3"
        # Create base schema first.
        bootstrap = make_store(self.db_path)
        bootstrap.db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_initialization(self):
        store_a = make_store(self.db_path)
        store_b = make_store(self.db_path)
        barrier = threading.Barrier(2)
        results = {}

        def worker(name, store):
            barrier.wait()
            results[name] = initialize_platform_registry(store)

        t1 = threading.Thread(target=worker, args=("a", store_a))
        t2 = threading.Thread(target=worker, args=("b", store_b))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertIn(results["a"], ("initialized", "already-initialized"))
        self.assertIn(results["b"], ("initialized", "already-initialized"))
        marker_count = store_a.db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name=?", ("platform_registry_v1",)
        ).fetchone()[0]
        self.assertEqual(marker_count, 1)
        tables = {
            r[0]
            for r in store_a.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertTrue(REGISTRY_TABLES.issubset(tables))
        store_a.db.close()
        store_b.db.close()


class PlatformRegistryForeignKeyFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "fk.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_foreign_keys_disabled_fails_before_migration(self):
        self.store.db.execute("PRAGMA foreign_keys=OFF")
        self.assertEqual(self.store.db.execute("PRAGMA foreign_keys").fetchone()[0], 0)
        with self.assertRaises(RuntimeError):
            initialize_platform_registry(self.store)
        tables = {
            r[0]
            for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertFalse(REGISTRY_TABLES & tables)
        marker_count = self.store.db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name=?", ("platform_registry_v1",)
        ).fetchone()[0]
        self.assertEqual(marker_count, 0)
        self.store.db.execute("PRAGMA foreign_keys=ON")


class _FailingConnection:
    def __init__(self, real, fail_marker):
        self._real = real
        self._fail_marker = fail_marker
        self.in_transaction = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def execute(self, sql, *args, **kwargs):
        self.in_transaction = getattr(self._real, "in_transaction", False)
        if self._fail_marker in sql:
            raise RuntimeError("injected migration failure")
        result = self._real.execute(sql, *args, **kwargs)
        self.in_transaction = getattr(self._real, "in_transaction", False)
        return result

    def executescript(self, *args, **kwargs):
        return self._real.executescript(*args, **kwargs)


class PlatformRegistryInjectedFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "injected.sqlite3"
        self.store = make_store(self.db_path)
        seed_existing_data(self.store, ResultsDB(self.db_path))
        self.store.db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_injected_failure_rolls_back_and_retry_succeeds(self):
        store = make_store(self.db_path)
        original_db = store.db
        proxy = _FailingConnection(original_db, "CREATE TABLE IF NOT EXISTS workspaces")
        store.db = proxy
        try:
            with self.assertRaises(RuntimeError):
                initialize_platform_registry(store)
        finally:
            store.db = original_db
        tables = {
            r[0]
            for r in original_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertFalse(REGISTRY_TABLES & tables)
        marker_count = original_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name=?", ("platform_registry_v1",)
        ).fetchone()[0]
        self.assertEqual(marker_count, 0)
        result = initialize_platform_registry(store)
        self.assertIn(result, ("initialized", "already-initialized"))
        tables = {
            r[0]
            for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertTrue(REGISTRY_TABLES.issubset(tables))
        store.db.close()


class PlatformRegistryFailClosedStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config.toml"
        self.config.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{self.root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{self.root}"\nallowed_commands=[]\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_create_app_raises_on_registry_failure(self):
        import sqlite3
        import unittest.mock as mock
        from evo_core import platform_registry
        from evo_core import api as api_module
        from evo_core.store import EvoStore as real_evo_store

        captured = {}

        def capturing_store(path):
            store = real_evo_store(path)
            captured["store"] = store
            return store

        with mock.patch.object(api_module, "EvoStore", side_effect=capturing_store):
            with mock.patch.object(
                platform_registry, "initialize_platform_registry", side_effect=RuntimeError("boom")
            ):
                from evo_core.api import create_app

                with self.assertRaises(RuntimeError):
                    create_app(self.config)

        self.assertIn("store", captured)
        with self.assertRaises(sqlite3.ProgrammingError):
            captured["store"].db.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
