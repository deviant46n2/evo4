import sqlite3
import unittest

from evo_core.background_agent import (
    claim, create, events, initialize, is_cancelled, recover,
    request_cancel, transition,
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
            "INSERT INTO agent_runs(id,kind,status,started_at) VALUES('run-1','coding','running','now')")
        initialize(self.db)
        create(self.db, "run-1")

    def tearDown(self):
        self.db.close()

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
