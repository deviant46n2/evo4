"""Durable lifecycle ledger for background coding-agent runs.

The existing agent/tool-event tables remain the source of detailed tool history.
This module adds atomic claims, explicit task state, and append-only lifecycle events.
"""
from datetime import datetime, timezone
import json
import sqlite3

ACTIVE = {"queued", "running", "awaiting_approval", "cancel_requested"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}

def now():
    return datetime.now(timezone.utc).isoformat()

def initialize(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS background_agent_tasks (
      run_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
      status TEXT NOT NULL,
      cancel_requested INTEGER NOT NULL DEFAULT 0,
      worker_token TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_background_tasks_status
      ON background_agent_tasks(status, created_at);
    CREATE TABLE IF NOT EXISTS background_agent_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL REFERENCES background_agent_tasks(run_id) ON DELETE CASCADE,
      event_type TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_background_events_run
      ON background_agent_events(run_id,id);
    """)
    connection.commit()

def create(connection, run_id):
    stamp = now()
    connection.execute(
        "INSERT INTO background_agent_tasks(run_id,status,created_at,updated_at) VALUES(?,?,?,?)",
        (run_id, "queued", stamp, stamp))
    _event(connection, run_id, "queued", {})
    connection.commit()
    return get(connection, run_id)

def _event(connection, run_id, event_type, payload):
    connection.execute(
        "INSERT INTO background_agent_events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
        (run_id, event_type, json.dumps(payload, ensure_ascii=False, default=str), now()))

def event(connection, run_id, event_type, payload=None):
    with connection:
        if not connection.execute("SELECT 1 FROM background_agent_tasks WHERE run_id=?", (run_id,)).fetchone():
            raise ValueError("Background task not found")
        _event(connection, run_id, event_type, payload or {})

def get(connection, run_id):
    row = connection.execute("SELECT * FROM background_agent_tasks WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None

def list_tasks(connection, limit=100):
    rows = connection.execute(
        "SELECT * FROM background_agent_tasks ORDER BY created_at DESC LIMIT ?",
        (max(1, min(int(limit), 200)),)).fetchall()
    return [dict(row) for row in rows]

def claim(connection, run_id, worker_token):
    """Exactly one worker can claim a queued task, even under concurrent requests."""
    stamp = now()
    with connection:
        cursor = connection.execute(
            """UPDATE background_agent_tasks SET status='running',worker_token=?,updated_at=?
               WHERE run_id=? AND status='queued' AND cancel_requested=0""",
            (worker_token, stamp, run_id))
        if cursor.rowcount != 1:
            return False
        _event(connection, run_id, "started", {"worker_token": worker_token})
    return True

def transition(connection, run_id, status, payload=None):
    if status not in ACTIVE | TERMINAL:
        raise ValueError("Invalid background task status")
    stamp = now()
    with connection:
        row = get(connection, run_id)
        if row is None:
            raise ValueError("Background task not found")
        if row["status"] in TERMINAL:
            return False
        connection.execute(
            "UPDATE background_agent_tasks SET status=?,updated_at=? WHERE run_id=?",
            (status, stamp, run_id))
        _event(connection, run_id, status, payload or {})
    return True

def request_cancel(connection, run_id):
    stamp = now()
    with connection:
        row = get(connection, run_id)
        if row is None:
            raise ValueError("Background task not found")
        if row["status"] in TERMINAL:
            return False
        connection.execute(
            """UPDATE background_agent_tasks SET cancel_requested=1,status='cancel_requested',
               updated_at=? WHERE run_id=?""", (stamp, run_id))
        _event(connection, run_id, "cancel_requested", {})
    return True

def is_cancelled(connection, run_id):
    row = connection.execute(
        "SELECT cancel_requested FROM background_agent_tasks WHERE run_id=?", (run_id,)).fetchone()
    return bool(row and row["cancel_requested"])

def events(connection, run_id, after_id=0, limit=200):
    rows = connection.execute(
        """SELECT id,event_type,payload_json,created_at FROM background_agent_events
           WHERE run_id=? AND id>? ORDER BY id LIMIT ?""",
        (run_id, max(0, int(after_id)), max(1, min(int(limit), 500)))).fetchall()
    return [{"id": r["id"], "type": r["event_type"],
             "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]}
            for r in rows]

def recover(connection):
    """A process restart cannot safely resume an in-flight provider/tool call."""
    rows = connection.execute(
        "SELECT run_id,status FROM background_agent_tasks WHERE status IN ('queued','running','awaiting_approval','cancel_requested')"
    ).fetchall()
    recovered = []
    with connection:
        for row in rows:
            connection.execute(
                "UPDATE background_agent_tasks SET status='interrupted',updated_at=? WHERE run_id=?",
                (now(), row["run_id"]))
            _event(connection, row["run_id"], "interrupted",
                   {"previous_status": row["status"], "resume_safe": False})
            recovered.append(row["run_id"])
    return recovered
