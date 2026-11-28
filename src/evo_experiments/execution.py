"""Allowlisted, user-confirmed subprocess execution for reserved workloads.

Only commands explicitly permitted by workspace.allowed_commands can run. Commands
are argv arrays (never shell strings), run under the configured workspace, and are
owned by the worker that created them. Evo never attaches to or controls unrelated
processes such as an existing inference server.
"""
from datetime import datetime, timezone
import json
import os
import sys
import re
import signal
import subprocess
import threading
import time
import uuid

from evo_experiments.scheduler import cancel_job, finish_job, get_job, start_job

OUTPUT_LIMIT = 20000
MAX_TIMEOUT_SECONDS = 900

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workload_executions (
 id TEXT PRIMARY KEY,
 job_id TEXT UNIQUE,
 agent_run_id TEXT,
 workspace_id TEXT,
 project_id TEXT,
 approval_id TEXT,
 approval_evidence_json TEXT NOT NULL DEFAULT '{}',
 source_revision TEXT,
 cancel_requested INTEGER NOT NULL DEFAULT 0,
 requested_at TEXT,
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
)
"""
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_workload_executions_status ON workload_executions(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_workload_executions_job ON workload_executions(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_workload_executions_agent_run ON workload_executions(agent_run_id)",
)

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _migrate_execution_schema(connection):
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(workload_executions)").fetchall()}
    managed = not connection.in_transaction
    if managed:
        connection.execute("BEGIN IMMEDIATE")
    try:
        if not columns:
            connection.execute(TABLE_SQL)
            for statement in INDEX_STATEMENTS:
                connection.execute(statement)
            if managed:
                connection.commit()
            return
        required = {
            "job_id": None, "agent_run_id": None, "workspace_id": None, "project_id": None,
            "approval_id": None, "approval_evidence_json": "TEXT NOT NULL DEFAULT '{}'",
            "source_revision": None, "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
            "requested_at": None,
        }
        rebuild = "job_id" in columns and columns["job_id"][3]  # notnull
        if not rebuild:
            for column in required:
                if column not in columns:
                    rebuild = True
                    break
        if not rebuild:
            for statement in INDEX_STATEMENTS:
                connection.execute(statement)
            if managed:
                connection.commit()
            return
        connection.execute("ALTER TABLE workload_executions RENAME TO workload_executions_legacy")
        connection.execute(TABLE_SQL)
        legacy_columns = {row[1] for row in connection.execute("PRAGMA table_info(workload_executions_legacy)").fetchall()}
        def col(name):
            return name if name in legacy_columns else "NULL"
        connection.execute(
            f"""INSERT INTO workload_executions
            (id, job_id, agent_run_id, workspace_id, project_id, approval_id,
             approval_evidence_json, source_revision, cancel_requested, requested_at,
             argv_json, policy_json, workspace, status, timeout_seconds, pid,
             process_started_at, started_at, finished_at, returncode, elapsed_seconds,
             stdout, stderr, error, created_at)
            SELECT {col('id')}, {col('job_id')}, NULL, NULL, NULL, NULL, '{{}}', NULL, 0, NULL,
                   {col('argv_json')}, {col('policy_json')}, {col('workspace')}, {col('status')},
                   {col('timeout_seconds')}, {col('pid')}, {col('process_started_at')},
                   {col('started_at')}, {col('finished_at')}, {col('returncode')},
                   {col('elapsed_seconds')}, {col('stdout')}, {col('stderr')}, {col('error')},
                   {col('created_at')}
            FROM workload_executions_legacy"""
        )
        connection.execute("DROP TABLE workload_executions_legacy")
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
        if managed:
            connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise

def initialize_execution(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(workload_executions)").fetchall()}
    managed = not connection.in_transaction
    if managed:
        connection.execute("BEGIN IMMEDIATE")
    try:
        if not columns:
            connection.execute(TABLE_SQL)
            for statement in INDEX_STATEMENTS:
                connection.execute(statement)
        else:
            if "policy_json" not in columns:
                connection.execute("ALTER TABLE workload_executions ADD COLUMN policy_json TEXT NOT NULL DEFAULT '[]'")
            _migrate_execution_schema(connection)
            for statement in INDEX_STATEMENTS:
                connection.execute(statement)
        if managed:
            connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise

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
    try:
        item["approval_evidence"] = json.loads(item.pop("approval_evidence_json", "{}") or "{}")
    except (ValueError, TypeError):
        item["approval_evidence"] = {}
    return item

def request_cancel_managed_execution(connection, execution_id):
    row = get_execution(connection, execution_id)
    if row is None:
        raise ValueError("Managed execution not found")
    if row["status"] in {"completed", "failed", "cancelled", "interrupted", "launch_uncertain"}:
        return row
    stamp = _now()
    connection.execute(
        "UPDATE workload_executions SET cancel_requested=1 WHERE id=?",
        (execution_id,))
    if row["status"] in {"queued", "launching"}:
        connection.execute(
            """UPDATE workload_executions SET status='cancelled', finished_at=?, error=?
               WHERE id=? AND status IN ('queued','launching')""",
            (stamp, "Cancelled before launch.", execution_id))
        if row.get("job_id"):
            try:
                cancel_job(connection, row["job_id"], commit=False)
            except ValueError:
                pass
    connection.commit()
    return get_execution(connection, execution_id)

def managed_executions_for_parent(connection, agent_run_id):
    rows = connection.execute(
        "SELECT * FROM workload_executions WHERE agent_run_id=? ORDER BY created_at",
        (agent_run_id,)).fetchall()
    return [_decode(row) for row in rows]

def list_executions(connection, limit=50):
    rows = connection.execute(
        "SELECT * FROM workload_executions ORDER BY created_at DESC LIMIT ?",
        (min(max(int(limit), 1), 100),)).fetchall()
    return [_decode(row) for row in rows]

def get_execution(connection, execution_id):
    row = connection.execute("SELECT * FROM workload_executions WHERE id=?", (execution_id,)).fetchone()
    return _decode(row) if row else None

def register_managed_execution(connection, *, workspace, argv, allowed_commands, timeout_seconds=300,
                                    job_id=None, agent_run_id=None, workspace_id=None, project_id=None,
                                    approval_id=None, approval_evidence=None, source_revision=None):
    if not command_allowed(argv, allowed_commands):
        raise ValueError("Command is not permitted by workspace.allowed_commands")
    timeout = min(max(int(timeout_seconds), 1), MAX_TIMEOUT_SECONDS)
    import hashlib, json as _json
    canonical_argv_hash = hashlib.sha256(_json.dumps(list(argv), sort_keys=True).encode("utf-8")).hexdigest()
    canonical_policy = [list(prefix) for prefix in allowed_commands if prefix]
    if agent_run_id is None:
        approval_evidence = dict(approval_evidence or {})
    else:
        evidence = dict(approval_evidence or {})
        if evidence.get("approval") != "approved":
            raise ValueError("Approval evidence must record an approved action")
        if not isinstance(evidence.get("approval_source"), str) or not evidence["approval_source"].strip():
            raise ValueError("Approval evidence must include a meaningful approval source")
        if not isinstance(evidence.get("approved_at"), str) or not evidence["approved_at"].strip():
            raise ValueError("Approval evidence must include an approval timestamp")
        if evidence.get("argv_sha256") != canonical_argv_hash:
            raise ValueError("Approval evidence must bind the exact command argv")
        if evidence.get("policy") != canonical_policy:
            raise ValueError("Approval evidence must bind the exact effective policy snapshot")
        approval_evidence = evidence
    approval_evidence = dict(approval_evidence or {})
    if "argv_sha256" in approval_evidence and approval_evidence["argv_sha256"] != canonical_argv_hash:
        raise ValueError("Approval evidence does not match the requested command")
    if "policy" in approval_evidence and approval_evidence["policy"] != canonical_policy:
        raise ValueError("Approval evidence does not match the effective policy snapshot")
    if job_id is not None:
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
        (id,job_id,agent_run_id,workspace_id,project_id,approval_id,approval_evidence_json,
         source_revision,cancel_requested,requested_at,argv_json,policy_json,workspace,status,
         timeout_seconds,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (execution_id, job_id, agent_run_id, workspace_id, project_id, approval_id,
         json.dumps(approval_evidence or {}, ensure_ascii=False, default=str),
         source_revision, 0, created, json.dumps(list(argv)), json.dumps(policy_snapshot),
         str(workspace), "queued", timeout, created))
    connection.commit()
    if job_id is not None:
        try:
            start_job(connection, job_id)
        except Exception:
            connection.execute("DELETE FROM workload_executions WHERE id=?", (execution_id,))
            connection.commit()
            raise
    return get_execution(connection, execution_id)

def register_execution(connection, job_id, argv, allowed_commands, workspace, timeout_seconds=300):
    return register_managed_execution(
        connection, job_id=job_id, workspace=workspace, argv=argv,
        allowed_commands=allowed_commands, timeout_seconds=timeout_seconds)

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

def _terminate_owned_process(process, send_signal=True):
    if process is None:
        return
    if process.poll() is not None:
        return
    if send_signal and _owned_group_is_live(process):
        try:
            os.killpg(getattr(process, "_evo_group_pid", process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if _owned_group_is_live(process):
            try:
                os.killpg(getattr(process, "_evo_group_pid", process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

def _finish_linked_job(connection, execution, outcome, note):
    job_id = execution.get("job_id")
    if not job_id:
        return
    job = get_job(connection, job_id)
    if not job:
        return
    if job["status"] in {"completed", "failed", "cancelled"}:
        return
    if job["status"] in {"queued", "reserved"}:
        try:
            cancel_job(connection, job_id, commit=False)
        except ValueError:
            pass
        return
    if job["status"] == "running":
        try:
            finish_job(connection, job_id, "failed" if outcome == "cancelled" else outcome, note, commit=False)
        except ValueError:
            pass

def _finalize_cancelled_before_launch(connection, lock, execution_id, record):
    stamp = _now()
    with lock:
        cursor = connection.execute(
            """UPDATE workload_executions
               SET status='cancelled', cancel_requested=1, finished_at=?, error=?
               WHERE id=? AND status IN ('queued','launching')
                 AND status NOT IN ('completed','failed','cancelled','interrupted','launch_uncertain')""",
            (stamp, "Cancelled before launch.", execution_id))
        if cursor.rowcount == 1:
            _finish_linked_job(connection, record, "cancelled", "Cancelled before launch.")
        connection.commit()

def _finalize_cancelled_execution(connection, lock, execution_id, record, started, begin):
    stamp = _now()
    elapsed = round(time.monotonic() - begin, 3)
    with lock:
        cursor = connection.execute(
            """UPDATE workload_executions
               SET status='cancelled', cancel_requested=1, finished_at=?, elapsed_seconds=?, error=?, pid=NULL
               WHERE id=? AND status NOT IN ('completed','failed','cancelled','interrupted','launch_uncertain')""",
            (stamp, elapsed, "Cancelled by user.", execution_id))
        if cursor.rowcount == 1:
            _finish_linked_job(connection, record, "cancelled", "Cancelled by user.")
        connection.commit()

def _process_has_exited(process):
    if process is None:
        return True
    if getattr(process, "returncode", None) is not None:
        return True
    try:
        return process.poll() is not None
    except Exception:
        return False


def _owned_group_is_live(process):
    """Check that the keeper-owned process group is still live."""
    if process is None:
        return False
    group_pid = getattr(process, "_evo_group_pid", process.pid)
    keeper = getattr(process, "_evo_keeper", None)
    if keeper is not None and keeper.poll() is not None:
        return False
    try:
        return os.getpgid(group_pid) == group_pid
    except (ProcessLookupError, OSError):
        return False


def _group_has_members(process):
    """Best-effort check that the process group still has live members."""
    if process is None:
        return False
    try:
        os.killpg(getattr(process, "_evo_group_pid", process.pid), 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _group_member_pids(group_pid, keeper_pid):
    """Return PIDs in the group excluding the keeper."""
    pids = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == keeper_pid:
                continue
            try:
                with open(f"/proc/{pid}/stat", "r") as handle:
                    stat = handle.read()
            except (OSError, ValueError):
                continue
            if ")" not in stat:
                continue
            parts = stat.rsplit(")", 1)[-1].split()
            if len(parts) < 3:
                continue
            try:
                pgrp = int(parts[2])
            except ValueError:
                continue
            if pgrp == group_pid:
                pids.append(pid)
    except OSError:
        return []
    return pids


def _remaining_descendants(group_pid, keeper_pid):
    """Count group members excluding the keeper.

    Returns -1 when group membership cannot be established safely.
    """
    count = 0
    uncertain = False
    try:
        entries = os.listdir("/proc")
    except OSError:
        # Cannot enumerate; do not infer membership from group existence.
        return -1
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == keeper_pid:
            continue
        try:
            with open(f"/proc/{pid}/stat", "r") as handle:
                stat = handle.read()
        except FileNotFoundError:
            # Disappeared during inspection: not a remaining member.
            continue
        except (OSError, ValueError):
            # Unreadable entry: cannot prove absence.
            uncertain = True
            continue
        if ")" not in stat:
            uncertain = True
            continue
        parts = stat.rsplit(")", 1)[-1].split()
        if len(parts) < 3:
            uncertain = True
            continue
        try:
            pgrp = int(parts[2])
        except ValueError:
            uncertain = True
            continue
        if pgrp == group_pid:
            count += 1
    if uncertain:
        return -1
    return count


def _bounded_group_cleanup(process, send_sigterm=True, grace_seconds=1.0):
    """Boundedly clean up an owned process group. Returns an error string."""
    cleanup_error = ""
    if process is None:
        return cleanup_error
    # Serialize the entire cleanup operation.
    lock = getattr(process, "_evo_cleanup_lock", None)
    if lock is None:
        lock = threading.Lock()
        process._evo_cleanup_lock = lock
    with lock:
        if getattr(process, "_evo_cleanup_done", False):
            return getattr(process, "_evo_cleanup_error", "")
        group_pid = getattr(process, "_evo_group_pid", process.pid)
        keeper = getattr(process, "_evo_keeper", None)
        keeper_pid = keeper.pid if keeper is not None else group_pid
        if not _owned_group_is_live(process):
            cleanup_error = "process group ownership not established"
            process._evo_cleanup_done = True
            process._evo_cleanup_error = cleanup_error
            return cleanup_error
        if send_sigterm:
            try:
                os.killpg(group_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as exc:
                cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            remaining = _remaining_descendants(group_pid, keeper_pid)
            if remaining == 0:
                break
            if remaining < 0:
                if not cleanup_error:
                    cleanup_error = "process group membership could not be established"
                break
            time.sleep(0.05)
        remaining = _remaining_descendants(group_pid, keeper_pid)
        if (remaining > 0 or remaining < 0) and _owned_group_is_live(process):
            try:
                os.killpg(group_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                if not cleanup_error:
                    cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                remaining = _remaining_descendants(group_pid, keeper_pid)
                if remaining == 0:
                    break
                if remaining < 0:
                    if not cleanup_error:
                        cleanup_error = "process group membership could not be established"
                    break
                time.sleep(0.05)
        remaining = _remaining_descendants(group_pid, keeper_pid)
        if remaining > 0 or remaining < 0:
            if not cleanup_error:
                cleanup_error = "process group cleanup incomplete"
        # Reap keeper only after descendant cleanup is established.
        if keeper is not None and not cleanup_error and _remaining_descendants(group_pid, keeper_pid) == 0:
            kill = getattr(keeper, "kill", None)
            if callable(kill):
                try:
                    kill()
                except (ProcessLookupError, OSError) as exc:
                    if not cleanup_error:
                        cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            try:
                keeper.wait(timeout=3)
            except subprocess.TimeoutExpired:
                kill = getattr(keeper, "kill", None)
                if callable(kill):
                    try:
                        kill()
                    except (ProcessLookupError, OSError):
                        pass
                try:
                    keeper.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if not cleanup_error:
                        cleanup_error = "keeper cleanup incomplete"
        elif keeper is not None and cleanup_error:
            cleanup_error = cleanup_error + "; keeper preserved for recovery"
        process._evo_cleanup_done = True
        process._evo_cleanup_error = cleanup_error
        return cleanup_error


def _signal_owned_process_group(process):
    """Signal the owned process group once. Returns True if a signal was sent."""
    if not _owned_group_is_live(process):
        return False
    group_pid = getattr(process, "_evo_group_pid", process.pid)
    try:
        os.killpg(group_pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, OSError):
        return False


def _cleanup_keeper(process=None, keeper=None):
    if keeper is None and process is not None:
        keeper = getattr(process, "_evo_keeper", None)
    if keeper is None:
        return ""
    cleanup_error = ""
    terminate = getattr(keeper, "terminate", None)
    if callable(terminate):
        try:
            terminate()
        except (ProcessLookupError, OSError) as exc:
            cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    else:
        kill = getattr(keeper, "kill", None)
        if callable(kill):
            try:
                kill()
            except (ProcessLookupError, OSError) as exc:
                cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    try:
        keeper.wait(timeout=3)
    except subprocess.TimeoutExpired:
        kill = getattr(keeper, "kill", None)
        if callable(kill):
            try:
                kill()
            except (ProcessLookupError, OSError) as exc:
                if not cleanup_error:
                    cleanup_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            keeper.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if not cleanup_error:
                cleanup_error = "keeper cleanup incomplete"
    return cleanup_error


def run_execution(connection, lock, execution_id):
    with lock:
        record = get_execution(connection, execution_id)
    if record is None or record["status"] != "queued":
        return
    if record.get("cancel_requested"):
        _finalize_cancelled_before_launch(connection, lock, execution_id, record)
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
    keeper = None
    try:
        with lock:
            current = get_execution(connection, execution_id)
        if current is not None and current.get("cancel_requested"):
            _finalize_cancelled_before_launch(connection, lock, execution_id, current)
            return
        # Recheck the persisted policy snapshot at the actual process boundary.
        # Legacy records without a snapshot decode to an empty policy and fail closed.
        if not command_allowed(record["argv"], record.get("allowed_commands", [])):
            raise ValueError("Command is not permitted by the execution policy snapshot")
        # A long-lived keeper owns the process group so ownership can still be
        # established after the command leader exits.
        keeper = subprocess.Popen(
            [sys.executable, "-c",
             "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(1000000)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            process_group=0, env=_safe_environment(), close_fds=True)
        group_pid = keeper.pid
        process = subprocess.Popen(
            record["argv"], cwd=record["workspace"], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, close_fds=True, process_group=group_pid,
            env=_safe_environment())
        process._evo_group_pid = group_pid
        process._evo_keeper = keeper
        process._evo_cleanup_lock = threading.Lock()
        process._evo_cleanup_done = False
        process._evo_cleanup_error = None
        _persist(connection, lock, execution_id, status="running", pid=process.pid, started_at=started, process_started_at=started)
        with lock:
            current = get_execution(connection, execution_id)
        if current is not None and current.get("cancel_requested"):
            _terminate_owned_process(process, send_signal=True)
            _finalize_cancelled_execution(connection, lock, execution_id, current, started, begin)
            return
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

        # Synchronized process supervisor.  A single lock arbitrates natural
        # completion, cancellation, and timeout.  Signalling happens while the
        # lock is held so a completion observation cannot be established in the
        # gap between the decision and the signal.
        supervisor_lock = threading.Lock()
        state = {"value": "running"}  # running, cancelling, cancelled, timed_out
        process_exited = threading.Event()
        cancel_signalled = threading.Event()
        cancelled_outcome = {"value": False}
        timed_out_outcome = {"value": False}

        def _cancel_watcher():
            while True:
                # Periodic wake-up; also returns promptly when process exits.
                process_exited.wait(0.05)
                if process_exited.is_set():
                    return
                try:
                    with lock:
                        current = get_execution(connection, execution_id)
                except Exception:
                    current = None
                if current is None or not current.get("cancel_requested"):
                    continue
                with supervisor_lock:
                    if process_exited.is_set():
                        return
                    if state["value"] in ("cancelled", "cancelling", "timed_out"):
                        return
                    if not _owned_group_is_live(process):
                        # Process already gone; do not signal a stale group.
                        process_exited.set()
                        return
                    state["value"] = "cancelling"
                    # Decision and signalling are committed atomically while the
                    # lock is held, so natural completion cannot win in between.
                    signalled = _signal_owned_process_group(process)
                    if signalled:
                        cancel_signalled.set()
                        cancelled_outcome["value"] = True
                    # Bounded cleanup of resistant descendants.
                    cleanup_error_local = _bounded_group_cleanup(process, send_sigterm=False, grace_seconds=1.0)
                    # Preserve the watcher result on the process for the main path.
                    process._evo_cleanup_error = cleanup_error_local
                    process_exited.set()
                    state["value"] = "cancelled" if cancelled_outcome["value"] else state["value"]

        watcher = threading.Thread(target=_cancel_watcher, daemon=True)
        watcher.start()

        timeout_occurred = False
        try:
            returncode = process.wait(timeout=record["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timeout_occurred = True
            returncode = None

        with supervisor_lock:
            process_exited.set()
            if timeout_occurred:
                if state["value"] not in ("cancelling", "cancelled") and not cancel_signalled.is_set():
                    state["value"] = "timed_out"
                    timed_out_outcome["value"] = True
                else:
                    # Cancellation wins the race.
                    cancelled_outcome["value"] = True
                    state["value"] = "cancelled"
            else:
                if state["value"] == "cancelling":
                    cancelled_outcome["value"] = True
                    state["value"] = "cancelled"

        # Terminate only if timeout won and cancellation did not.
        if timed_out_outcome["value"] and not cancelled_outcome["value"]:
            cleanup_error = _bounded_group_cleanup(process, send_sigterm=True, grace_seconds=1.0)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            returncode = process.returncode

        watcher.join(timeout=1)

        # Bounded descendant cleanup; separate from the command outcome.
        cleanup_error = _bounded_group_cleanup(process, send_sigterm=True, grace_seconds=1.0)
        for thread in readers:
            thread.join(timeout=3)
        if any(thread.is_alive() for thread in readers):
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
        if cancelled_outcome["value"] and (returncode is None or (isinstance(returncode, int) and returncode < 0)):
            outcome = "cancelled"
        else:
            outcome = "failed" if timed_out_outcome["value"] or returncode != 0 else "completed"
        error = f"Command timed out after {record['timeout_seconds']} seconds" if timed_out_outcome["value"] else ""
        if cleanup_error:
            error = (error + "; process group cleanup failed: " + cleanup_error).strip("; ").strip()
        with lock:
            cursor = connection.execute(
                """UPDATE workload_executions SET status=?,finished_at=?,returncode=?,
                   elapsed_seconds=?,stdout=?,stderr=?,error=?,pid=NULL
                   WHERE id=? AND status NOT IN ('completed','failed','cancelled','interrupted','launch_uncertain')""",
                (outcome, _now(), returncode, elapsed, stdout, stderr, error[:2000], execution_id))
            if cursor.rowcount == 1 and record.get("job_id"):
                try:
                    if outcome == "cancelled":
                        finish_job(connection, record["job_id"], "failed",
                                   error or "Cancelled by user", commit=False)
                    else:
                        finish_job(connection, record["job_id"], outcome,
                                   error or (f"Exit code {returncode}" if returncode else "Exit code 0"),
                                   commit=False)
                except ValueError:
                    pass
            connection.commit()
    except Exception as exc:
        cleanup_error = ""
        if process is not None:
            cleanup_error = _bounded_group_cleanup(process, send_sigterm=True, grace_seconds=1.0)
            try:
                process.wait(timeout=3)
            except Exception:
                pass
        elif keeper is not None:
            cleanup_error = _cleanup_keeper(keeper=keeper)
            keeper = None
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
                if record.get("job_id") and job and job["status"] == "running":
                    try:
                        finish_job(connection, record["job_id"], "failed", error_text, commit=False)
                    except Exception:
                        pass
                try:
                    connection.commit()
                except Exception:
                    connection.rollback()



    finally:
        if process is not None:
            _bounded_group_cleanup(process, send_sigterm=True, grace_seconds=1.0)
        elif keeper is not None:
            _cleanup_keeper(keeper=keeper)




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
