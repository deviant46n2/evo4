"""Persistent, reservation-based workload scheduler.

The scheduler admits and reserves work; it never launches, kills, or reconfigures
processes. A caller remains responsible for starting a reserved workload and
reporting its completion.
"""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from .intelligence import assess_workload

LEASE_SECONDS = 300
FINAL_STATES = {"completed", "failed", "cancelled"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS workload_jobs (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT 'background',
 status TEXT NOT NULL DEFAULT 'queued',
 priority INTEGER NOT NULL DEFAULT 10,
 gpu_heavy INTEGER,
 estimated_vram_mib REAL,
 estimated_ram_mib REAL,
 decision_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 reserved_at TEXT,
 lease_expires_at TEXT,
 started_at TEXT,
 finished_at TEXT,
 outcome_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_workload_jobs_queue
 ON workload_jobs(status, priority DESC, created_at ASC);
"""

def _now():
    return datetime.now(timezone.utc)

def _stamp(value=None):
    return (value or _now()).isoformat(timespec="seconds")

def initialize_scheduler(connection):
    connection.executescript(SCHEMA)
    connection.commit()

def create_job(connection, payload, now=None):
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ValueError("Job name must contain 1-120 characters")
    description = str(payload.get("description", ""))[:2000]
    kind = str(payload.get("kind", "background")).strip().lower()
    if kind not in {"background", "benchmark", "research", "agent", "maintenance", "cpu"}:
        raise ValueError("Unsupported workload kind")
    priority = payload.get("priority", 10)
    if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 100:
        raise ValueError("priority must be an integer from 1 to 100")
    gpu_heavy = payload.get("gpu_heavy")
    if kind == "cpu" and gpu_heavy is None:
        gpu_heavy = False
    if gpu_heavy is not None and not isinstance(gpu_heavy, bool):
        raise ValueError("gpu_heavy must be true, false, or null")
    values = {}
    for key in ("estimated_vram_mib", "estimated_ram_mib"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > 1000000):
            raise ValueError(key + " must be between 0 and 1000000 MiB")
        values[key] = float(value) if value is not None else None
    now_text = _stamp(now)
    job_id = uuid.uuid4().hex
    connection.execute(
        """INSERT INTO workload_jobs
        (id,name,description,kind,status,priority,gpu_heavy,estimated_vram_mib,
         estimated_ram_mib,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, name, description, kind, "queued", priority,
         None if gpu_heavy is None else int(gpu_heavy),
         values["estimated_vram_mib"], values["estimated_ram_mib"], now_text, now_text))
    connection.commit()
    return get_job(connection, job_id)

def _decode(row):
    item = dict(row)
    item["gpu_heavy"] = None if item["gpu_heavy"] is None else bool(item["gpu_heavy"])
    try:
        item["last_decision"] = json.loads(item.pop("decision_json") or "{}")
    except (ValueError, TypeError):
        item["last_decision"] = {}
    return item

def get_job(connection, job_id):
    row = connection.execute("SELECT * FROM workload_jobs WHERE id=?", (job_id,)).fetchone()
    return _decode(row) if row else None

def list_jobs(connection, limit=100):
    bounded = min(max(int(limit), 1), 200)
    rows = connection.execute(
        """SELECT * FROM workload_jobs
        ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'reserved' THEN 1
          WHEN 'queued' THEN 2 ELSE 3 END, priority DESC, created_at ASC LIMIT ?""",
        (bounded,)).fetchall()
    counts = {row["status"]: row["n"] for row in connection.execute(
        "SELECT status,COUNT(*) AS n FROM workload_jobs GROUP BY status")}
    return {"jobs": [_decode(row) for row in rows], "counts": counts,
            "lease_seconds": LEASE_SECONDS,
            "process_control": False}

def _expire_reservations(connection, now_text):
    rows = connection.execute(
        "SELECT id FROM workload_jobs WHERE status='reserved' AND lease_expires_at<=?",
        (now_text,)).fetchall()
    for row in rows:
        connection.execute(
            """UPDATE workload_jobs SET status='queued',reserved_at=NULL,lease_expires_at=NULL,
            updated_at=?,decision_json=? WHERE id=? AND status='reserved'""",
            (now_text, json.dumps({"decision":"expired","reasons":["Reservation lease expired; job returned to queue."]}), row["id"]))
    return len(rows)

def dispatch_jobs(connection, sample, limit=5, now=None):
    """Reserve the highest-priority queued jobs that fit current headroom."""
    bounded = min(max(int(limit), 1), 20)
    now_dt = now or _now()
    now_text = _stamp(now_dt)
    expires = _stamp(now_dt + timedelta(seconds=LEASE_SECONDS))
    connection.execute("BEGIN IMMEDIATE")
    try:
        expired = _expire_reservations(connection, now_text)
        reserved = connection.execute(
            """SELECT COALESCE(SUM(estimated_vram_mib),0) AS vram,
                      COALESCE(SUM(estimated_ram_mib),0) AS ram
               FROM workload_jobs WHERE status='reserved'""").fetchone()
        total = sample.get("gpu_memory_total_mib")
        used = sample.get("gpu_memory_used_mib")
        effective = dict(sample)
        if isinstance(total, (int,float)) and isinstance(used, (int,float)):
            effective["gpu_memory_used_mib"] = min(total, used + reserved["vram"])
        if isinstance(sample.get("ram_available_bytes"), (int,float)):
            effective["ram_available_bytes"] = max(
                0, sample["ram_available_bytes"] - reserved["ram"] * 1048576)
        queued = connection.execute(
            """SELECT * FROM workload_jobs WHERE status='queued'
               ORDER BY priority DESC,created_at ASC LIMIT ?""", (bounded,)).fetchall()
        decisions = []
        for row in queued:
            workload = {"kind":row["kind"], "gpu_heavy":None if row["gpu_heavy"] is None else bool(row["gpu_heavy"]),
                        "estimated_vram_mib":row["estimated_vram_mib"],
                        "estimated_ram_mib":row["estimated_ram_mib"]}
            decision = assess_workload(effective, workload)
            if decision["decision"] == "allow":
                connection.execute(
                    """UPDATE workload_jobs SET status='reserved',reserved_at=?,lease_expires_at=?,
                       updated_at=?,decision_json=? WHERE id=? AND status='queued'""",
                    (now_text, expires, now_text, json.dumps(decision), row["id"]))
                decisions.append({"id":row["id"],"decision":"reserved","reasons":decision["reasons"]})
                if isinstance(total,(int,float)) and isinstance(used,(int,float)) and workload["gpu_heavy"] is not False:
                    effective["gpu_memory_used_mib"] += workload["estimated_vram_mib"] or 0
                if isinstance(effective.get("ram_available_bytes"),(int,float)):
                    effective["ram_available_bytes"] = max(0,effective["ram_available_bytes"] - (workload["estimated_ram_mib"] or 0)*1048576)
            else:
                connection.execute(
                    "UPDATE workload_jobs SET updated_at=?,decision_json=? WHERE id=? AND status='queued'",
                    (now_text,json.dumps(decision),row["id"]))
                decisions.append({"id":row["id"],"decision":decision["decision"],"reasons":decision["reasons"]})
        connection.commit()
        return {"decisions":decisions,"expired_reservations":expired,
                "jobs":list_jobs(connection)["jobs"]}
    except Exception:
        connection.rollback()
        raise

def start_job(connection, job_id, now=None):
    now_text = _stamp(now)
    connection.execute("BEGIN IMMEDIATE")
    try:
        _expire_reservations(connection, now_text)
        cur = connection.execute(
            """UPDATE workload_jobs SET status='running',started_at=?,updated_at=?,
               lease_expires_at=NULL WHERE id=? AND status='reserved' AND lease_expires_at>?""",
            (now_text,now_text,job_id,now_text))
        if cur.rowcount != 1:
            connection.commit()
            raise ValueError("Job is not currently reserved; refresh the queue before starting it")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return get_job(connection,job_id)

def finish_job(connection, job_id, outcome, note="", now=None):
    if outcome not in {"completed","failed"}:
        raise ValueError("Running jobs can only be marked completed or failed; Evo does not stop processes")
    now_text = _stamp(now)
    try:
        cur = connection.execute(
            """UPDATE workload_jobs SET status=?,finished_at=?,updated_at=?,outcome_note=?
               WHERE id=? AND status='running'""",
            (outcome,now_text,now_text,str(note)[:2000],job_id))
        if cur.rowcount != 1:
            connection.rollback()
            raise ValueError("Only a running job can be finished")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return get_job(connection,job_id)

def cancel_job(connection, job_id, now=None):
    now_text = _stamp(now)
    try:
        cur = connection.execute(
            """UPDATE workload_jobs SET status='cancelled',finished_at=?,updated_at=?,
               lease_expires_at=NULL,outcome_note='Cancelled before start; no process action taken.'
               WHERE id=? AND status IN ('queued','reserved')""",
            (now_text,now_text,job_id))
        if cur.rowcount != 1:
            connection.rollback()
            raise ValueError("Only queued or reserved jobs can be cancelled; running processes are never stopped")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return get_job(connection,job_id)
