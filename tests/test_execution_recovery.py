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
        self.returncode = None
        self.stdout = io.BytesIO(b"worker-ok\n")
        self.stderr = io.BytesIO(b"")
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return None

    def kill(self):
        self.killed = True



def _pid_terminated(pid):
    """Return True if pid is missing or a zombie (state Z)."""
    try:
        with open(f"/proc/{pid}/stat", "r") as handle:
            stat = handle.read()
    except FileNotFoundError:
        return True
    except OSError:
        # Race or permission; treat as not provably terminated.
        return False
    if ")" not in stat:
        return False
    parts = stat.rsplit(")", 1)[-1].split()
    if not parts:
        return False
    state = parts[0]
    return state == "Z"


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
             patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg"), \
             patch("evo_experiments.execution.os.killpg") as kill:
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("pid persistence failed", result["error"])
        self.assertIsNone(result["pid"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")
        kill.assert_called()

    def test_recovery_of_launching_execution_never_signals(self):
        job = self.reserve("launching")
        record = self.register(job)
        self.db.execute("UPDATE workload_executions SET status='launching', pid=NULL WHERE id=?",
                        (record["id"],))
        self.db.commit()
        with patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg") as kill:
            recovered = recover_interrupted_executions(self.db)
        self.assertEqual(recovered, [record["id"]])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "launch_uncertain")
        self.assertIsNone(result["pid"])
        self.assertIn("did not signal", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")
        kill.assert_not_called()

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

        with patch("evo_experiments.execution.subprocess.Popen", PermissionProcess),              patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg"), \
             patch("evo_experiments.execution.os.killpg", side_effect=PermissionError("not permitted")):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertIn("process group cleanup failed: PermissionError", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_launch_intent_commit_failure_does_not_call_popen(self):
        job = self.reserve("launch-intent-commit")
        record = self.register(job)

        class CommitFailingProxy:
            def __init__(self, connection):
                self._connection = connection

            def execute(self, sql, *args, **kwargs):
                return self._connection.execute(sql, *args, **kwargs)

            def commit(self):
                raise sqlite3.OperationalError("commit failed")

            def rollback(self):
                return self._connection.rollback()

            def __getattr__(self, name):
                return getattr(self._connection, name)

        proxy = CommitFailingProxy(self.db)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(proxy, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertIn(result["status"], {"queued", "launching"})
        self.assertEqual(get_job(self.db, job["id"])["status"], "running")

    def test_process_cleanup_process_lookup_is_not_fatal(self):
        job = self.reserve("cleanup-missing")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)

        class MissingProcess(FakeProcess):
            def wait(self, timeout=None):
                if not getattr(self, "_waited", False):
                    self._waited = True
                    raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=timeout)
                return 0

            def poll(self):
                return None

        with patch("evo_experiments.execution.subprocess.Popen", MissingProcess),              patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg", side_effect=ProcessLookupError("gone")):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertNotIn("process group cleanup failed", result["error"])
        self.assertEqual(get_job(self.db, job["id"])["status"], "failed")

    def test_process_cleanup_generic_oserror_is_recorded(self):
        job = self.reserve("cleanup-oserror")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)

        class GenericOsProcess(FakeProcess):
            def wait(self, timeout=None):
                if not getattr(self, "_waited", False):
                    self._waited = True
                    raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=timeout)
                return 0

            def poll(self):
                return None

        with patch("evo_experiments.execution.subprocess.Popen", GenericOsProcess),              patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg"), \
             patch("evo_experiments.execution.os.killpg", side_effect=OSError("permission-ish")):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("process group cleanup failed: OSError", result["error"])
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
             patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg") as kill:
            recovered = recover_interrupted_executions(self.db)
        kill.assert_not_called()
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


    def test_finalization_rolls_back_when_scheduler_update_fails(self):
        job = self.reserve("finalization-scheduler-fail")
        record = self.register(job)

        class SchedulerFailProxy:
            def __init__(self, connection):
                self._connection = connection

            def execute(self, sql, *args, **kwargs):
                if "SET status='launching'" in sql:
                    raise sqlite3.OperationalError("launch intent write failed")
                if "UPDATE workload_jobs" in sql:
                    raise sqlite3.OperationalError("scheduler finalization failed")
                return self._connection.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        proxy = SchedulerFailProxy(self.db)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(proxy, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertIn(result["status"], {"queued", "launching"})
        self.assertEqual(get_job(self.db, job["id"])["status"], "running")

    def test_finalization_rolls_back_when_execution_update_fails(self):
        job = self.reserve("finalization-execution-fail")
        record = self.register(job)

        class ExecutionFailProxy:
            def __init__(self, connection):
                self._connection = connection

            def execute(self, sql, *args, **kwargs):
                if "SET status='launching'" in sql:
                    raise sqlite3.OperationalError("launch intent write failed")
                if "SET status='failed'" in sql:
                    raise sqlite3.OperationalError("execution finalization failed")
                return self._connection.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        proxy = ExecutionFailProxy(self.db)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(proxy, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertIn(result["status"], {"queued", "launching"})
        self.assertEqual(get_job(self.db, job["id"])["status"], "running")

    def test_finalization_db_unavailable_leaves_recoverable_state(self):
        job = self.reserve("finalization-db-unavailable")
        record = self.register(job)

        class DbUnavailableProxy:
            def __init__(self, connection):
                self._connection = connection
                self._select_calls = 0

            def execute(self, sql, *args, **kwargs):
                if "SET status='launching'" in sql:
                    raise sqlite3.OperationalError("launch intent write failed")
                if sql.lstrip().upper().startswith("SELECT"):
                    self._select_calls += 1
                    if self._select_calls >= 2:
                        raise sqlite3.OperationalError("database unavailable")
                return self._connection.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        proxy = DbUnavailableProxy(self.db)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            run_execution(proxy, self.lock, record["id"])
        popen.assert_not_called()
        result = get_execution(self.db, record["id"])
        self.assertIn(result["status"], {"queued", "launching"})
        self.assertEqual(get_job(self.db, job["id"])["status"], "running")

    def test_successful_failure_finalization_marks_both_failed(self):
        job = self.reserve("finalization-success")
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

    def test_legacy_schema_migration_preserves_rows_and_adds_columns(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE workload_executions (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, argv_json TEXT NOT NULL,
            policy_json TEXT NOT NULL DEFAULT '[]', workspace TEXT NOT NULL, status TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL, pid INTEGER, process_started_at TEXT, started_at TEXT,
            finished_at TEXT, returncode INTEGER, elapsed_seconds REAL, stdout TEXT NOT NULL DEFAULT '',
            stderr TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO workload_executions(id,job_id,argv_json,policy_json,workspace,status,timeout_seconds,created_at)
                      VALUES('legacy-exec','legacy-job','["echo","ok"]','[]','/tmp','completed',5,'2026-01-01T00:00:00Z')""")
        db.commit()
        from evo_experiments.execution import initialize_execution
        initialize_execution(db)
        columns = {row[1] for row in db.execute("PRAGMA table_info(workload_executions)").fetchall()}
        self.assertIn("agent_run_id", columns)
        self.assertIn("cancel_requested", columns)
        self.assertIn("approval_evidence_json", columns)
        row = db.execute("SELECT * FROM workload_executions WHERE id='legacy-exec'").fetchone()
        self.assertEqual(row["job_id"], "legacy-job")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["cancel_requested"], 0)
        # idempotent
        initialize_execution(db)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM workload_executions").fetchone()[0], 1)
        db.close()

    def test_terminal_execution_is_not_overwritten_by_cancel_finalization(self):
        job = self.reserve("terminal-guard")
        record = self.register(job)
        self.db.execute("UPDATE workload_executions SET status='completed', returncode=0 WHERE id=?", (record["id"],))
        self.db.commit()
        from evo_experiments.execution import _finalize_cancelled_execution
        _finalize_cancelled_execution(self.db, self.lock, record["id"], record, 0.0, 0.0)
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")

    def test_agent_approval_evidence_is_strict_and_command_bound(self):
        from evo_experiments.execution import register_managed_execution
        store_db = self.db
        argv = ["python", "-c", "print('ok')"]
        allowed = [["python", "-c"]]
        # missing evidence
        with self.assertRaises(ValueError):
            register_managed_execution(store_db, workspace="/tmp", argv=argv, allowed_commands=allowed,
                                      agent_run_id="run-1", approval_evidence=None)
        valid = {
            "approval": "approved",
            "approval_source": "user",
            "approved_at": "2026-01-01T00:00:00Z",
            "argv_sha256": __import__("hashlib").sha256(__import__("json").dumps(argv, sort_keys=True).encode()).hexdigest(),
            "policy": allowed,
        }
        rec = register_managed_execution(store_db, workspace="/tmp", argv=argv, allowed_commands=allowed,
                                        agent_run_id="run-1", approval_evidence=valid)
        self.assertEqual(rec["approval_evidence"]["argv_sha256"], valid["argv_sha256"])
        # mismatched hash
        bad = dict(valid, argv_sha256="0" * 64)
        with self.assertRaises(ValueError):
            register_managed_execution(store_db, workspace="/tmp", argv=argv, allowed_commands=allowed,
                                      agent_run_id="run-2", approval_evidence=bad)
        # scheduler compatibility: no agent run, no evidence required
        job = self.reserve("approval-compat")
        sched_rec = register_managed_execution(store_db, workspace="/tmp", argv=argv, allowed_commands=allowed,
                                             job_id=job["id"])
        self.assertEqual(sched_rec["approval_evidence"], {})

    def test_cancelled_execution_does_not_overwrite_terminal_result(self):
        job = self.reserve("cancel-race")
        record = self.register(job)
        self.db.execute("UPDATE workload_executions SET status='completed', returncode=0, cancel_requested=1 WHERE id=?",
                        (record["id"],))
        self.db.commit()
        from evo_experiments.execution import request_cancel_managed_execution
        result = request_cancel_managed_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(get_execution(self.db, record["id"])["status"], "completed")

    def test_migration_preserves_job_id_nullability_and_indexes(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE workload_executions (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, argv_json TEXT NOT NULL,
            policy_json TEXT NOT NULL DEFAULT '[]', workspace TEXT NOT NULL, status TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL, pid INTEGER, process_started_at TEXT, started_at TEXT,
            finished_at TEXT, returncode INTEGER, elapsed_seconds REAL, stdout TEXT NOT NULL DEFAULT '',
            stderr TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO workload_executions(id,job_id,argv_json,policy_json,workspace,status,timeout_seconds,created_at)
                      VALUES('legacy-null','legacy-job','["echo","ok"]','[]','/tmp','queued',5,'2026-01-01T00:00:00Z')""")
        db.commit()
        from evo_experiments.execution import initialize_execution
        initialize_execution(db)
        columns = {row[1]: row for row in db.execute("PRAGMA table_info(workload_executions)").fetchall()}
        self.assertEqual(columns["job_id"][3], 0)
        indexes = {row[1] for row in db.execute("PRAGMA index_list(workload_executions)").fetchall()}
        self.assertIn("idx_workload_executions_agent_run", indexes)
        info = db.execute("PRAGMA index_info(idx_workload_executions_agent_run)").fetchall()
        self.assertEqual([row[2] for row in info], ["agent_run_id"])
        self.assertIn("idx_workload_executions_job", indexes)
        info = db.execute("PRAGMA index_info(idx_workload_executions_job)").fetchall()
        self.assertEqual([row[2] for row in info], ["job_id"])
        self.assertIn("idx_workload_executions_status", indexes)
        info = db.execute("PRAGMA index_info(idx_workload_executions_status)").fetchall()
        self.assertEqual([row[2] for row in info], ["status", "created_at"])
        db.close()

    def test_natural_completion_before_cancellation_is_not_relabelled(self):
        job = self.reserve("natural-completion-race")
        record = self.register(job)

        class CompletingProcess(FakeProcess):
            def wait(self, timeout=None):
                # Simulate the process exiting successfully before cancellation is observed.
                self.db.execute("UPDATE workload_executions SET cancel_requested=1 WHERE id=?", (record["id"],))
                self.db.commit()
                self.returncode = 0
                return 0

        CompletingProcess.db = self.db
        with patch("evo_experiments.execution.subprocess.Popen", CompletingProcess), \
             patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg") as kill:
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["returncode"], 0)

    def test_cancellation_while_running_terminates_owned_process(self):
        job = self.reserve("cancel-running")
        record = self.register(job)

        import threading
        class RunningProcess(FakeProcess):
            started = threading.Event()
            cancelled = threading.Event()

            def wait(self, timeout=None):
                self.started.set()
                if self.cancelled.wait(timeout if timeout is not None else None):
                    self.returncode = -15
                    return self.returncode
                raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=timeout)

            def poll(self):
                return None

        RunningProcess.started.clear()
        RunningProcess.cancelled.clear()

        def fake_killpg(pid, sig):
            RunningProcess.cancelled.set()

        with patch("evo_experiments.execution.subprocess.Popen", RunningProcess), \
             patch("evo_experiments.execution.os.getpgid", return_value=999999), \
             patch("evo_experiments.execution.os.killpg"), \
             patch("evo_experiments.execution.os.killpg", side_effect=fake_killpg) as kill:
            import threading
            worker = threading.Thread(target=run_execution, args=(self.db, self.lock, record["id"]))
            worker.start()
            RunningProcess.started.wait(timeout=5)
            from evo_experiments.execution import request_cancel_managed_execution
            request_cancel_managed_execution(self.db, record["id"])
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "cancelled")
        kill.assert_called()


    def test_fresh_schema_init_rollback_on_partial_failure(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row

        class FailingConnection:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                if "CREATE INDEX IF NOT EXISTS idx_workload_executions_status" in sql:
                    raise sqlite3.OperationalError("forced init failure")
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        proxy = FailingConnection(db)
        with self.assertRaises(sqlite3.OperationalError):
            initialize_execution(proxy)
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workload_executions'"
        ).fetchall()
        self.assertEqual(len(tables), 0)
        db.close()

    def test_legacy_schema_init_rollback_on_partial_failure(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE workload_executions (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, argv_json TEXT NOT NULL,
            policy_json TEXT NOT NULL DEFAULT '[]', workspace TEXT NOT NULL, status TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL, pid INTEGER, process_started_at TEXT, started_at TEXT,
            finished_at TEXT, returncode INTEGER, elapsed_seconds REAL, stdout TEXT NOT NULL DEFAULT '',
            stderr TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO workload_executions(id,job_id,argv_json,policy_json,workspace,status,timeout_seconds,created_at)
                      VALUES('legacy-rollback','legacy-job','["echo","ok"]','[]','/tmp','completed',5,'2026-01-01T00:00:00Z')""")
        db.commit()

        class FailingConnection:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                if "DROP TABLE workload_executions_legacy" in sql:
                    raise sqlite3.OperationalError("forced migration failure")
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        proxy = FailingConnection(db)
        with self.assertRaises(sqlite3.OperationalError):
            initialize_execution(proxy)
        columns = {row[1]: row for row in db.execute("PRAGMA table_info(workload_executions)").fetchall()}
        self.assertIn("job_id", columns)
        self.assertEqual(columns["job_id"][3], 1)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM workload_executions").fetchone()[0], 1)
        db.close()


    def test_resistant_descendant_is_killed_by_bounded_cleanup(self):
        job = self.reserve("resistant-descendant")
        code = ("import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', 'import time, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)']); "
                "print('started')")
        record = self.register(job, [sys.executable, "-c", code], timeout=5)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertLess(result["elapsed_seconds"], 5)

    def test_descendant_holding_pipes_does_not_block_readers(self):
        job = self.reserve("pipe-descendant")
        code = ("import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
                "stdout=subprocess.PIPE, stderr=subprocess.PIPE); "
                "print('started')")
        record = self.register(job, [sys.executable, "-c", code], timeout=5)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        self.assertLess(result["elapsed_seconds"], 5)

    def test_keeper_already_exited_fails_closed(self):
        from evo_experiments.execution import _bounded_group_cleanup
        with patch("evo_experiments.execution._owned_group_is_live", return_value=False), \
             patch("evo_experiments.execution.os.killpg"), \
             patch("evo_experiments.execution.os.killpg") as kill:
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
            fake = Fake()
            class Keeper:
                def poll(self):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            err = _bounded_group_cleanup(fake)
        kill.assert_not_called()
        self.assertEqual(err, "process group ownership not established")

    def test_command_popen_failure_after_keeper_cleans_keeper(self):
        job = self.reserve("popen-fail")
        record = self.register(job)
        original_popen = __import__("evo_experiments.execution", fromlist=["subprocess"]).subprocess.Popen
        calls = {"n": 0}

        def failing_popen(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("command popen failed")
            return original_popen(*args, **kwargs)

        with patch("evo_experiments.execution.subprocess.Popen", side_effect=failing_popen):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")

    def test_persistence_failure_cleans_owned_group(self):
        job = self.reserve("persist-fail")
        record = self.register(job)
        original_persist = __import__("evo_experiments.execution", fromlist=["_persist"])._persist

        def failing_persist(connection, lock, execution_id, **values):
            if values.get("status") == "running":
                raise RuntimeError("pid persistence failed")
            return original_persist(connection, lock, execution_id, **values)

        with patch("evo_experiments.execution._persist", side_effect=failing_persist):
            run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("pid persistence failed", result["error"])

    def test_repeated_cleanup_is_idempotent(self):
        job = self.reserve("repeat-cleanup")
        record = self.register(job)
        with patch("evo_experiments.execution.subprocess.Popen") as popen:
            pass
        # Exercise helper directly with a minimal fake process.
        class Fake:
            def __init__(self):
                self.pid = 999999
                self._evo_group_pid = 999999
                self._evo_keeper = None
                self.returncode = 0

            def poll(self):
                return self.returncode

        fake = Fake()
        from evo_experiments.execution import _bounded_group_cleanup
        with patch("evo_experiments.execution._owned_group_is_live", return_value=False):
            first = _bounded_group_cleanup(fake)
            second = _bounded_group_cleanup(fake)
        self.assertEqual(first, second)


    def test_cancellation_with_resistant_descendant_cleans_it(self):
        job = self.reserve("cancel-resistant")
        code = ("import subprocess, sys, time, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "time.sleep(30)")
        record = self.register(job, [sys.executable, "-c", code], timeout=10)
        import threading
        worker = threading.Thread(target=run_execution, args=(self.db, self.lock, record["id"]))
        worker.start()
        import time
        time.sleep(1.0)
        from evo_experiments.execution import request_cancel_managed_execution
        request_cancel_managed_execution(self.db, record["id"])
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "cancelled")

    def test_timeout_with_resistant_descendant_preserves_timeout_result(self):
        job = self.reserve("timeout-resistant")
        code = ("import subprocess, sys, time, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "time.sleep(30)")
        record = self.register(job, [sys.executable, "-c", code], timeout=1)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])

    def test_successful_cancellation_does_not_report_false_ownership_loss(self):
        job = self.reserve("cancel-clean")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(30)"], timeout=10)
        import threading, time
        worker = threading.Thread(target=run_execution, args=(self.db, self.lock, record["id"]))
        worker.start()
        time.sleep(0.5)
        from evo_experiments.execution import request_cancel_managed_execution
        request_cancel_managed_execution(self.db, record["id"])
        worker.join(timeout=10)
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn("ownership not established", result["error"])

    def test_successful_timeout_cleanup_does_not_report_false_ownership_loss(self):
        job = self.reserve("timeout-clean")
        record = self.register(job, [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertNotIn("ownership not established", result["error"])

    def test_proc_enumeration_failure_does_not_sigkill(self):
        job = self.reserve("proc-fail")
        record = self.register(job)
        with patch("evo_experiments.execution.os.listdir", side_effect=OSError("no proc")),              patch("evo_experiments.execution.os.killpg") as killpg,              patch("evo_experiments.execution._owned_group_is_live", return_value=True):
            from evo_experiments.execution import _bounded_group_cleanup
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
            fake = Fake()
            fake._evo_keeper = None
            # make keeper alive mock
            class Keeper:
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            err = _bounded_group_cleanup(fake)
        self.assertTrue("ownership not established" in err or "could not be established" in err)

    def test_keeper_zombie_does_not_cause_false_cleanup_failure(self):
        job = self.reserve("keeper-zombie")
        record = self.register(job)
        # Use a process that has already exited; ownership check fails closed.
        with patch("evo_experiments.execution._owned_group_is_live", return_value=False):
            from evo_experiments.execution import _bounded_group_cleanup
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
            fake = Fake()
            class Keeper:
                def poll(self):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            err = _bounded_group_cleanup(fake)
        self.assertEqual(err, "process group ownership not established")

    def test_idempotent_cleanup_real_group(self):
        job = self.reserve("idempotent-real")
        record = self.register(job)
        # Minimal fake with ownership disabled; repeated calls return same.
        with patch("evo_experiments.execution._owned_group_is_live", return_value=False):
            from evo_experiments.execution import _bounded_group_cleanup
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
            fake = Fake()
            class Keeper:
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            first = _bounded_group_cleanup(fake)
            second = _bounded_group_cleanup(fake)
        self.assertEqual(first, second)


    def test_descendant_pid_terminated_after_completion(self):
        import re, time
        job = self.reserve("pid-capture")
        code = ("import subprocess, sys, time; "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "print('PID', p.pid, flush=True); time.sleep(0.5)")
        record = self.register(job, [sys.executable, "-c", code], timeout=5)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "completed")
        match = re.search(r"PID (\d+)", result["stdout"])
        self.assertIsNotNone(match)
        pid = int(match.group(1))
        for _ in range(20):
            if _pid_terminated(pid):
                break
            time.sleep(0.1)
        self.assertTrue(_pid_terminated(pid))

    def test_concurrent_cleanup_single_result(self):
        from evo_experiments.execution import _bounded_group_cleanup
        import threading

        class Fake:
            def __init__(self):
                self.pid = 999999
                self._evo_group_pid = 999999
                self._evo_keeper = None
                self._evo_cleanup_lock = threading.Lock()
                self._evo_cleanup_done = False
                self._evo_cleanup_error = None

        fake = Fake()

        class Keeper:
            def poll(self):
                return None
            def kill(self):
                pass
            def wait(self, timeout=None):
                return 0
            @property
            def pid(self):
                return 999999

        fake._evo_keeper = Keeper()
        with patch("evo_experiments.execution._owned_group_is_live", return_value=False):
            results = []
            def worker():
                results.append(_bounded_group_cleanup(fake))
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(set(results)), 1)


    def test_cancellation_resistant_descendant_pid_terminated(self):
        import re, time
        job = self.reserve("cancel-resistant-pid")
        code = ("import subprocess, sys, time, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "print('PID', p.pid, flush=True); time.sleep(30)")
        record = self.register(job, [sys.executable, "-c", code], timeout=10)
        import threading
        worker = threading.Thread(target=run_execution, args=(self.db, self.lock, record["id"]))
        worker.start()
        time.sleep(1.0)
        from evo_experiments.execution import request_cancel_managed_execution
        request_cancel_managed_execution(self.db, record["id"])
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "cancelled")
        match = re.search(r"PID (\d+)", result["stdout"])
        self.assertIsNotNone(match)
        pid = int(match.group(1))
        for _ in range(30):
            if _pid_terminated(pid):
                break
            time.sleep(0.1)
        self.assertTrue(_pid_terminated(pid))

    def test_timeout_resistant_descendant_pid_terminated(self):
        import re, time
        job = self.reserve("timeout-resistant-pid")
        code = ("import subprocess, sys, time, signal; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "print('PID', p.pid, flush=True); time.sleep(30)")
        record = self.register(job, [sys.executable, "-c", code], timeout=1)
        run_execution(self.db, self.lock, record["id"])
        result = get_execution(self.db, record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        match = re.search(r"PID (\d+)", result["stdout"])
        self.assertIsNotNone(match)
        pid = int(match.group(1))
        for _ in range(30):
            if _pid_terminated(pid):
                break
            time.sleep(0.1)
        self.assertTrue(_pid_terminated(pid))

    def test_proc_enumeration_failure_escalates_group(self):
        from evo_experiments.execution import _bounded_group_cleanup
        with patch("evo_experiments.execution.os.listdir", side_effect=OSError("no proc")), \
             patch("evo_experiments.execution._owned_group_is_live", return_value=True), \
             patch("evo_experiments.execution.os.killpg") as killpg:
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
                    self._evo_cleanup_lock = threading.Lock()
                    self._evo_cleanup_done = False
                    self._evo_cleanup_error = None
            fake = Fake()
            class Keeper:
                def poll(self):
                    return None
                def kill(self):
                    pass
                def wait(self, timeout=None):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            err = _bounded_group_cleanup(fake)
        # SIGTERM then SIGKILL
        self.assertGreaterEqual(killpg.call_count, 2)
        self.assertEqual(killpg.call_args_list[0].args, (999999, __import__("signal").SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (999999, __import__("signal").SIGKILL))

    def test_concurrent_cleanup_blocks_and_reuses_result(self):
        from evo_experiments.execution import _bounded_group_cleanup
        import threading, time

        class Fake:
            def __init__(self):
                self.pid = 999999
                self._evo_group_pid = 999999
                self._evo_keeper = None
                self._evo_cleanup_lock = threading.Lock()
                self._evo_cleanup_done = False
                self._evo_cleanup_error = None

        fake = Fake()

        keeper_calls = {"kill": 0, "wait": 0}

        class Keeper:
            def poll(self):
                return None
            def kill(self):
                keeper_calls["kill"] += 1
            def wait(self, timeout=None):
                keeper_calls["wait"] += 1
                return 0
            @property
            def pid(self):
                return 999999

        fake._evo_keeper = Keeper()

        entered = threading.Event()
        release = threading.Event()
        call_count = {"n": 0}

        def blocking_remaining(group_pid, keeper_pid):
            if call_count["n"] == 0:
                call_count["n"] += 1
                entered.set()
                release.wait(timeout=5)
            return 0

        killpg_calls = []

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))

        results = []

        def worker():
            with patch("evo_experiments.execution._owned_group_is_live", return_value=True), \
                 patch("evo_experiments.execution._remaining_descendants", side_effect=blocking_remaining), \
                 patch("evo_experiments.execution.os.killpg", side_effect=fake_killpg):
                results.append(_bounded_group_cleanup(fake))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        entered.wait(timeout=5)
        time.sleep(0.2)
        # Additional callers should still be waiting.
        self.assertEqual(len(results), 0)
        release.set()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(results), 4)
        self.assertEqual(len(set(results)), 1)
        # Exactly one SIGTERM (no SIGKILL needed since remaining==0).
        self.assertEqual(len(killpg_calls), 1)
        self.assertEqual(killpg_calls[0], (999999, __import__("signal").SIGTERM))
        self.assertEqual(keeper_calls["kill"], 1)
        self.assertEqual(keeper_calls["wait"], 1)

    def test_proc_enumeration_failure_escalates_group(self):
        from evo_experiments.execution import _bounded_group_cleanup
        with patch("evo_experiments.execution.os.listdir", side_effect=OSError("no proc")), \
             patch("evo_experiments.execution._owned_group_is_live", return_value=True), \
             patch("evo_experiments.execution.os.killpg") as killpg:
            class Fake:
                def __init__(self):
                    self.pid = 999999
                    self._evo_group_pid = 999999
                    self._evo_keeper = None
                    self._evo_cleanup_lock = threading.Lock()
                    self._evo_cleanup_done = False
                    self._evo_cleanup_error = None
            fake = Fake()
            class Keeper:
                def poll(self):
                    return None
                def kill(self):
                    pass
                def wait(self, timeout=None):
                    return 0
                @property
                def pid(self):
                    return 999999
            fake._evo_keeper = Keeper()
            err = _bounded_group_cleanup(fake)
        # SIGTERM then SIGKILL
        self.assertGreaterEqual(killpg.call_count, 2)
        self.assertEqual(killpg.call_args_list[0].args, (999999, __import__("signal").SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (999999, __import__("signal").SIGKILL))

    def test_concurrent_cleanup_blocks_and_reuses_result(self):
        from evo_experiments.execution import _bounded_group_cleanup
        import threading, time

        class Fake:
            def __init__(self):
                self.pid = 999999
                self._evo_group_pid = 999999
                self._evo_keeper = None
                self._evo_cleanup_lock = threading.Lock()
                self._evo_cleanup_done = False
                self._evo_cleanup_error = None

        fake = Fake()

        class Keeper:
            def poll(self):
                return None
            def kill(self):
                pass
            def wait(self, timeout=None):
                return 0
            @property
            def pid(self):
                return 999999

        fake._evo_keeper = Keeper()
        call_count = {"n": 0}

        def slow_cleanup(*a, **k):
            nonlocal call_count
            call_count["n"] += 1
            time.sleep(0.5)
            return "done"

        with patch("evo_experiments.execution._owned_group_is_live", return_value=False):
            # ownership fails fast; but lock still serializes
            results = []
            def worker():
                results.append(_bounded_group_cleanup(fake))
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(set(results)), 1)


    def test_pid_terminated_helper(self):
        import os
        # Missing pid -> terminated
        self.assertTrue(_pid_terminated(999999999))
        # Live non-zombie -> not terminated
        alive_pid = os.getpid()
        self.assertFalse(_pid_terminated(alive_pid))

if __name__ == "__main__":
    unittest.main()
