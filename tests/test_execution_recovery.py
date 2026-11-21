import io
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from evo_experiments.execution import (
    get_execution, initialize_execution, recover_interrupted_executions, register_execution,
    run_execution,
)
from evo_experiments.scheduler import create_job, dispatch_jobs, get_job, initialize_scheduler


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.pid = 999999
        self.returncode = 0
        self.stdout = io.BytesIO(b"worker-ok\n")
        self.stderr = io.BytesIO(b"")
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return None

    def kill(self):
        self.killed = True


class ExecutionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        initialize_scheduler(self.db)
        initialize_execution(self.db)
        self.allowed = [(sys.executable, "-c")]
        self.sample = {"ram_available_bytes": 8 * 1024 ** 3, "ram_used_percent": 40}

    def tearDown(self):
        self.db.close()

    def reserve(self, name="worker"):
        job = create_job(self.db, {
            "name": name, "kind": "cpu", "estimated_ram_mib": 128,
            "gpu_heavy": False,
        })
        dispatch_jobs(self.db, self.sample)
        self.assertEqual(get_job(self.db, job["id"])["status"], "reserved")
        return job

    def register(self, job, argv=None, timeout=5):
        argv = argv or [sys.executable, "-c", "print('worker-ok')"]
        return register_execution(self.db, job["id"], argv, self.allowed,
                                  tempfile.gettempdir(), timeout)

    def test_failure_before_subprocess_creation_marks_execution_failed(self):
        job = self.reserve("before-launch")
        record = self.register(job)
        with patch("evo_experiments.execution.subprocess.Popen", side_effect=RuntimeError("launch failed")):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("RuntimeError", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_failure_after_popen_before_pid_persistence_marks_failed_and_kills_group(self):
        job = self.reserve("pid-persist-failure")
        record = self.register(job)
        original_persist = __import__("evo_experiments.execution", fromlist=["_persist"])._persist

        def failing_persist(connection, lock, execution_id, **values):
            if values.get("status") == "running":
                raise RuntimeError("pid persistence failed")
            return original_persist(connection, lock, execution_id, **values)

        with patch("evo_experiments.execution.subprocess.Popen", FakeProcess), \
             patch("evo_experiments.execution._persist", side_effect=failing_persist), \
             patch("evo_experiments.execution.os.killpg") as killpg:
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("pid persistence failed", result["error"])
        self.assertIsNone(result["pid"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")
        killpg.assert_called()

    def test_recovery_of_launching_execution_never_signals(self):
        job = self.reserve("launching")
        record = self.register(job)
        self.db.execute("UPDATE workload_executions SET status='launching', pid=NULL WHERE id=?",
                        (record["id"],))
        self.db.commit()
        with patch("evo_experiments.execution.os.killpg") as killpg:
            recovered = recover_interrupted_executions(self.db)
        self.assertEqual(recovered, [record["id"]])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "launch_uncertain")
        self.assertIsNone(result["pid"])
        self.assertIn("did not signal", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")
        killpg.assert_not_called()

    def test_recovery_of_running_execution_preserves_pid(self):
        job = self.reserve("running")
        record = self.register(job)
        self.db.execute("UPDATE workload_executions SET status='running', pid=424242 WHERE id=?",
                        (record["id"],))
        self.db.commit()
        recovered = recover_interrupted_executions(self.db)
        self.assertEqual(recovered, [record["id"]])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["pid"], 424242)
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_launch_intent_persistence_failure_does_not_call_popen(self):
        job = self.reserve("launch-intent")
        record = self.register(job)

        class LaunchIntentProxy:
            def __init__(self, connection):
                self._connection = connection

            def execute(self, sql, *args, **kwargs):
                if "SET status='launching'" in sql:
                    raise sqlite3.OperationalError("launch intent write failed")
                return self._connection.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        proxy = LaunchIntentProxy(self.db)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(proxy, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("Launch intent could not be persisted", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_process_cleanup_permission_error_is_recorded_without_aborting_finalization(self):
        job = self.reserve("cleanup-permission")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)

        class PermissionProcess(FakeProcess):
            def wait(self, timeout=None):
                if not getattr(self, "_waited", False):
                    self._waited = True
                    raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=timeout)
                return 0

        with patch("evo_experiments.execution.subprocess.Popen", PermissionProcess),              patch("evo_experiments.execution.os.killpg", side_effect=PermissionError("not permitted")):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertIn("process group cleanup failed: PermissionError", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_partial_recovery_failure_rolls_back_and_can_retry(self):
        job_one = self.reserve("first")
        record_one = self.register(job_one)
        job_two = self.reserve("second")
        record_two = self.register(job_two)
        for record in (record_one, record_two):
            self.db.execute("UPDATE workload_executions SET status='launching', pid=NULL WHERE id=?",
                            (record["id"],))
        self.db.commit()

        original_get_job = __import__("evo_experiments.execution", fromlist=["get_job"]).get_job
        calls = {"count": 0}

        def failing_get_job(connection, job_id):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("forced recovery failure")
            return original_get_job(connection, job_id)

        with patch("evo_experiments.execution.get_job", side_effect=failing_get_job), \
             patch("evo_experiments.execution.os.killpg") as killpg:
            recovered = recover_interrupted_executions(self.db)
        killpg.assert_not_called()
        self.assertEqual(len(recovered), 1)
        statuses = {get_execution(self.db, record_one["id"])["status"],
                    get_execution(self.db, record_two["id"])["status"]}
        self.assertIn("launching", statuses)
        self.assertIn("launch_uncertain", statuses)

        # Retry after removing the injected failure.
        recovered_again = recover_interrupted_executions(self.db)
        self.assertEqual(len(recovered_again), 1)
        self.assertEqual(get_execution(self.db, record_one["id"])["status"], "launch_uncertain")
        self.assertEqual(get_execution(self.db, record_two["id"])["status"], "launch_uncertain")
        self.assertEqual(get_job(self.db, job_one["id"])["status"], "failed")
        self.assertEqual(get_job(self.db, job_two["id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
