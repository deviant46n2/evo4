import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_core.orchestration import create_plan, get_plan, initialize
from evo_core.store import EvoStore


class ScopePersistenceTests(unittest.TestCase):
    def test_legacy_database_receives_scope_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "legacy.db"
            # Create an older schema without scope columns.
            connection = sqlite3.connect(db_path)
            connection.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general', tags_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'user', confidence REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, last_accessed_at TEXT, access_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE lessons (id TEXT PRIMARY KEY, trigger_text TEXT NOT NULL,
                    lesson TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general',
                    source TEXT NOT NULL DEFAULT 'user', confidence REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE research_documents (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    url TEXT, content TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'manual',
                    captured_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
                    priority INTEGER NOT NULL DEFAULT 3, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, due_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE agent_plans (id TEXT PRIMARY KEY, request TEXT NOT NULL,
                    workspace TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
            """)
            connection.commit()
            connection.close()

            store = EvoStore(db_path)
            try:
                for table in ("conversations", "memories", "lessons", "research_documents", "tasks"):
                    columns = {row[1] for row in store.db.execute(f"PRAGMA table_info({table})").fetchall()}
                    self.assertIn("project_id", columns)
                    self.assertIn("workspace_id", columns)
                initialize(store.db)
                plan_columns = {row[1] for row in store.db.execute("PRAGMA table_info(agent_plans)").fetchall()}
                self.assertIn("project_id", plan_columns)
                self.assertIn("workspace_id", plan_columns)
            finally:
                store.db.close()

    def test_conversation_scope_persists_and_defaults_to_global(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvoStore(Path(temp) / "evo.sqlite3")
            try:
                global_id = store.create_conversation("global")
                scoped_id = store.create_conversation("scoped", project_id="project-1", workspace_id="workspace-1")
                global_row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (global_id,)).fetchone()
                scoped_row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (scoped_id,)).fetchone()
                self.assertIsNone(global_row["project_id"])
                self.assertIsNone(global_row["workspace_id"])
                self.assertEqual(scoped_row["project_id"], "project-1")
                self.assertEqual(scoped_row["workspace_id"], "workspace-1")
            finally:
                store.db.close()

    def test_context_records_persist_explicit_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvoStore(Path(temp) / "evo.sqlite3")
            try:
                memory_id = store.add_memory("memory", project_id="project-1", workspace_id="workspace-1")
                lesson_id = store.add_lesson("lesson", project_id="project-1", workspace_id="workspace-1")
                research_id = store.add_research_document("title", "content", project_id="project-1", workspace_id="workspace-1")
                task_id = store.add_task("task", project_id="project-1", workspace_id="workspace-1")
                for table, row_id in (("memories", memory_id), ("lessons", lesson_id),
                                      ("research_documents", research_id), ("tasks", task_id)):
                    row = store.db.execute(f"SELECT project_id, workspace_id FROM {table} WHERE id=?", (row_id,)).fetchone()
                    self.assertEqual(row["project_id"], "project-1", table)
                    self.assertEqual(row["workspace_id"], "workspace-1", table)

                unscoped_memory = store.add_memory("global memory")
                row = store.db.execute("SELECT project_id, workspace_id FROM memories WHERE id=?", (unscoped_memory,)).fetchone()
                self.assertIsNone(row["project_id"])
                self.assertIsNone(row["workspace_id"])
            finally:
                store.db.close()

    def test_agent_plan_scope_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvoStore(Path(temp) / "evo.sqlite3")
            initialize(store.db)
            try:
                plan = create_plan(store.db, "request", "workspace-1", "/workspace", {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                                    project_id="project-1")
                loaded = get_plan(store.db, plan["id"])
                self.assertEqual(loaded["workspace_id"], "workspace-1")
                self.assertEqual(loaded["project_id"], "project-1")
                legacy = create_plan(store.db, "legacy", None, "/workspace", {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]})
                self.assertIsNone(get_plan(store.db, legacy["id"])["project_id"])
            finally:
                store.db.close()
