import sqlite3
import sys
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from evo_experiments.execution import (
    _safe_environment, command_allowed, get_execution, initialize_execution, list_executions,
    recover_interrupted_executions, register_execution, run_execution,
)
from evo_experiments.scheduler import create_job, dispatch_jobs, get_job, initialize_scheduler


class ManagedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        initialize_scheduler(self.db)
        initialize_execution(self.db)
        self.allowed = [(sys.executable, "-c")]
        self.sample = {"ram_available_bytes": 8 * 1024**3, "ram_used_percent": 40}

    def tearDown(self):
        self.db.close()

    def reserve(self, name="worker", ram=128):
        job = create_job(self.db, {
            "name": name, "kind": "cpu", "estimated_ram_mib": ram,
            "gpu_heavy": False,
        })
        dispatch_jobs(self.db, self.sample)
        self.assertEqual(get_job(self.db, job["id"])["status"], "reserved")
        return job

    def register(self, job, argv, timeout=5):
        return register_execution(self.db, job["id"], argv, self.allowed,
                                  tempfile.gettempdir(), timeout)

    def test_command_must_match_explicit_argv_prefix(self):
        self.assertTrue(command_allowed([sys.executable, "-c", "print(1)"], self.allowed))
        self.assertFalse(command_allowed(["sh", "-c", "echo unsafe"], self.allowed))
        self.assertFalse(command_allowed([sys.executable, "-c", "x\x00y"], self.allowed))
        self.assertFalse(command_allowed([], self.allowed))

    def test_execution_captures_output_and_completes_scheduler_job(self):
        job = self.reserve()
        record = self.register(job, [sys.executable, "-c", "print('worker-ok')"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "running")
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("worker-ok", result["stdout"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "completed")
        self.assertIsNone(result["pid"])

    def test_child_process_descendants_do_not_outlive_managed_command(self):
        job = self.reserve("child cleanup")
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])"
        record = self.register(job, [sys.executable, "-c", code])
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertLess(result["elapsed_seconds"], 5)

    def test_credential_environment_is_filtered_without_broad_substring_matches(self):
        with patch.dict(os.environ, {
            "EVO_TEST_TOKEN": "secret-value",
            "EVO_TEST_API_KEY": "secret-key",
            "EVO_TEST_SETTING": "ordinary",
            "MONKEY": "banana",
        }, clear=False):
            env = _safe_environment()
        self.assertNotIn("EVO_TEST_TOKEN", env)
        self.assertNotIn("EVO_TEST_API_KEY", env)
        self.assertEqual(env["EVO_TEST_SETTING"], "ordinary")
        self.assertEqual(env["MONKEY"], "banana")

    def test_nonzero_exit_is_failed_and_stderr_is_captured(self):
        job = self.reserve("failure")
        record = self.register(job, [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"])
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["returncode"], 7)
        self.assertIn("bad", result["stderr"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_timeout_terminates_only_the_evo_created_process_group(self):
        job = self.reserve("timeout")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertIsNone(result["pid"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_output_is_bounded_to_recent_tail(self):
        job = self.reserve("large output")
        code = "print('x' * 40000)"
        record = self.register(job, [sys.executable, "-c", code])
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 20000)

    def test_environment_contract_rejects_sensitive_values(self):
        job = self.reserve("env")
        with self.assertRaisesRegex(ValueError, "sensitive"):
            register_execution(self.db, job["id"], [sys.executable, "-c", "print(1)"],
                               self.allowed, tempfile.gettempdir(),
                               environment={"API_KEY": "secret"})

    def test_expected_artifacts_are_collected(self):
        root = Path(tempfile.mkdtemp())
        (root / "out.txt").write_text("artifact", encoding="utf-8")
        job = self.reserve("artifact")
        record = register_execution(
            self.db, job["id"], [sys.executable, "-c", "print('ok')"],
            self.allowed, str(root), expected_artifacts=["out.txt", "missing.txt"],
        )
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        artifacts = {item["path"]: item for item in result["artifacts"]}
        self.assertEqual(artifacts["out.txt"]["status"], "collected")
        self.assertEqual(artifacts["missing.txt"]["status"], "missing")

    def test_duplicate_execution_and_unapproved_command_are_rejected(self):
        job = self.reserve("duplicate")
        with self.assertRaisesRegex(ValueError, "not permitted"):
            register_execution(self.db, job["id"], ["sh", "-c", "echo nope"],
                               self.allowed, tempfile.gettempdir())
        record = self.register(job, [sys.executable, "-c", "print(1)"])
        with self.assertRaisesRegex(ValueError, "Only a reserved job"):
            register_execution(self.db, job["id"], [sys.executable, "-c", "print(2)"],
                               self.allowed, tempfile.gettempdir())
        self.assertEqual(len(list_executions(self.db)), 1)
        self.assertEqual(record["status"], "queued")

    def test_execution_rechecks_persisted_policy_at_launch(self):
        job = self.reserve("policy recheck")
        record = self.register(job, [sys.executable, "-c", "print('should-not-run')"])
        self.db.execute(
            "UPDATE workload_executions SET policy_json='[]' WHERE id=?", (record["id"],)
        )
        self.db.commit()
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(self.db, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("execution policy snapshot", result["error"])

    def test_restart_recovery_marks_interrupted_without_signalling_pid(self):
        job = self.reserve("restart")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(10)"])
        self.db.execute("UPDATE workload_executions SET status='running',pid=424242 WHERE id=?",
                        (record["id"],))
        self.db.commit()
        recovered = recover_interrupted_executions(self.db)
        self.assertEqual(recovered, [record["id"]])
        saved = get_execution(self.db, record["id"])
        self.assertEqual(saved["status"], "interrupted")
        self.assertEqual(saved["pid"], 424242)
        self.assertIn("did not signal", saved["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
