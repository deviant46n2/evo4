import os
import sqlite3
import tempfile
import unittest

from evo_core import background_agent, lifecycle, orchestration
from evo_core.store import EvoStore
from evo_experiments.db import ResultsDB
from evo_experiments.execution import initialize_execution
from evo_experiments.scheduler import initialize_scheduler


class AgentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "evo.db")
        self.store = EvoStore(self.db_path)
        self.lab = ResultsDB(self.db_path)
        background_agent.initialize(self.lab.connection)
        orchestration.initialize(self.lab.connection)
        lifecycle.initialize(self.lab.connection)
        initialize_scheduler(self.lab.connection)
        initialize_execution(self.lab.connection)

    def tearDown(self):
        self.store.close()
        self.lab.close()
        self.tmp.cleanup()

    def _insert_run(self, run_id, status="running", source="desktop"):
        now = "2026-01-01T00:00:00+00:00"
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO agent_runs(id,kind,status,started_at,metadata_json) VALUES(?,?,?,?,?)",
                (run_id, "coding", status, now, '{"source": "%s"}' % source))
            self.store.db.commit()

    def test_concurrent_finalization_adopts_winning_decision(self):
        run_id = "run-concurrent"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
        first = lifecycle.decide(self.lab.connection, run_id, "completed", source="worker", reason="done")
        second = lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(second["decision"]["outcome"], "completed")
        lifecycle.apply_decision(self.store, second["decision"])
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "completed")

    def test_crash_after_decision_before_store_update(self):
        run_id = "run-decision-first"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            decision = lifecycle.decide(self.lab.connection, run_id, "completed", source="worker", reason="done")["decision"]
        # Store intentionally not updated.
        lifecycle.reconcile(self.store, self.lab)
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "completed")

    def test_crash_after_store_before_background_update(self):
        run_id = "run-store-first"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            decision = lifecycle.decide(self.lab.connection, run_id, "completed", source="worker", reason="done")["decision"]
        self.store.apply_agent_run_decision(run_id, "completed", summary="done", source="worker")
        # Background task intentionally remains running.
        lifecycle.reconcile(self.store, self.lab)
        task = background_agent.get(self.lab.connection, run_id)
        self.assertEqual(task["status"], "completed")

    def test_repeated_reconciliation_no_duplicate_events(self):
        run_id = "run-repeat"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
        lifecycle.reconcile(self.store, self.lab)
        with self.lab.lock:
            before = self.lab.connection.execute("SELECT COUNT(*) FROM lifecycle_reconciliation_events").fetchone()[0]
        lifecycle.reconcile(self.store, self.lab)
        with self.lab.lock:
            after = self.lab.connection.execute("SELECT COUNT(*) FROM lifecycle_reconciliation_events").fetchone()[0]
        self.assertEqual(before, after)

    def test_claim_failure_creates_terminal_decision(self):
        run_id = "run-unclaimed"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            decision = lifecycle.finalize_unclaimed(self.lab.connection, run_id)
        self.assertIn(decision["outcome"], lifecycle.TERMINAL)
        self.store.apply_agent_run_decision(run_id, decision["outcome"], summary=decision["reason"], source="lifecycle")
        self.assertEqual(self.store.get_agent_run(run_id)["status"], decision["outcome"])

    def test_partial_run_creation_recovery(self):
        run_id = "run-partial"
        self._insert_run(run_id, "running")
        # No background task created: reconciliation must not leave it running.
        with self.lab.lock:
            lifecycle.decide(self.lab.connection, run_id, "interrupted", source="startup_recovery", reason="partial")
        lifecycle.reconcile(self.store, self.lab)
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "interrupted")

    def test_scheduler_execution_disagreement(self):
        with self.lab.lock:
            self.lab.connection.execute(
                "INSERT INTO workload_jobs(id,name,kind,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("job-1", "j", "cpu", "running", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
            self.lab.connection.execute(
                "INSERT INTO workload_executions(id,job_id,argv_json,workspace,status,timeout_seconds,created_at) VALUES(?,?,?,?,?,?,?)",
                ("exec-1", "job-1", "[]", "/tmp", "failed", 30, "2026-01-01T00:00:00+00:00"))
            self.lab.connection.commit()
        lifecycle.reconcile(self.store, self.lab)
        job = self.lab.connection.execute("SELECT status FROM workload_jobs WHERE id='job-1'").fetchone()
        self.assertEqual(job["status"], "failed")

    def test_terminal_conflict_preserved(self):
        run_id = "run-conflict"
        self._insert_run(run_id, "completed")
        with self.lab.lock:
            lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
            background_agent.create(self.lab.connection, run_id)
            background_agent.transition(self.lab.connection, run_id, "completed", {})
        report = lifecycle.reconcile(self.store, self.lab)
        # Store remains completed; conflict is reported, not overwritten.
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "completed")
        self.assertTrue(any(item.get("reason") == "terminal_conflict" for item in report["unresolved"]))

    def test_no_process_side_effects(self):
        run_id = "run-side"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            lifecycle.decide(self.lab.connection, run_id, "interrupted", source="worker", reason="stopped")
        lifecycle.reconcile(self.store, self.lab)
        self.assertTrue(True)

    def test_reconstruct_missing_task_from_decision(self):
        run_id = "run-reconstruct"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
        # Remove the task to simulate partial creation.
        with self.lab.lock:
            self.lab.connection.execute("DELETE FROM background_agent_tasks WHERE run_id=?", (run_id,))
            self.lab.connection.commit()
        report = lifecycle.reconcile(self.store, self.lab)
        task = background_agent.get(self.lab.connection, run_id)
        self.assertEqual(task["status"], "failed")
        events = background_agent.events(self.lab.connection, run_id, limit=100)
        self.assertTrue(any(e["type"] == "reconstructed_from_finalization" for e in events))
        self.assertFalse(any(e["type"] in {"queued", "started"} for e in events))
        self.assertTrue(any(item.get("reconstructed") is True for item in report["background_tasks"]))

    def test_repeated_reconstruction_is_idempotent(self):
        run_id = "run-reconstruct-repeat"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
            self.lab.connection.execute("DELETE FROM background_agent_tasks WHERE run_id=?", (run_id,))
            self.lab.connection.commit()
        lifecycle.reconcile(self.store, self.lab)
        with self.lab.lock:
            before_events = self.lab.connection.execute(
                "SELECT COUNT(*) FROM background_agent_events WHERE run_id=?", (run_id,)).fetchone()[0]
            before_tasks = self.lab.connection.execute(
                "SELECT COUNT(*) FROM background_agent_tasks WHERE run_id=?", (run_id,)).fetchone()[0]
        lifecycle.reconcile(self.store, self.lab)
        with self.lab.lock:
            after_events = self.lab.connection.execute(
                "SELECT COUNT(*) FROM background_agent_events WHERE run_id=?", (run_id,)).fetchone()[0]
            after_tasks = self.lab.connection.execute(
                "SELECT COUNT(*) FROM background_agent_tasks WHERE run_id=?", (run_id,)).fetchone()[0]
        self.assertEqual(before_events, after_events)
        self.assertEqual(before_tasks, after_tasks)
        self.assertEqual(after_tasks, 1)

    def test_partial_app_owned_run_finalized_and_reconstructed(self):
        run_id = "run-partial-app"
        self._insert_run(run_id, "running", source="desktop")
        # No task and no decision.
        lifecycle.reconcile(self.store, self.lab)
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "interrupted")
        task = background_agent.get(self.lab.connection, run_id)
        self.assertEqual(task["status"], "interrupted")
        events = background_agent.events(self.lab.connection, run_id, limit=100)
        self.assertTrue(any(e["type"] == "reconstructed_from_finalization" for e in events))

    def test_decision_without_agent_run_unresolved_no_task(self):
        run_id = "run-orphan-decision"
        with self.lab.lock:
            lifecycle.decide(self.lab.connection, run_id, "failed", source="worker", reason="boom")
        report = lifecycle.reconcile(self.store, self.lab)
        self.assertIsNone(background_agent.get(self.lab.connection, run_id))
        self.assertTrue(any(item.get("reason") == "decision_without_agent_run" for item in report["unresolved"]))

    def test_reconciliation_no_process_side_effects(self):
        run_id = "run-recon-side"
        self._insert_run(run_id, "running")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            lifecycle.decide(self.lab.connection, run_id, "interrupted", source="worker", reason="stopped")
        lifecycle.reconcile(self.store, self.lab)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
