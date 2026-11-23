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
      verification_commands_json TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '',
      started_at TEXT, finished_at TEXT, UNIQUE(plan_id,position)
    );
    CREATE TABLE IF NOT EXISTS agent_plan_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL REFERENCES agent_plans(id) ON DELETE CASCADE,
      step_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_agent_plan_events ON agent_plan_events(plan_id,id);
    CREATE TABLE IF NOT EXISTS agent_plan_step_verifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      plan_id TEXT NOT NULL REFERENCES agent_plans(id) ON DELETE CASCADE,
      step_id TEXT NOT NULL REFERENCES agent_plan_steps(id) ON DELETE CASCADE,
      position INTEGER NOT NULL,
      command_json TEXT NOT NULL,
      status TEXT NOT NULL,
      exit_code INTEGER,
      stdout TEXT NOT NULL DEFAULT '',
      stderr TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_plan_step_verifications ON agent_plan_step_verifications(plan_id,step_id,id);
    """)
    for column, definition in (
        ("verification_commands_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("verification_status", "TEXT NOT NULL DEFAULT 'not_configured'"),
    ):
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_plan_steps)")}
        if column not in columns:
            connection.execute(f"ALTER TABLE agent_plan_steps ADD COLUMN {column} {definition}")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_plans)")}
    if "workspace_id" not in columns:
        connection.execute("ALTER TABLE agent_plans ADD COLUMN workspace_id TEXT")
    if "project_id" not in columns:
        connection.execute("ALTER TABLE agent_plans ADD COLUMN project_id TEXT")
    connection.commit()

def _event(connection, plan_id, event_type, payload=None, step_id=None):
    connection.execute(
        "INSERT INTO agent_plan_events(plan_id,step_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
        (plan_id, step_id, event_type, json.dumps(payload or {}, ensure_ascii=False, default=str), _now()))

def create_plan(connection, request, *args, allowed_commands=None, workspace_id=None, project_id=None, workspace=None, proposal=None):
    # Support both the legacy (workspace, proposal) signature and the new
    # (workspace_id, workspace, proposal) signature without breaking callers.
    positional = list(args)
    if proposal is None and positional and isinstance(positional[-1], dict):
        proposal = positional.pop()
    if workspace is None and len(positional) >= 2 and isinstance(positional[1], str) and (positional[0] is None or isinstance(positional[0], str)):
        workspace_id = positional.pop(0)
        workspace = positional.pop(0)
    elif workspace is None and len(positional) == 1 and isinstance(positional[0], str):
        workspace = positional.pop(0)
    if allowed_commands is None and positional:
        allowed_commands = positional.pop()
    if not isinstance(proposal, dict):
        raise ValueError("Plan proposal must be an object")
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError("A resolved workspace path is required")
    workspace = workspace.strip()
    if workspace_id is not None and (not isinstance(workspace_id, str) or not workspace_id.strip()):
        raise ValueError("workspace_id must be a non-empty string when provided")
    if isinstance(workspace_id, str):
        workspace_id = workspace_id.strip()
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise ValueError("project_id must be a non-empty string when provided")
    if isinstance(project_id, str):
        project_id = project_id.strip()
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
        commands = item.get("verification_commands", [])
        if commands is None:
            commands = []
        if not isinstance(commands, list) or len(commands) > 5:
            raise ValueError("verification_commands must be a list of at most 5 commands")
        normalized_commands = []
        for command in commands:
            if not isinstance(command, list) or not command or not all(isinstance(part, str) and part.strip() for part in command):
                raise ValueError("Each verification command must be a nonempty argv list of strings")
            if len(command) > 20 or any(len(part) > 500 for part in command):
                raise ValueError("A verification command exceeds its size limit")
            normalized_commands.append([part.strip() for part in command])
        values["verification_commands"] = normalized_commands
        if allowed_commands is not None and normalized_commands:
            allowed = [list(prefix) for prefix in allowed_commands if isinstance(prefix, (list, tuple)) and prefix]
            for command in normalized_commands:
                if not any(command[:len(prefix)] == prefix for prefix in allowed):
                    raise ValueError("A verification command must match one of the configured command prefixes")
        steps.append(values)
    plan_id, stamp = uuid.uuid4().hex, _now()
    with connection:
        connection.execute(
            """INSERT INTO agent_plans(id,request,workspace,workspace_id,project_id,title,summary,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (plan_id, request[:20000], workspace, workspace_id, project_id, title, summary, "proposed", stamp, stamp))
        for index, step in enumerate(steps):
            connection.execute(
                """INSERT INTO agent_plan_steps(id,plan_id,position,title,description,expected_outcome,verification,verification_commands_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, plan_id, index, step["title"], step["description"],
                 step["expected_outcome"], step["verification"],
                 json.dumps(step["verification_commands"])))
        _event(connection, plan_id, "proposed", {"step_count": len(steps)})
    return get_plan(connection, plan_id)

def record_event(connection, plan_id, event_type, payload=None, step_id=None):
    if not connection.execute("SELECT 1 FROM agent_plans WHERE id=?", (plan_id,)).fetchone():
        raise ValueError("Agent plan not found")
    with connection:
        _event(connection, plan_id, event_type, payload, step_id)


def _step(row):
    item = dict(row)
    try:
        item["verification_commands"] = json.loads(item.get("verification_commands_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        item["verification_commands"] = []
    item["verification_status"] = item.get("verification_status") or "not_configured"
    return item

def get_plan(connection, plan_id):
    row = connection.execute("SELECT * FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    steps = [_step(item) for item in connection.execute(
        "SELECT * FROM agent_plan_steps WHERE plan_id=? ORDER BY position", (plan_id,)).fetchall()]
    for step in steps:
        step["verification_checks"] = [dict(v) for v in connection.execute(
            "SELECT id,command_json,status,exit_code,stdout,stderr,created_at FROM agent_plan_step_verifications WHERE step_id=? ORDER BY id",
            (step["id"],)).fetchall()]
        for check in step["verification_checks"]:
            try:
                check["command"] = json.loads(check.pop("command_json"))
            except (TypeError, json.JSONDecodeError):
                check["command"] = []
    for step in steps:
        step["verification_status"] = step_verification_status(step)
    result["steps"] = steps
    result["verification_summary"] = {
        "passed": sum(1 for s in steps if s["verification_status"] == "passed"),
        "failed": sum(1 for s in steps if s["verification_status"] == "failed"),
        "not_run": sum(1 for s in steps if s["verification_status"] == "not_run"),
        "not_configured": sum(1 for s in steps if s["verification_status"] == "not_configured"),
    }
    result["events"] = [{
        "id": item["id"], "step_id": item["step_id"], "type": item["event_type"],
        "payload": json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"]
    } for item in connection.execute(
        "SELECT * FROM agent_plan_events WHERE plan_id=? ORDER BY id LIMIT 500", (plan_id,)).fetchall()]
    return result

def list_plans(connection, limit=50):
    rows = connection.execute(
        "SELECT id,title,summary,status,workspace,workspace_id,project_id,created_at,updated_at,run_id,error FROM agent_plans ORDER BY created_at DESC LIMIT ?",
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

def finish_step(connection, plan_id, step_id, outcome, result="", verification_status=None):
    if outcome not in {"completed", "failed", "interrupted"}:
        raise ValueError("Invalid step outcome")
    allowed_verification = {"passed", "failed", "not_run", "not_required", "not_configured"}
    if verification_status is None:
        verification_status = "not_configured"
    if verification_status not in allowed_verification:
        raise ValueError("Invalid verification status")
    stamp = _now()
    with connection:
        cur = connection.execute(
            "UPDATE agent_plan_steps SET status=?,result=?,finished_at=?,verification_status=? WHERE id=? AND plan_id=? AND status='running'",
            (outcome, str(result)[:4000], stamp, verification_status, step_id, plan_id))
        if cur.rowcount != 1:
            raise ValueError("Step is not running")
        _event(connection, plan_id, "step_" + outcome, {"result": str(result)[:1000], "verification_status": verification_status}, step_id)
    return True

def record_verification(connection, plan_id, step_id, command, status, exit_code=None, stdout="", stderr=""):
    if status not in {"passed", "failed", "denied", "error", "timed_out"}:
        raise ValueError("Invalid verification status")
    stamp = _now()
    with connection:
        connection.execute(
            """INSERT INTO agent_plan_step_verifications
               (plan_id,step_id,position,command_json,status,exit_code,stdout,stderr,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (plan_id, step_id,
             connection.execute("SELECT position FROM agent_plan_steps WHERE id=?", (step_id,)).fetchone()[0],
             json.dumps(command), status, exit_code, str(stdout)[:4000], str(stderr)[:4000], stamp))
    return True

def step_verification_status(step):
    persisted = step.get("verification_status")
    if persisted in {"passed", "failed", "not_run", "not_required"}:
        return persisted
    commands = [list(command) for command in (step.get("verification_commands") or [])]
    checks = step.get("verification_checks") or []
    if not commands:
        return "not_configured"
    if not checks:
        return "not_run"
    if any(check.get("status") != "passed" for check in checks):
        return "failed"
    remaining = [list(command) for command in commands]
    for check in checks:
        if check.get("status") != "passed":
            continue
        try:
            command = list(check.get("command") or [])
        except TypeError:
            command = []
        for index, configured in enumerate(remaining):
            if command == configured:
                del remaining[index]
                break
    if remaining:
        return "not_run"
    return "passed"

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
            unverified = connection.execute(
                "SELECT COUNT(*) FROM agent_plan_steps WHERE plan_id=? AND verification_status NOT IN ('passed','not_required')",
                (plan_id,)).fetchone()[0]
            if unverified:
                raise ValueError("A plan cannot complete until every step has passed or not-required verification")
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

def propose_with_model(provider, request, workspace, max_tokens=1800, allowed_commands=None):
    """Ask the configured provider for a bounded JSON plan; never execute model output here."""
    allowed_text = "none configured"
    if allowed_commands:
        allowed_text = ", ".join(" ".join(str(part) for part in prefix) for prefix in allowed_commands if prefix)
    system = (
        "You are Evo's task planner. Return ONLY one JSON object with keys title, summary, steps. "
        "Create 2-8 sequential, concrete steps. Each step must have title, description, expected_outcome, "
        "and verification. Keep each step independently understandable and bounded. Include inspection "
        "before edits, and tests/verification after edits when relevant. Do not propose deployment, privilege "
        "escalation, credential access, destructive actions, or arbitrary shell commands. Do not invent "
        "workspace facts. Plans are proposals for user review, not authorization. "
        "Configured command prefixes: " + allowed_text + ". Propose verification_commands only as argv "
        "arrays whose first elements match one of those prefixes. Never invent an unsupported command."
    )
    user = ("Workspace: " + workspace + "\nUser request: " + request[:12000] +
            "\\nReturn valid JSON only. No markdown fences.")
    response = provider.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max(500, min(int(max_tokens), 3000)), temperature=0.1)
    raw = (response.get("content") or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        proposal = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The model did not return a valid structured plan; no plan was saved.") from exc
    if not isinstance(proposal, dict):
        raise ValueError("The model plan must be a JSON object")
    return proposal
