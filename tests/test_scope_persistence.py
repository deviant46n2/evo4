import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_core.orchestration import create_plan, get_plan, initialize
from evo_core.store import EvoStore


class ScopePersistenceTests(unittest.TestCase):
    def _fixtures(self, store, root):
        from evo_core.platform_registry import initialize_platform_registry
        from evo_core.project_checkouts import register_project, register_checkout
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        initialize_platform_registry(store)
        project = register_project(store, "Project")
        directory = root / "checkout"
        directory.mkdir()
        checkout = register_checkout(store, project["project_id"], directory)
        config = create_configuration(store, {"schema_version": 1, "components": {}}, name="cfg")
        workspace = create_workspace(store, "Workspace", project["project_id"],
                                    config["configuration"]["configuration_id"], config["revision"]["revision_id"],
                                    checkout_id=checkout["checkout_id"])
        return project, workspace
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

    def _fixtures(self, store, root):
        from evo_core.platform_registry import initialize_platform_registry
        from evo_core.project_checkouts import register_project, register_checkout
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        initialize_platform_registry(store)
        project = register_project(store, "Project")
        directory = root / "checkout"
        directory.mkdir()
        checkout = register_checkout(store, project["project_id"], directory)
        config = create_configuration(store, {"schema_version": 1, "components": {}}, name="cfg")
        workspace = create_workspace(
            store, "Workspace", project["project_id"],
            config["configuration"]["configuration_id"], config["revision"]["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        return project, workspace

    def test_conversation_scope_persists_and_defaults_to_global(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                global_id = store.create_conversation("global")
                project_only_id = store.create_conversation("project", project_id=project["project_id"])
                scoped_id = store.create_conversation("scoped", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                global_row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (global_id,)).fetchone()
                project_row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (project_only_id,)).fetchone()
                scoped_row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (scoped_id,)).fetchone()
                self.assertIsNone(global_row["project_id"])
                self.assertIsNone(global_row["workspace_id"])
                self.assertEqual(project_row["project_id"], project["project_id"])
                self.assertIsNone(project_row["workspace_id"])
                self.assertEqual(scoped_row["project_id"], project["project_id"])
                self.assertEqual(scoped_row["workspace_id"], workspace["workspace_id"])
            finally:
                store.db.close()

    def test_context_records_persist_explicit_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                memory_id = store.add_memory("memory", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                lesson_id = store.add_lesson("lesson", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                research_id = store.add_research_document("title", "content", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                task_id = store.add_task("task", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                for table, row_id in (("memories", memory_id), ("lessons", lesson_id),
                                      ("research_documents", research_id), ("tasks", task_id)):
                    row = store.db.execute(f"SELECT project_id, workspace_id FROM {table} WHERE id=?", (row_id,)).fetchone()
                    self.assertEqual(row["project_id"], project["project_id"], table)
                    self.assertEqual(row["workspace_id"], workspace["workspace_id"], table)

                unscoped_memory = store.add_memory("global memory")
                row = store.db.execute("SELECT project_id, workspace_id FROM memories WHERE id=?", (unscoped_memory,)).fetchone()
                self.assertIsNone(row["project_id"])
                self.assertIsNone(row["workspace_id"])
            finally:
                store.db.close()

    def test_scope_validation_rejects_unknown_project(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvoStore(Path(temp) / "evo.sqlite3")
            try:
                with self.assertRaises(ValueError):
                    store.validate_scope("missing-project", None)
            finally:
                store.db.close()

    def test_scope_validation_rejects_unknown_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                from evo_core.platform_registry import initialize_platform_registry
                from evo_core.project_checkouts import register_project
                initialize_platform_registry(store)
                project = register_project(store, "Project")
                with self.assertRaises(ValueError):
                    store.validate_scope(project["project_id"], "missing-workspace")
            finally:
                store.db.close()

    def test_scope_validation_rejects_workspace_without_project(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvoStore(Path(temp) / "evo.sqlite3")
            try:
                with self.assertRaises(ValueError):
                    store.validate_scope(None, "workspace-1")
            finally:
                store.db.close()

    def test_scope_validation_rejects_mismatched_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                other_project, _ = (register_project(store, "Other"), None) if False else (None, None)
                from evo_core.project_checkouts import register_project
                other = register_project(store, "Other")
                # Create a workspace for the other project by reusing a checkout in that project.
                other_dir = root / "other-checkout"
                other_dir.mkdir()
                from evo_core.project_checkouts import register_checkout
                other_checkout = register_checkout(store, other["project_id"], other_dir)
                from evo_core.ai_configurations import create_configuration
                from evo_core.workspaces import create_workspace
                cfg = create_configuration(store, {"schema_version": 1, "components": {}}, name="cfg2")
                other_workspace = create_workspace(store, "OtherWorkspace", other["project_id"],
                                                  cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                                  checkout_id=other_checkout["checkout_id"])
                with self.assertRaises(ValueError):
                    store.validate_scope(project["project_id"], other_workspace["workspace_id"])
            finally:
                store.db.close()

    def test_memory_candidate_ownership_follows_source_conversation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                conversation_id = store.create_conversation("scoped", project_id=project["project_id"], workspace_id=workspace["workspace_id"])
                candidate_id = store.propose_memory("remember this", conversation_id=conversation_id)
                row = store.db.execute("SELECT project_id, workspace_id FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
                self.assertEqual(row["project_id"], project["project_id"])
                self.assertEqual(row["workspace_id"], workspace["workspace_id"])
                accepted_id = store.review_memory_candidate(candidate_id, True)
                memory = store.db.execute("SELECT project_id, workspace_id FROM memories WHERE id=?", (accepted_id,)).fetchone()
                self.assertEqual(memory["project_id"], project["project_id"])
                self.assertEqual(memory["workspace_id"], workspace["workspace_id"])

                global_conversation_id = store.create_conversation("global")
                global_candidate_id = store.propose_memory("global memory", conversation_id=global_conversation_id)
                global_row = store.db.execute("SELECT project_id, workspace_id FROM memory_candidates WHERE id=?", (global_candidate_id,)).fetchone()
                self.assertIsNone(global_row["project_id"])
                self.assertIsNone(global_row["workspace_id"])
            finally:
                store.db.close()

    def test_memory_candidate_rejects_inconsistent_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                with self.assertRaises(ValueError):
                    store.propose_memory("bad", project_id=project["project_id"], workspace_id="wrong-workspace")
            finally:
                store.db.close()

    def test_memory_candidate_dedup_is_scope_aware(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                global_first = store.propose_memory("same content")
                global_second = store.propose_memory("same content")
                project_first = store.propose_memory("same content", project_id=project["project_id"])
                self.assertEqual(global_first, global_second)
                self.assertNotEqual(global_first, project_first)

                from evo_core.project_checkouts import register_project
                other_project = register_project(store, "Other")
                other_candidate = store.propose_memory("same content", project_id=other_project["project_id"])
                self.assertNotEqual(project_first, other_candidate)
                self.assertEqual(store.propose_memory("same content", project_id=other_project["project_id"]), other_candidate)
            finally:
                store.db.close()

    def test_create_plan_rejects_invalid_scope_with_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            initialize(store.db)
            try:
                with self.assertRaises(ValueError):
                    create_plan(store.db, "request", "workspace", "/workspace",
                                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                                project_id="missing", store=store)
                with self.assertRaises(ValueError):
                    create_plan(store.db, "request", "workspace", "/workspace",
                                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                                project_id="project", workspace_id=None, store=store)
            finally:
                store.db.close()

    def test_scope_normalization_persists_trimmed_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EvoStore(root / "evo.sqlite3")
            try:
                project, workspace = self._fixtures(store, root)
                padded_project = "  " + project["project_id"] + "  "
                padded_workspace = "  " + workspace["workspace_id"] + "  "
                conversation_id = store.create_conversation("scoped", project_id=padded_project, workspace_id=padded_workspace)
                memory_id = store.add_memory("memory", project_id=padded_project, workspace_id=padded_workspace)
                row = store.db.execute("SELECT project_id, workspace_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
                self.assertEqual(row["project_id"], project["project_id"])
                self.assertEqual(row["workspace_id"], workspace["workspace_id"])
                memory = store.db.execute("SELECT project_id, workspace_id FROM memories WHERE id=?", (memory_id,)).fetchone()
                self.assertEqual(memory["project_id"], project["project_id"])
                self.assertEqual(memory["workspace_id"], workspace["workspace_id"])
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
