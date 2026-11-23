"""Allowlisted, user-confirmed subprocess execution for reserved workloads.

Only commands explicitly permitted by workspace.allowed_commands can run. Commands
are argv arrays (never shell strings), run under the configured workspace, and are
owned by the worker that created them. Evo never attaches to or controls unrelated
processes such as an existing inference server.
"""
from datetime import datetime, timezone
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid

from evo_experiments.scheduler import cancel_job, finish_job, get_job, start_job

OUTPUT_LIMIT = 20000
MAX_TIMEOUT_SECONDS = 900

SCHEMA = """
CREATE TABLE IF NOT EXISTS workload_executions (
 id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL UNIQUE,
 argv_json TEXT NOT NULL,
 policy_json TEXT NOT NULL DEFAULT '[]',
 workspace TEXT NOT NULL,
 status TEXT NOT NULL,
 timeout_seconds INTEGER NOT NULL,
 pid INTEGER,
 process_started_at TEXT,
 started_at TEXT,
 finished_at TEXT,
 returncode INTEGER,
 elapsed_seconds REAL,
 stdout TEXT NOT NULL DEFAULT '',
 stderr TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workload_executions_status
 ON workload_executions(status, created_at);
"""

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def initialize_execution(connection):
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(workload_executions)")}
    if "policy_json" not in columns:
        connection.execute(
            "ALTER TABLE workload_executions ADD COLUMN policy_json TEXT NOT NULL DEFAULT '[]'"
        )
    connection.commit()

def command_allowed(argv, allowed_commands):
    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > 128:
        return False
    if any(not isinstance(part, str) or not part or len(part) > 4096 or "\x00" in part for part in argv):
        return False
    return any(tuple(argv[:len(prefix)]) == tuple(prefix) for prefix in allowed_commands if prefix)

def _decode(row):
    item = dict(row)
    try:
        item["argv"] = json.loads(item.pop("argv_json"))
    except (ValueError, TypeError):
        item["argv"] = []
    try:
        item["allowed_commands"] = json.loads(item.pop("policy_json"))
    except (ValueError, TypeError, KeyError):
        item["allowed_commands"] = []
    return item

def list_executions(connection, limit=50):
    rows = connection.execute(
        "SELECT * FROM workload_executions ORDER BY created_at DESC LIMIT ?",
        (min(max(int(limit), 1), 100),)).fetchall()
    return [_decode(row) for row in rows]

def get_execution(connection, execution_id):
    row = connection.execute("SELECT * FROM workload_executions WHERE id=?", (execution_id,)).fetchone()
    return _decode(row) if row else None

def register_execution(connection, job_id, argv, allowed_commands, workspace, timeout_seconds=300):
    if not command_allowed(argv, allowed_commands):
        raise ValueError("Command is not permitted by workspace.allowed_commands")
    timeout = min(max(int(timeout_seconds), 1), MAX_TIMEOUT_SECONDS)
    job = get_job(connection, job_id)
    if job is None:
        raise ValueError("Scheduled job not found")
    if job["status"] != "reserved":
        raise ValueError("Only a reserved job can be executed")
    if connection.execute("SELECT 1 FROM workload_executions WHERE job_id=?", (job_id,)).fetchone():
        raise ValueError("This workload already has an execution record")
    policy_snapshot = [list(prefix) for prefix in allowed_commands if prefix]
    execution_id = uuid.uuid4().hex
    created = _now()
    connection.execute(
        """INSERT INTO workload_executions
        (id,job_id,argv_json,policy_json,workspace,status,timeout_seconds,created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (execution_id, job_id, json.dumps(list(argv)), json.dumps(policy_snapshot),
         str(workspace), "queued", timeout, created))
    connection.commit()
    try:
        start_job(connection, job_id)
    except Exception:
        connection.execute("DELETE FROM workload_executions WHERE id=?", (execution_id,))
        connection.commit()
        raise
    return get_execution(connection, execution_id)

def _safe_environment():
    # Preserve PATH/HOME and ordinary settings while filtering credential-shaped
    # variable names. Avoid broad substring matching (e.g. MONKEY is not a secret).
    sensitive = {"TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS"}
    def is_secret(name):
        parts = set(re.split(r"[^A-Z0-9]+", name.upper()))
        return bool(parts & sensitive) or ({"API", "KEY"} <= parts) or ({"PRIVATE", "KEY"} <= parts)
    return {key: value for key, value in os.environ.items() if not is_secret(key)}

def _persist(connection, lock, execution_id, **values):
    if not values:
        return
    assignments = ", ".join(f"{key}=?" for key in values)
    with lock:
        connection.execute(
            f"UPDATE workload_executions SET {assignments} WHERE id=?",
            [*values.values(), execution_id])
        connection.commit()

def run_execution(connection, lock, execution_id):
    with lock:
        record = get_execution(connection, execution_id)
    if record is None or record["status"] != "queued":
        return
    started = _now()
    begin = time.monotonic()
    process = None
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    readers = []
    launch_intent_persisted = False
    try:
        with lock:
            cursor = connection.execute(
                """UPDATE workload_executions
                   SET status='launching', started_at=?, process_started_at=NULL
                   WHERE id=? AND status='queued'""",
                (started, execution_id))
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError("Execution is no longer queued; launch intent was not persisted")
            connection.commit()
            launch_intent_persisted = True
    except Exception as exc:
        error_text = f"Launch intent could not be persisted: {type(exc).__name__}: {str(exc)[:1900]}"
        with lock:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                current = get_execution(connection, execution_id)
            except Exception:
                # Database unavailable: leave the queued/launching row and running
                # job for startup recovery instead of claiming finalization.
                return
            if current is not None and current["status"] in {"queued", "launching"}:
                try:
                    connection.execute(
                        """UPDATE workload_executions
                           SET status='failed', finished_at=?, error=?, pid=NULL
                           WHERE id=? AND status IN ('queued', 'launching')""",
                        (_now(), error_text, execution_id))
                    job = get_job(connection, record["job_id"])
                    if job and job["status"] == "running":
                        finish_job(connection, record["job_id"], "failed", error_text, commit=False)
                    connection.commit()
                except Exception:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
        return
    try:
        # Recheck the persisted policy snapshot at the actual process boundary.
        # Legacy records without a snapshot decode to an empty policy and fail closed.
        if not command_allowed(record["argv"], record.get("allowed_commands", [])):
            raise ValueError("Command is not permitted by the execution policy snapshot")
        process = subprocess.Popen(
            record["argv"], cwd=record["workspace"], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, close_fds=True, start_new_session=True, env=_safe_environment())
        _persist(connection, lock, execution_id, status="running", pid=process.pid, started_at=started, process_started_at=started)
        def drain(pipe, target):
            try:
                while True:
                    chunk = pipe.read(8192)
                    if not chunk:
                        break
                    target.extend(chunk)
                    if len(target) > OUTPUT_LIMIT:
                        del target[:-OUTPUT_LIMIT]
            finally:
                pipe.close()
        for pipe, target in ((process.stdout, stdout_buffer), (process.stderr, stderr_buffer)):
            thread = threading.Thread(target=drain, args=(pipe, target), daemon=True)
            thread.start()
            readers.append(thread)
        timed_out = False
        try:
            returncode = process.wait(timeout=record["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
        # Commands are bounded jobs, not daemon launchers. Clean up any descendants
        # left in this private process group after the leader exits or times out.
        cleanup_error = ""
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        if timed_out:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        for thread in readers:
            thread.join(timeout=3)
        if any(thread.is_alive() for thread in readers):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                if not cleanup_error:
                    cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            for thread in readers:
                thread.join(timeout=2)
        if process.poll() is None:
            try:
                process.kill()
            except (ProcessLookupError, OSError) as exc:
                if not cleanup_error and not isinstance(exc, ProcessLookupError):
                    cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        returncode = process.returncode
        stdout = bytes(stdout_buffer).decode("utf-8", errors="replace")
        stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
        elapsed = round(time.monotonic() - begin, 3)
        outcome = "failed" if timed_out or returncode != 0 else "completed"
        error = f"Command timed out after {record['timeout_seconds']} seconds" if timed_out else ""
        if cleanup_error:
            error = (error + "; process group cleanup failed: " + cleanup_error).strip("; ").strip()
        with lock:
            connection.execute(
                """UPDATE workload_executions SET status=?,finished_at=?,returncode=?,
                   elapsed_seconds=?,stdout=?,stderr=?,error=?,pid=NULL WHERE id=?""",
                (outcome, _now(), returncode, elapsed, stdout, stderr, error[:2000], execution_id))
            finish_job(connection, record["job_id"], outcome,
                       error or (f"Exit code {returncode}" if returncode else "Exit code 0"),
                       commit=False)
            connection.commit()
    except Exception as exc:
        cleanup_error = ""
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as cleanup_exc:
                cleanup_error = f"{type(cleanup_exc).__name__}: {str(cleanup_exc)[:200]}"
            try:
                process.wait(timeout=3)
            except Exception:
                pass
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as cleanup_exc:
                    if not cleanup_error:
                        cleanup_error = f"{type(cleanup_exc).__name__}: {str(cleanup_exc)[:200]}"
                try:
                    process.wait(timeout=3)
                except Exception:
                    pass
        elapsed = round(time.monotonic() - begin, 3)
        error_text = f"{type(exc).__name__}: {exc}"[:2000]
        if cleanup_error:
            error_text = (error_text + "; process group cleanup failed: " + cleanup_error)[:2000]
        with lock:
            connection.rollback()
            current = get_execution(connection, execution_id)
            if current is not None and current["status"] in {"queued", "launching", "running"}:
                connection.execute(
                    """UPDATE workload_executions SET status='failed',finished_at=?,
                       elapsed_seconds=?,error=?,pid=NULL WHERE id=?""",
                    (_now(), elapsed, error_text, execution_id))
                job = get_job(connection, record["job_id"])
                if job and job["status"] == "running":
                    try:
                        finish_job(connection, record["job_id"], "failed", error_text, commit=False)
                    except Exception:
                        pass
                try:
                    connection.commit()
                except Exception:
                    connection.rollback()

def recover_interrupted_executions(connection):
    """Mark interrupted Evo-owned runs; never signal possibly orphaned processes.

    A row in ``launching`` means Evo requested a subprocess but did not record a
    PID.  The process may or may not exist; Evo neither assumes that it does nor
    terminates it.  The outcome is intentionally ``launch_uncertain``.
    """
    rows = connection.execute(
        "SELECT * FROM workload_executions WHERE status IN ('queued','running','launching')").fetchall()
    recovered = []
    for raw in rows:
        item = _decode(raw)
        if item["status"] == "launching":
            outcome = "launch_uncertain"
            note = ("Evo restarted after requesting this subprocess but before recording its PID. "
                    "The process may or may not be running; Evo did not signal or terminate it. "
                    "Inspect it manually before retrying.")
        elif item["status"] == "running":
            outcome = "interrupted"
            note = ("Evo restarted while this command was active. The recorded PID may still be running; "
                    "Evo did not signal or terminate it. Inspect it manually before retrying.")
        else:
            outcome = "interrupted"
            note = ("Evo restarted before this queued command was launched. No process was started by Evo.")
        try:
            with connection:
                connection.execute(
                    """UPDATE workload_executions SET status=?,finished_at=?,error=?,pid=?
                       WHERE id=?""",
                    (outcome, _now(), note, item.get("pid"), item["id"]))
                job = get_job(connection, item["job_id"])
                if job and job["status"] == "running":
                    finish_job(connection, item["job_id"], "failed", note, commit=False)
                elif job and job["status"] == "reserved":
                    cancel_job(connection, item["job_id"], commit=False)
            recovered.append(item["id"])
        except Exception:
            # Leave the row for the next recovery attempt rather than reporting
            # a partially recovered execution.
            continue
    return recovered
