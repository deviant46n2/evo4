"""Persistent, approval-first agent plans with auditable step state.

Plans are proposals until explicitly approved. Steps execute sequentially; each step
still uses the existing approval-gated CodingAgent tool boundary.
"""
from datetime import datetime, timezone
import json
import sqlite3
import uuid

PLAN_STATES = {"proposed", "approved", "executing", "completed", "failed", "cancelled", "interrupted"}
STEP_STATES = {"pending", "running", "completed", "failed", "skipped", "interrupted"}

def _now():
    return datetime.now(timezone.utc).isoformat()

def initialize(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS agent_plans (
      id TEXT PRIMARY KEY, request TEXT NOT NULL, workspace TEXT NOT NULL,
      title TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, approved_at TEXT,
      run_id TEXT, error TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_agent_plans_status ON agent_plans(status,created_at);
    CREATE TABLE IF NOT EXISTS agent_plan_steps (
      id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES agent_plans(id) ON DELETE CASCADE,
      position INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
      expected_outcome TEXT NOT NULL, verification TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '',
      started_at TEXT, finished_at TEXT, UNIQUE(plan_id,position)
    );
    CREATE TABLE IF NOT EXISTS agent_plan_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL REFERENCES agent_plans(id) ON DELETE CASCADE,
      step_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_agent_plan_events ON agent_plan_events(plan_id,id);
    """)
    connection.commit()

def _event(connection, plan_id, event_type, payload=None, step_id=None):
    connection.execute(
        "INSERT INTO agent_plan_events(plan_id,step_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
        (plan_id, step_id, event_type, json.dumps(payload or {}, ensure_ascii=False, default=str), _now()))

def create_plan(connection, request, workspace, proposal):
    if not isinstance(proposal, dict):
        raise ValueError("Plan proposal must be an object")
    raw_title, raw_summary = proposal.get("title"), proposal.get("summary")
    if not isinstance(raw_title, str) or not isinstance(raw_summary, str):
        raise ValueError("Plan title and summary must be text")
    title = raw_title.strip()[:160]
    summary = raw_summary.strip()[:3000]
    raw_steps = proposal.get("steps")
    if not title or not summary or not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 12:
        raise ValueError("Plan must include a title, summary, and 1-12 steps")
    steps = []
    for index, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            raise ValueError("Every plan step must be an object")
        keys = ("title", "description", "expected_outcome", "verification")
        if any(not isinstance(item.get(key), str) for key in keys):
            raise ValueError("Plan step fields must all be text")
        values = {key: item[key].strip() for key in keys}
        if any(not values[key] for key in values):
            raise ValueError("Each step needs a title, description, expected outcome, and verification")
        if any(len(value) > limit for value, limit in zip(values.values(), (160, 3000, 1000, 1000))):
            raise ValueError("A plan step exceeds its text limit")
        steps.append(values)
    plan_id, stamp = uuid.uuid4().hex, _now()
    with connection:
        connection.execute(
            """INSERT INTO agent_plans(id,request,workspace,title,summary,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (plan_id, request[:20000], workspace, title, summary, "proposed", stamp, stamp))
        for index, step in enumerate(steps):
            connection.execute(
                """INSERT INTO agent_plan_steps(id,plan_id,position,title,description,expected_outcome,verification)
                   VALUES(?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, plan_id, index, step["title"], step["description"],
                 step["expected_outcome"], step["verification"]))
        _event(connection, plan_id, "proposed", {"step_count": len(steps)})
    return get_plan(connection, plan_id)

def record_event(connection, plan_id, event_type, payload=None, step_id=None):
    if not connection.execute("SELECT 1 FROM agent_plans WHERE id=?", (plan_id,)).fetchone():
        raise ValueError("Agent plan not found")
    with connection:
        _event(connection, plan_id, event_type, payload, step_id)


def _step(row):
    return dict(row)

def get_plan(connection, plan_id):
    row = connection.execute("SELECT * FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["steps"] = [_step(item) for item in connection.execute(
        "SELECT * FROM agent_plan_steps WHERE plan_id=? ORDER BY position", (plan_id,)).fetchall()]
    result["events"] = [{
        "id": item["id"], "step_id": item["step_id"], "type": item["event_type"],
        "payload": json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"]
    } for item in connection.execute(
        "SELECT * FROM agent_plan_events WHERE plan_id=? ORDER BY id LIMIT 500", (plan_id,)).fetchall()]
    return result

def list_plans(connection, limit=50):
    rows = connection.execute(
        "SELECT id,title,summary,status,created_at,updated_at,run_id,error FROM agent_plans ORDER BY created_at DESC LIMIT ?",
        (min(max(int(limit), 1), 100),)).fetchall()
    return [dict(row) for row in rows]

def approve_plan(connection, plan_id):
    stamp = _now()
    with connection:
        cur = connection.execute(
            "UPDATE agent_plans SET status='approved',approved_at=?,updated_at=? WHERE id=? AND status='proposed'",
            (stamp, stamp, plan_id))
        if cur.rowcount != 1:
            raise ValueError("Only a proposed plan can be approved")
        _event(connection, plan_id, "approved")
    return get_plan(connection, plan_id)

def attach_run(connection, plan_id, run_id):
    stamp = _now()
    with connection:
        cur = connection.execute(
            "UPDATE agent_plans SET status='executing',run_id=?,updated_at=? WHERE id=? AND status='approved'",
            (run_id, stamp, plan_id))
        if cur.rowcount != 1:
            raise ValueError("Plan is not approved or has already been started")
        _event(connection, plan_id, "execution_started", {"run_id": run_id})
    return get_plan(connection, plan_id)

def start_step(connection, plan_id, step_id):
    stamp = _now()
    with connection:
        plan = connection.execute("SELECT status FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
        if not plan or plan["status"] != "executing":
            raise ValueError("Steps can only run after the plan has started")
        row = connection.execute(
            "SELECT position,status FROM agent_plan_steps WHERE id=? AND plan_id=?", (step_id, plan_id)).fetchone()
        if not row or row["status"] != "pending":
            raise ValueError("Step is not pending")
        earlier = connection.execute(
            "SELECT COUNT(*) FROM agent_plan_steps WHERE plan_id=? AND position<? AND status!='completed'",
            (plan_id, row["position"])).fetchone()[0]
        if earlier:
            raise ValueError("Earlier plan steps must complete first")
        connection.execute(
            "UPDATE agent_plan_steps SET status='running',started_at=? WHERE id=?", (stamp, step_id))
        _event(connection, plan_id, "step_started", {"position": row["position"]}, step_id)
    return True

def finish_step(connection, plan_id, step_id, outcome, result=""):
    if outcome not in {"completed", "failed", "interrupted"}:
        raise ValueError("Invalid step outcome")
    stamp = _now()
    with connection:
        cur = connection.execute(
            "UPDATE agent_plan_steps SET status=?,result=?,finished_at=? WHERE id=? AND plan_id=? AND status='running'",
            (outcome, str(result)[:4000], stamp, step_id, plan_id))
        if cur.rowcount != 1:
            raise ValueError("Step is not running")
        _event(connection, plan_id, "step_" + outcome, {"result": str(result)[:1000]}, step_id)
    return True

def finish_plan(connection, plan_id, outcome, error=""):
    if outcome not in {"completed", "failed", "cancelled", "interrupted"}:
        raise ValueError("Invalid plan outcome")
    stamp = _now()
    with connection:
        row = connection.execute("SELECT status FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise ValueError("Plan not found")
        if row["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return False
        if outcome == "completed":
            remaining = connection.execute(
                "SELECT COUNT(*) FROM agent_plan_steps WHERE plan_id=? AND status!='completed'",
                (plan_id,)).fetchone()[0]
            if remaining:
                raise ValueError("A plan cannot complete until every step is completed")
        connection.execute(
            "UPDATE agent_plans SET status=?,error=?,updated_at=? WHERE id=?",
            (outcome, str(error)[:2000], stamp, plan_id))
        if outcome != "completed":
            active_outcome = "interrupted" if outcome in {"cancelled", "interrupted"} else "failed"
            connection.execute(
                """UPDATE agent_plan_steps SET status=?,result=?,finished_at=?
                   WHERE plan_id=? AND status='running'""",
                (active_outcome, str(error)[:4000], stamp, plan_id))
            connection.execute(
                "UPDATE agent_plan_steps SET status='skipped',finished_at=? WHERE plan_id=? AND status='pending'",
                (stamp, plan_id))
        _event(connection, plan_id, outcome, {"error": str(error)[:1000]} if error else {})
    return True

def recover_plans(connection):
    rows = connection.execute(
        "SELECT id FROM agent_plans WHERE status IN ('approved','executing')").fetchall()
    recovered = []
    with connection:
        for row in rows:
            finish_plan(connection, row["id"], "interrupted",
                        "Evo restarted; plan steps were not replayed.")
            recovered.append(row["id"])
    return recovered

def propose_with_model(provider, request, workspace, max_tokens=1800):
    """Ask the configured provider for a bounded JSON plan; never execute model output here."""
    system = (
        "You are Evo's task planner. Return ONLY one JSON object with keys title, summary, steps. "
        "Create 2-8 sequential, concrete steps. Each step must have title, description, expected_outcome, "
        "and verification. Keep each step independently understandable and bounded. Include inspection "
        "before edits, and tests/verification after edits when relevant. Do not propose deployment, privilege "
        "escalation, credential access, destructive actions, or arbitrary shell commands. Do not invent "
        "workspace facts. Plans are proposals for user review, not authorization."
    )
    user = ("Workspace: " + workspace + "\\nUser request: " + request[:12000] +
            "\\nReturn valid JSON only. No markdown fences.")
    response = provider.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max(500, min(int(max_tokens), 3000)), temperature=0.1)
    raw = (response.get("content") or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        proposal = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The model did not return a valid structured plan; no plan was saved.") from exc
    if not isinstance(proposal, dict):
        raise ValueError("The model plan must be a JSON object")
    return proposal
