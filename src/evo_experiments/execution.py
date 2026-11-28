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
 created_at TEXT NOT NULL,
 environment_json TEXT NOT NULL DEFAULT '{}',
 resource_limits_json TEXT NOT NULL DEFAULT '{}',
 expected_artifacts_json TEXT NOT NULL DEFAULT '[]',
 artifacts_json TEXT NOT NULL DEFAULT '[]',
 output_limit_bytes INTEGER NOT NULL DEFAULT 20000,
 execution_specification_json TEXT,
 execution_specification_sha256 TEXT
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
            "environment_json": "TEXT NOT NULL DEFAULT '{}'",
            "resource_limits_json": "TEXT NOT NULL DEFAULT '{}'",
            "expected_artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
            "artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
            "output_limit_bytes": "INTEGER NOT NULL DEFAULT 20000",
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
             stdout, stderr, error, created_at, environment_json, resource_limits_json,
             expected_artifacts_json, artifacts_json, output_limit_bytes,
             execution_specification_json, execution_specification_sha256)
            SELECT {col('id')}, {col('job_id')}, NULL, NULL, NULL, NULL, '{{}}', NULL, 0, NULL,
                   {col('argv_json')}, {col('policy_json')}, {col('workspace')}, {col('status')},
                   {col('timeout_seconds')}, {col('pid')}, {col('process_started_at')},
                   {col('started_at')}, {col('finished_at')}, {col('returncode')},
                   {col('elapsed_seconds')}, {col('stdout')}, {col('stderr')}, {col('error')},
                   {col('created_at')}, '{{}}', '{{}}', '[]', '[]', 20000, NULL, NULL
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
            additions = [
                ("environment_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("resource_limits_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("expected_artifacts_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("artifacts_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("output_limit_bytes", "INTEGER NOT NULL DEFAULT 20000"),
                ("execution_specification_json", "TEXT"),
                ("execution_specification_sha256", "TEXT"),
            ]
            for column, definition in additions:
                if column not in columns:
                    connection.execute(f"ALTER TABLE workload_executions ADD COLUMN {column} {definition}")
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
    for json_field, target, default in (
        ("environment_json", "environment_contract", {}),
        ("resource_limits_json", "resource_limits", {}),
        ("expected_artifacts_json", "expected_artifacts", []),
        ("artifacts_json", "artifacts", []),
    ):
        try:
            value = json.loads(item.pop(json_field, None) or ("{}" if default == {} else "[]"))
        except (ValueError, TypeError):
            value = default
        item[target] = value
        item[json_field.replace("_json", "")] = value
    item["output_limit_bytes"] = item.get("output_limit_bytes") or 20000
    item["execution_specification"] = item.get("execution_specification_json")
    item["execution_specification_sha256"] = item.get("execution_specification_sha256")
    # Compatibility aliases.
    item["environment"] = item.get("environment_contract", {})
    item["resource_budget"] = item.get("resource_limits", {})
    item["expected_artifact_paths"] = item.get("expected_artifacts", [])
    item["collected_artifacts"] = item.get("artifacts", [])
    item["specification_digest"] = item.get("execution_specification_sha256")
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

SENSITIVE_ENVIRONMENT_NAMES = {
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS",
}


def _is_sensitive_environment_name(name):
    parts = set(re.split(r"[^A-Z0-9]+", str(name).upper()))
    return bool(parts & SENSITIVE_ENVIRONMENT_NAMES) or ({"API", "KEY"} <= parts) or ({"PRIVATE", "KEY"} <= parts)


def _sanitize_environment_contract(value):
    if value is None:
        return {"inherit_safe_environment": True, "variables": {}}
    if not isinstance(value, dict):
        raise ValueError("environment contract must be a mapping")
    if "variables" in value or "inherit_safe_environment" in value or "inherit" in value:
        inherit = bool(value.get("inherit_safe_environment", value.get("inherit", True)))
        variables = value.get("variables", {})
        if variables is None:
            variables = {}
        if not isinstance(variables, dict):
            raise ValueError("environment contract variables must be a mapping")
    else:
        inherit = True
        variables = value
    sanitized = {}
    for key, env_value in variables.items():
        if not isinstance(key, str) or not key or "\x00" in key or "=" in key:
            raise ValueError("environment variable names must be non-empty strings")
        if not isinstance(env_value, str):
            raise ValueError("environment variable values must be strings")
        if _is_sensitive_environment_name(key):
            raise ValueError(f"refusing to persist sensitive environment variable {key!r}")
        sanitized[key] = env_value
    return {"inherit_safe_environment": bool(inherit), "variables": sanitized}


def _validate_resource_limits(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("resource limits must be a mapping")
    aliases = {
        "cpu_seconds": "cpu_seconds",
        "cpu_time_seconds": "cpu_seconds",
        "memory_bytes": "memory_bytes",
        "memory_limit_bytes": "memory_bytes",
        "address_space_bytes": "memory_bytes",
        "open_files": "open_files",
        "max_open_files": "open_files",
        "processes": "processes",
        "max_processes": "processes",
        "file_size_bytes": "file_size_bytes",
        "max_file_size_bytes": "file_size_bytes",
    }
    result = {}
    for key, raw in value.items():
        canonical = aliases.get(str(key))
        if canonical is None:
            raise ValueError(f"unsupported resource limit {key!r}")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"resource limit {key!r} must be numeric")
        number = int(raw)
        if number < 0:
            raise ValueError(f"resource limit {key!r} must be non-negative")
        result[canonical] = number
    if result and not _resource_limits_supported(result):
        raise ValueError("resource limits are not enforceable on this platform")
    return result


def _resource_limits_supported(limits=None):
    try:
        import resource
    except ImportError:
        return False
    if not hasattr(resource, "setrlimit"):
        return False
    required = {
        "cpu_seconds": "RLIMIT_CPU",
        "memory_bytes": "RLIMIT_AS",
        "open_files": "RLIMIT_NOFILE",
        "processes": "RLIMIT_NPROC",
        "file_size_bytes": "RLIMIT_FSIZE",
    }
    return all(hasattr(resource, required[name]) for name, value in (limits or {}).items() if value > 0)


def _validate_expected_artifacts(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected artifacts must be a list")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("expected artifact paths must be strings")
        if not item or item.startswith("/") or "\\" in item or "\x00" in item:
            raise ValueError("expected artifact path must be a relative POSIX path")
        parts = item.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("expected artifact path must not traverse the workspace")
        if parts and parts[0] == ".git":
            raise ValueError("expected artifact path must not target Git metadata")
        if item not in result:
            result.append(item)
    if len(result) > 100:
        raise ValueError("too many expected artifacts")
    return result


def _safe_relative_artifact_path(value):
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or "\x00" in value:
        return None
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    if parts and parts[0] == ".git":
        return None
    return "/".join(parts)


def _collect_artifacts(workspace, expected_artifacts, max_bytes=10 * 1024 * 1024):
    """Hash expected regular files without following symlinks in any path component."""
    import errno
    import hashlib
    import os
    import stat as stat_module

    collected = []
    total = 0
    dir_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    if (not dir_flag or not nofollow_flag or os.open not in getattr(os, "supports_dir_fd", set())):
        return [
            {"path": str(path), "status": "unsafe", "reason": "safe_open_unavailable"}
            for path in expected_artifacts
        ][:100]

    for relative in expected_artifacts[:100]:
        safe = _safe_relative_artifact_path(relative)
        if safe is None:
            collected.append({"path": str(relative), "status": "unsafe", "reason": "unsafe_path"})
            continue
        parts = safe.split("/")
        directory_fd = None
        file_fd = None
        try:
            directory_fd = os.open(str(workspace), os.O_RDONLY | dir_flag | nofollow_flag)
            for component in parts[:-1]:
                next_fd = os.open(
                    component, os.O_RDONLY | dir_flag | nofollow_flag,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(
                parts[-1], os.O_RDONLY | nofollow_flag | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
            before = os.fstat(file_fd)
            if not stat_module.S_ISREG(before.st_mode):
                collected.append({"path": safe, "status": "unsafe", "reason": "not_regular_file"})
                continue
            if before.st_size > max_bytes or total + before.st_size > max_bytes:
                collected.append({"path": safe, "status": "oversized", "size_bytes": before.st_size})
                continue
            digest = hashlib.sha256()
            read_bytes = 0
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                read_bytes += len(chunk)
                if total + read_bytes > max_bytes:
                    break
                digest.update(chunk)
            after = os.fstat(file_fd)
            signature_before = (
                before.st_dev, before.st_ino, before.st_size, before.st_mode,
                before.st_mtime_ns, before.st_ctime_ns,
            )
            signature_after = (
                after.st_dev, after.st_ino, after.st_size, after.st_mode,
                after.st_mtime_ns, after.st_ctime_ns,
            )
            if read_bytes > max_bytes - total:
                collected.append({"path": safe, "status": "oversized", "size_bytes": read_bytes})
            elif signature_before != signature_after or read_bytes != before.st_size:
                collected.append({"path": safe, "status": "changed", "reason": "file changed during collection"})
            else:
                collected.append({
                    "path": safe, "status": "collected",
                    "size_bytes": read_bytes, "sha256": digest.hexdigest(),
                })
                total += read_bytes
        except FileNotFoundError:
            collected.append({"path": safe, "status": "missing"})
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                collected.append({"path": safe, "status": "unsafe", "reason": "symlink_or_non_directory"})
            else:
                collected.append({"path": safe, "status": "unreadable", "reason": str(exc)[:200]})
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                os.close(directory_fd)
    return collected

def _canonical_execution_specification(argv, workspace, environment_contract, timeout_seconds, output_limit_bytes, resource_limits, expected_artifacts, allowed_commands):
    import hashlib, json as _json
    spec = {
        "argv": list(argv),
        "working_directory": str(workspace),
        "environment_contract": environment_contract,
        "timeout_seconds": int(timeout_seconds),
        "output_limit_bytes": int(output_limit_bytes),
        "resource_limits": resource_limits,
        "expected_artifacts": list(expected_artifacts),
        "effective_command_policy": [list(prefix) for prefix in allowed_commands if prefix],
    }
    text = _json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def register_managed_execution(connection, *, workspace, argv, allowed_commands, timeout_seconds=300,
                                    job_id=None, agent_run_id=None, workspace_id=None, project_id=None,
                                    approval_id=None, approval_evidence=None, source_revision=None,
                                    working_directory=None, environment=None, environment_contract=None,
                                    output_limit_bytes=None, resource_limits=None, resource_budget=None,
                                    expected_artifacts=None, expected_artifact_paths=None):
    if not command_allowed(argv, allowed_commands):
        raise ValueError("Command is not permitted by workspace.allowed_commands")
    timeout = min(max(int(timeout_seconds), 1), MAX_TIMEOUT_SECONDS)
    working_directory = working_directory if working_directory is not None else workspace
    if isinstance(working_directory, (os.PathLike,)):
        working_directory = os.fspath(working_directory)
    if not isinstance(working_directory, str) or not working_directory.strip():
        raise ValueError("working_directory must be a non-empty string")
    working_directory = working_directory.strip()
    if not os.path.isdir(working_directory):
        raise ValueError("working_directory must be an existing directory")
    environment_contract = _sanitize_environment_contract(
        environment_contract if environment_contract is not None else environment)
    resource_limits = _validate_resource_limits(
        resource_limits if resource_limits is not None else resource_budget)
    expected_artifacts = _validate_expected_artifacts(
        expected_artifacts if expected_artifacts is not None else expected_artifact_paths)
    if output_limit_bytes is None:
        output_limit_bytes = OUTPUT_LIMIT
    if isinstance(output_limit_bytes, bool) or not isinstance(output_limit_bytes, int):
        raise ValueError("output_limit_bytes must be an integer")
    if output_limit_bytes < 1 or output_limit_bytes > 100 * 1024 * 1024:
        raise ValueError("output_limit_bytes must be between 1 and 104857600")
    import hashlib, json as _json
    canonical_argv_hash = hashlib.sha256(_json.dumps(list(argv), sort_keys=True).encode("utf-8")).hexdigest()
    canonical_policy = [list(prefix) for prefix in allowed_commands if prefix]
    specification_text, specification_hash = _canonical_execution_specification(
        argv, working_directory, environment_contract, timeout, output_limit_bytes,
        resource_limits, expected_artifacts, allowed_commands)
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
        if "execution_specification_sha256" in evidence and evidence.get("execution_specification_sha256") != specification_hash:
            raise ValueError("Approval evidence must bind the complete execution specification")
        approval_evidence = evidence
    approval_evidence = dict(approval_evidence or {})
    if "argv_sha256" in approval_evidence and approval_evidence["argv_sha256"] != canonical_argv_hash:
        raise ValueError("Approval evidence does not match the requested command")
    if "policy" in approval_evidence and approval_evidence["policy"] != canonical_policy:
        raise ValueError("Approval evidence does not match the effective policy snapshot")
    if "execution_specification_sha256" in approval_evidence and approval_evidence["execution_specification_sha256"] != specification_hash:
        raise ValueError("Approval evidence does not match the complete execution specification")
    if agent_run_id is not None:
        approval_evidence.setdefault("argv_sha256", canonical_argv_hash)
        approval_evidence.setdefault("policy", canonical_policy)
        approval_evidence.setdefault("execution_specification_sha256", specification_hash)
        approval_evidence.setdefault("execution_specification", specification_text)

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
         timeout_seconds,created_at,environment_json,resource_limits_json,expected_artifacts_json,
         artifacts_json,output_limit_bytes,execution_specification_json,execution_specification_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (execution_id, job_id, agent_run_id, workspace_id, project_id, approval_id,
         json.dumps(approval_evidence or {}, ensure_ascii=False, default=str),
         source_revision, 0, created, json.dumps(list(argv)), json.dumps(policy_snapshot),
         str(working_directory), "queued", timeout, created,
         json.dumps(environment_contract, ensure_ascii=False, default=str),
         json.dumps(resource_limits, ensure_ascii=False, default=str),
         json.dumps(expected_artifacts, ensure_ascii=False, default=str),
         "[]", output_limit_bytes, specification_text, specification_hash))
    connection.commit()
    if job_id is not None:
        try:
            start_job(connection, job_id)
        except Exception:
            connection.execute("DELETE FROM workload_executions WHERE id=?", (execution_id,))
            connection.commit()
            raise
    return get_execution(connection, execution_id)

def register_execution(connection, job_id, argv, allowed_commands, workspace, timeout_seconds=300, **kwargs):
    return register_managed_execution(
        connection, job_id=job_id, workspace=workspace, argv=argv,
        allowed_commands=allowed_commands, timeout_seconds=timeout_seconds, **kwargs)

def _safe_environment():
    # Preserve PATH/HOME and ordinary settings while filtering credential-shaped
    # variable names. Avoid broad substring matching (e.g. MONKEY is not a secret).
    sensitive = {"TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS"}
    def is_secret(name):
        parts = set(re.split(r"[^A-Z0-9]+", name.upper()))
        return bool(parts & sensitive) or ({"API", "KEY"} <= parts) or ({"PRIVATE", "KEY"} <= parts)
    return {key: value for key, value in os.environ.items() if not is_secret(key)}

def _environment_for_contract(contract):
    contract = contract or {}
    env = {}
    if contract.get("inherit_safe_environment", True):
        env.update(_safe_environment())
    for key, value in (contract.get("variables") or {}).items():
        if _is_sensitive_environment_name(key):
            raise ValueError(f"refusing to apply sensitive environment variable {key!r}")
        env[str(key)] = str(value)
    return env


def _make_preexec(resource_limits):
    def apply():
        try:
            import resource
        except ImportError as exc:
            raise RuntimeError("resource limits are not enforceable on this platform") from exc
        if "cpu_seconds" in resource_limits and resource_limits["cpu_seconds"] > 0:
            resource.setrlimit(resource.RLIMIT_CPU, (resource_limits["cpu_seconds"], resource_limits["cpu_seconds"]))
        if "memory_bytes" in resource_limits and resource_limits["memory_bytes"] > 0:
            resource.setrlimit(resource.RLIMIT_AS, (resource_limits["memory_bytes"], resource_limits["memory_bytes"]))
        if "open_files" in resource_limits and resource_limits["open_files"] > 0:
            resource.setrlimit(resource.RLIMIT_NOFILE, (resource_limits["open_files"], resource_limits["open_files"]))
        if "processes" in resource_limits and resource_limits["processes"] > 0 and hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (resource_limits["processes"], resource_limits["processes"]))
        if "file_size_bytes" in resource_limits and resource_limits["file_size_bytes"] > 0 and hasattr(resource, "RLIMIT_FSIZE"):
            resource.setrlimit(resource.RLIMIT_FSIZE, (resource_limits["file_size_bytes"], resource_limits["file_size_bytes"]))
    return apply


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
    output_limit = record.get("output_limit_bytes") or OUTPUT_LIMIT
    try:
        output_limit = int(output_limit)
    except (TypeError, ValueError):
        output_limit = OUTPUT_LIMIT
    if output_limit < 1:
        output_limit = OUTPUT_LIMIT
    environment_contract = record.get("environment_contract") or {}
    if not isinstance(environment_contract, dict):
        environment_contract = {}
    resource_limits = record.get("resource_limits") or {}
    if not isinstance(resource_limits, dict):
        resource_limits = {}
    try:
        env = _environment_for_contract(environment_contract)
    except ValueError as exc:
        _persist(connection, lock, execution_id, status="failed", error=str(exc)[:2000], finished_at=_now())
        return
    if resource_limits and not _resource_limits_supported(resource_limits):
        _persist(connection, lock, execution_id, status="failed", error="resource limits are not enforceable on this platform", finished_at=_now())
        return
    preexec = _make_preexec(resource_limits) if resource_limits else None
    working_directory = record.get("workspace") or record.get("working_directory")
    if not working_directory or not os.path.isdir(str(working_directory)):
        _persist(connection, lock, execution_id, status="failed", error="working directory is unavailable", finished_at=_now())
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
            process_group=0, env=env, close_fds=True)
        group_pid = keeper.pid
        process = subprocess.Popen(
            record["argv"], cwd=str(working_directory), shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, close_fds=True, process_group=group_pid,
            env=env, preexec_fn=preexec)
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
                    if len(target) > output_limit:
                        del target[:-output_limit]
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
        artifacts = _collect_artifacts(working_directory, record.get("expected_artifacts") or [], output_limit)
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
                   elapsed_seconds=?,stdout=?,stderr=?,error=?,pid=NULL,artifacts_json=?
                   WHERE id=? AND status NOT IN ('completed','failed','cancelled','interrupted','launch_uncertain')""",
                (outcome, _now(), returncode, elapsed, stdout, stderr, error[:2000],
                 json.dumps(artifacts, ensure_ascii=False, default=str), execution_id))
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
