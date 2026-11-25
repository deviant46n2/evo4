import sqlite3
import unittest

from evo_core.background_agent import (
    claim, create, events, initialize, is_cancelled, recover,
    request_cancel, transition, reconstruct_terminal,
)

class BackgroundAgentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE agent_runs(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, summary TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}')""")
        self.db.execute(
            """INSERT INTO agent_runs(id,kind,status,started_at,metadata_json)
               VALUES('run-1','coding','running','now',?)""",
            ('{"project_id":"project-1","workspace_id":"workspace-1"}',))
        initialize(self.db)
        create(self.db, "run-1")

    def tearDown(self):
        self.db.close()

    def test_scope_is_first_class_and_survives_restart_recovery(self):
        task = self.db.execute(
            "SELECT project_id,workspace_id FROM background_agent_tasks WHERE run_id='run-1'"
        ).fetchone()
        self.assertEqual(task["project_id"], "project-1")
        self.assertEqual(task["workspace_id"], "workspace-1")
        claim(self.db, "run-1", "worker-a")
        self.assertEqual(recover(self.db), ["run-1"])
        recovered = self.db.execute(
            "SELECT project_id,workspace_id,status FROM background_agent_tasks WHERE run_id='run-1'"
        ).fetchone()
        self.assertEqual(recovered["project_id"], "project-1")
        self.assertEqual(recovered["workspace_id"], "workspace-1")
        self.assertEqual(recovered["status"], "interrupted")
        queued = events(self.db, "run-1")[0]
        self.assertEqual(queued["payload"]["project_id"], "project-1")
        self.assertEqual(queued["payload"]["workspace_id"], "workspace-1")

    def test_scope_metadata_rejects_workspace_without_project(self):
        self.db.execute(
            "UPDATE agent_runs SET metadata_json=? WHERE id='run-1'",
            ('{"workspace_id":"workspace-1"}',))
        with self.assertRaisesRegex(ValueError, "requires project_id"):
            create(self.db, "run-1")

    def test_reconstructed_terminal_task_retains_run_scope(self):
        self.db.execute(
            """INSERT INTO agent_runs(id,kind,status,started_at,metadata_json)
               VALUES('run-2','coding','failed','now',?)""",
            ('{"project_id":"project-2","workspace_id":"workspace-2"}',))
        self.assertTrue(reconstruct_terminal(self.db, "run-2", "failed", reason="reconciled"))
        task = self.db.execute(
            "SELECT project_id,workspace_id,status FROM background_agent_tasks WHERE run_id='run-2'"
        ).fetchone()
        self.assertEqual(task["project_id"], "project-2")
        self.assertEqual(task["workspace_id"], "workspace-2")
        self.assertEqual(task["status"], "failed")

    def test_atomic_claim_only_once(self):
        self.assertTrue(claim(self.db, "run-1", "worker-a"))
        self.assertFalse(claim(self.db, "run-1", "worker-b"))

    def test_cancel_is_persistent_and_terminal_transition(self):
        self.assertTrue(request_cancel(self.db, "run-1"))
        self.assertTrue(is_cancelled(self.db, "run-1"))
        self.assertTrue(transition(self.db, "run-1", "cancelled"))
        self.assertFalse(transition(self.db, "run-1", "completed"))

    def test_repeated_cancel_does_not_duplicate_event(self):
        self.assertTrue(request_cancel(self.db, "run-1"))
        self.assertTrue(request_cancel(self.db, "run-1"))
        self.assertEqual([e["type"] for e in events(self.db, "run-1")].count("cancel_requested"), 1)

    def test_events_are_ordered_and_incremental(self):
        claim(self.db, "run-1", "worker-a")
        transition(self.db, "run-1", "awaiting_approval", {"tool": "write_file"})
        all_events = events(self.db, "run-1")
        self.assertEqual([e["type"] for e in all_events], ["queued", "started", "awaiting_approval"])
        self.assertEqual(events(self.db, "run-1", after_id=all_events[1]["id"])[0]["type"], "awaiting_approval")

    def test_restart_marks_nonterminal_as_interrupted_without_resuming(self):
        claim(self.db, "run-1", "worker-a")
        self.assertEqual(recover(self.db), ["run-1"])
        self.assertEqual(events(self.db, "run-1")[-1]["payload"]["resume_safe"], False)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            transition(self.db, "run-1", "running-again")

if __name__ == "__main__":
    unittest.main()
