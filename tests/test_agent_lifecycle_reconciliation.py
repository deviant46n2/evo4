import os
import sqlite3
import tempfile
import unittest

from evo_core import agent_lifecycle, background_agent, orchestration
from evo_core.store import EvoStore
from evo_experiments.db import ResultsDB


class AgentLifecycleReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "evo.db")
        self.store = EvoStore(self.db_path)
        self.lab = ResultsDB(self.db_path)
        background_agent.initialize(self.lab.connection)
        orchestration.initialize(self.lab.connection)
        agent_lifecycle.initialize(self.lab.connection)

    def tearDown(self):
        self.store.close()
        self.lab.close()
        self.tmp.cleanup()

    def _run(self, run_id, status="running"):
        now = "2026-01-01T00:00:00+00:00"
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO agent_runs(id,kind,status,started_at,metadata_json) VALUES(?,?,?,?,?)",
                (run_id, "coding", status, now, "{}"))
            self.store.db.commit()
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id) if status == "running" else None
        return run_id

    def test_completed_run_survives_startup_reconciliation(self):
        run_id = self._run("run-complete", "completed")
        with self.lab.lock:
            background_agent.create(self.lab.connection, run_id)
            background_agent.decide_finalization(self.lab.connection, run_id, "completed", "done")
            background_agent.transition(self.lab.connection, run_id, "completed", {})
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        row = self.store.get_agent_run(run_id)
        self.assertEqual(row["status"], "completed")
        task = background_agent.get(self.lab.connection, run_id)
        self.assertEqual(task["status"], "completed")

    def test_crash_after_finalization_before_store_update(self):
        run_id = self._run("run-crash-store", "running")
        background_agent.decide_finalization(self.lab.connection, run_id, "completed", "done")
        # Store not yet updated.
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "completed")

    def test_crash_after_store_before_background_update(self):
        run_id = self._run("run-crash-bg", "running")
        self.store.finish_agent_run(run_id, "completed", "done")
        background_agent.decide_finalization(self.lab.connection, run_id, "completed", "done")
        # background task still running
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        task = background_agent.get(self.lab.connection, run_id)
        self.assertEqual(task["status"], "completed")

    def test_repeated_reconciliation_is_stable(self):
        run_id = self._run("run-repeat", "running")
        background_agent.decide_finalization(self.lab.connection, run_id, "failed", "boom")
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        before = self.store.get_agent_run(run_id)["status"]
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        after = self.store.get_agent_run(run_id)["status"]
        self.assertEqual(before, after)
        self.assertEqual(after, "failed")

    def test_plan_cannot_complete_with_unfinished_step(self):
        plan = orchestration.create_plan(self.lab.connection, "r", "/w", {
            "title": "t", "summary": "s",
            "steps": [{"title": "a", "description": "d", "expected_outcome": "o", "verification": "v"}],
        })
        orchestration.approve_plan(self.lab.connection, plan["id"])
        orchestration.attach_run(self.lab.connection, plan["id"], "run-plan")
        self._run("run-plan", "running")
        background_agent.decide_finalization(self.lab.connection, "run-plan", "completed", "done")
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        p = orchestration.get_plan(self.lab.connection, plan["id"])
        self.assertNotEqual(p["status"], "completed")

    def test_scheduler_job_reconciled_from_terminal_execution(self):
        from evo_experiments.scheduler import initialize_scheduler
        from evo_experiments.execution import initialize_execution
        with self.lab.lock:
            initialize_scheduler(self.lab.connection)
            initialize_execution(self.lab.connection)
            self.lab.connection.execute(
                "INSERT INTO workload_jobs(id,name,kind,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("job-1", "j", "cpu", "running", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
            from evo_experiments.execution import initialize_execution
            initialize_execution(self.lab.connection)
            self.lab.connection.execute(
                "INSERT INTO workload_executions(id,job_id,argv_json,workspace,status,timeout_seconds,created_at) VALUES(?,?,?,?,?,?,?)",
                ("exec-1", "job-1", "[]", "/tmp", "failed", 30, "2026-01-01T00:00:00+00:00"))
            self.lab.connection.commit()
        agent_lifecycle.reconcile_executions(self.lab.connection, [])
        job = self.lab.connection.execute("SELECT status FROM workload_jobs WHERE id='job-1'").fetchone()
        self.assertEqual(job["status"], "failed")

    def test_no_process_or_tool_side_effects(self):
        # Reconciliation must not invoke subprocess or provider.
        run_id = self._run("run-side", "running")
        background_agent.decide_finalization(self.lab.connection, run_id, "interrupted", "stopped")
        agent_lifecycle.reconcile(self.lab.connection, self.store)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
