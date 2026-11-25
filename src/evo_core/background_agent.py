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
      project_id TEXT,
      workspace_id TEXT,
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
    existing = {row[1] for row in connection.execute("PRAGMA table_info(background_agent_tasks)").fetchall()}
    for column in ("project_id", "workspace_id"):
        if column not in existing:
            connection.execute(f"ALTER TABLE background_agent_tasks ADD COLUMN {column} TEXT")
    # Backfill scope for tasks created by earlier versions. Missing or malformed
    # legacy metadata remains explicitly unscoped rather than being guessed.
    rows = connection.execute(
        """SELECT task.run_id, run.metadata_json
           FROM background_agent_tasks AS task
           JOIN agent_runs AS run ON run.id=task.run_id
           WHERE task.project_id IS NULL AND task.workspace_id IS NULL"""
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row[1] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        project_id = metadata.get("project_id")
        workspace_id = metadata.get("workspace_id")
        if (
            isinstance(project_id, str) and project_id.strip()
            and (workspace_id is None or isinstance(workspace_id, str) and workspace_id.strip())
        ):
            connection.execute(
                "UPDATE background_agent_tasks SET project_id=?,workspace_id=? WHERE run_id=?",
                (project_id.strip(), workspace_id.strip() if isinstance(workspace_id, str) else None, row[0]),
            )
    connection.commit()

def _run_scope(connection, run_id, *, tolerate_malformed_metadata=False):
    row = connection.execute(
        "SELECT metadata_json FROM agent_runs WHERE id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Agent run not found")
    try:
        metadata = json.loads(row[0] or "{}")
    except (TypeError, ValueError) as exc:
        if tolerate_malformed_metadata:
            return None, None
        raise ValueError("Agent run scope metadata is malformed") from exc
    if not isinstance(metadata, dict):
        if tolerate_malformed_metadata:
            return None, None
        raise ValueError("Agent run scope metadata must be an object")
    project_id = metadata.get("project_id")
    workspace_id = metadata.get("workspace_id")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise ValueError("Agent run project_id metadata is invalid")
    if workspace_id is not None and (not isinstance(workspace_id, str) or not workspace_id.strip()):
        raise ValueError("Agent run workspace_id metadata is invalid")
    if workspace_id is not None and project_id is None:
        raise ValueError("Agent run workspace_id requires project_id")
    return (project_id.strip() if isinstance(project_id, str) else None,
            workspace_id.strip() if isinstance(workspace_id, str) else None)

def create(connection, run_id):
    stamp = now()
    project_id, workspace_id = _run_scope(
        connection, run_id, tolerate_malformed_metadata=True
    )
    connection.execute(
        """INSERT INTO background_agent_tasks
           (run_id,status,project_id,workspace_id,created_at,updated_at)
           VALUES(?,?,?,?,?,?)""",
        (run_id, "queued", project_id, workspace_id, stamp, stamp))
    _event(connection, run_id, "queued", {
        "project_id": project_id, "workspace_id": workspace_id
    })
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

def finalize(connection, run_id, outcome, payload=None, commit=True):
    """Record one terminal outcome; never overwrite an existing terminal state.

    Returns True only when this call performed the transition. A repeat of the
    same outcome, or a competing terminal outcome, returns False and leaves the
    existing record untouched so its evidence survives.
    """
    if outcome not in TERMINAL:
        raise ValueError("Invalid terminal background task status")
    row = get(connection, run_id)
    if row is None:
        raise ValueError("Background task not found")
    if row["status"] in TERMINAL:
        return False
    cursor = connection.execute(
        """UPDATE background_agent_tasks SET status=?,updated_at=?
           WHERE run_id=? AND status NOT IN ('completed','failed','cancelled','interrupted')""",
        (outcome, now(), run_id))
    if cursor.rowcount != 1:
        if commit:
            connection.commit()
        return False
    _event(connection, run_id, outcome, payload or {})
    if commit:
        connection.commit()
    return True

def request_cancel(connection, run_id):
    stamp = now()
    with connection:
        row = get(connection, run_id)
        if row is None:
            raise ValueError("Background task not found")
        if row["status"] in TERMINAL:
            return False
        if row["status"] == "cancel_requested" or row["cancel_requested"]:
            # Repeated requests are idempotent: do not append another event.
            return True
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


def reconstruct_terminal(connection, run_id, outcome, *, decided_at=None,
                         source="lifecycle", reason=""):
    """Reconstruct a missing task from an authoritative terminal decision.

    This does not represent a worker launch or fabricate prior task history.
    It creates only the terminal record and an explicit reconstruction event.
    """
    if outcome not in TERMINAL:
        raise ValueError("Invalid terminal background task status")

    stamp = decided_at or now()
    project_id, workspace_id = _run_scope(connection, run_id)
    cursor = connection.execute(
        """INSERT OR IGNORE INTO background_agent_tasks
           (run_id,status,cancel_requested,worker_token,project_id,workspace_id,created_at,updated_at)
           VALUES(?,?,0,NULL,?,?,?,?)""",
        (run_id, outcome, project_id, workspace_id, stamp, stamp),
    )
    created = cursor.rowcount == 1
    if created:
        _event(connection, run_id, "reconstructed_from_finalization", {
            "outcome": outcome,
            "source": str(source)[:200],
            "reason": str(reason)[:1000],
            "worker_started": False,
            "execution_replayed": False,
        })
        connection.commit()
    return created
