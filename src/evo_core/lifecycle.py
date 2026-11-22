"""Durable agent-run finalization decisions and cross-store reconciliation.

EvoStore and ResultsDB open the same SQLite file through separate connections,
so no single transaction can cover both. Instead of a distributed transaction,
this module records one durable terminal decision per agent run in the lab
connection (the coordination database that already owns background tasks,
plans, and scheduler state). The decision is committed before any mirror update
starts, and reconciliation converges EvoStore, background tasks, plan steps,
plans, and scheduler jobs onto it.

``agent_run_finalizations.run_id`` is the primary key, so the first terminal
decision for a run wins and every later attempt observes it instead of
overwriting it.
"""
from datetime import datetime, timezone
import json

from . import background_agent, orchestration

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
PLAN_TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
EXECUTION_TERMINAL = frozenset({"completed", "failed", "interrupted", "launch_uncertain", "cancelled"})
# Runs created by this application. A crashed run in these states can be
# finalized at startup because no worker of ours can still own it.
APP_OWNED_SOURCES = frozenset({"desktop", "approved-plan"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_run_finalizations (
  run_id TEXT PRIMARY KEY,
  outcome TEXT NOT NULL CHECK(outcome IN ('completed','failed','cancelled','interrupted')),
  source TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_reconciliation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repair_key TEXT NOT NULL UNIQUE,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  outcome TEXT,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_events_entity
  ON lifecycle_reconciliation_events(entity_type, entity_id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _has_table(connection, name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def initialize(connection):
    connection.executescript(SCHEMA)
    connection.commit()


def _ensure_schema(connection):
    if not _has_table(connection, "agent_run_finalizations"):
        initialize(connection)


def _decision(row):
    item = dict(row)
    try:
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
    except (TypeError, ValueError):
        item["evidence"] = {}
    return item


def get_decision(connection, run_id):
    row = connection.execute(
        "SELECT * FROM agent_run_finalizations WHERE run_id=?", (run_id,)).fetchone()
    return _decision(row) if row else None


def list_decisions(connection):
    return [_decision(row) for row in connection.execute(
        "SELECT * FROM agent_run_finalizations ORDER BY decided_at")]


def _record_event(connection, repair_key, entity_type, entity_id, action,
                  outcome=None, detail=None, commit=True):
    """Persist a repair/unresolved event once per key; repeats are silent."""
    cursor = connection.execute(
        """INSERT INTO lifecycle_reconciliation_events
           (repair_key,entity_type,entity_id,action,outcome,detail_json,created_at)
           VALUES(?,?,?,?,?,?,?) ON CONFLICT(repair_key) DO NOTHING""",
        (repair_key, entity_type, entity_id, action, outcome,
         json.dumps(detail or {}, ensure_ascii=False, default=str), _now()))
    if commit:
        connection.commit()
    return cursor.rowcount == 1


def decide(connection, run_id, outcome, *, source="unknown", reason="", evidence=None):
    """Create the winning terminal decision for a run, or return the existing one.

    The decision row and the background-task terminal transition are committed
    together on the lab connection. A background task that already holds a
    terminal outcome is adopted, because that outcome is itself durable evidence
    (for example a cancellation that landed before the worker finished).
    """
    if outcome not in TERMINAL:
        raise ValueError(f"Invalid terminal outcome: {outcome!r}")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("A run id is required for a finalization decision")
    _ensure_schema(connection)
    payload = dict(evidence or {})
    adopted = False
    task = None
    if _has_table(connection, "background_agent_tasks"):
        task = background_agent.get(connection, run_id)
    if task is not None and task["status"] in background_agent.TERMINAL:
        outcome = task["status"]
        adopted = True
        source = "background_task_adopted"
        reason = reason or "Adopted the terminal background-task outcome."
        payload["adopted_task_status"] = task["status"]
    cursor = connection.execute(
        """INSERT INTO agent_run_finalizations
           (run_id,outcome,source,reason,evidence_json,decided_at)
           VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING""",
        (run_id, outcome, source, str(reason)[:2000],
         json.dumps(payload, ensure_ascii=False, default=str), _now()))
    if cursor.rowcount != 1:
        # Another decision won; release the transaction and return it without
        # touching any dependent record.
        connection.commit()
        return {"created": False, "adopted": False,
                "decision": get_decision(connection, run_id)}
    if task is not None:
        background_agent.finalize(
            connection, run_id, outcome,
            {"decision": outcome, "source": source, "reason": str(reason)[:1000]},
            commit=False)
    _record_event(connection, f"decision:{run_id}:{outcome}", "agent_run", run_id,
                  "finalization_decision", outcome,
                  {"source": source, "adopted": adopted}, commit=False)
    connection.commit()
    return {"created": True, "adopted": adopted, "decision": get_decision(connection, run_id)}


def apply_decision(store, decision):
    """Mirror a durable decision into the EvoStore agent-run record."""
    return store.apply_agent_run_decision(
        decision["run_id"], decision["outcome"],
        summary=decision.get("reason") or "",
        source=decision.get("source") or "lifecycle")


def apply_background_from_decision(connection, decision):
    """Make a background task agree with the decision without overwriting it."""
    run_id, outcome = decision["run_id"], decision["outcome"]
    if not _has_table(connection, "background_agent_tasks"):
        return {"applied": False, "reason": "missing"}
    task = background_agent.get(connection, run_id)
    if task is None:
        return {"applied": False, "reason": "missing"}
    if task["status"] == outcome:
        return {"applied": False, "reason": "consistent"}
    if task["status"] in background_agent.TERMINAL:
        return {"applied": False, "reason": "conflict", "existing": task["status"]}
    changed = background_agent.finalize(
        connection, run_id, outcome, {"decision_source": decision["source"]})
    return {"applied": changed, "previous": task["status"], "outcome": outcome}


def apply_plan_decision(connection, plan_id, decision):
    """Derive a plan's terminal state from its steps and the durable decision.

    A plan is never completed unless every required step is completed. A plan
    that already holds a different terminal state is preserved and reported.
    """
    plan = orchestration.get_plan(connection, plan_id)
    if plan is None:
        return {"applied": False, "reason": "missing"}
    if plan["status"] in PLAN_TERMINAL:
        if plan["status"] == decision["outcome"]:
            return {"applied": False, "reason": "consistent"}
        return {"applied": False, "reason": "conflict", "existing": plan["status"]}
    outcome = decision["outcome"]
    if outcome == "completed":
        if any(step["status"] != "completed" for step in plan["steps"]):
            return {"applied": False, "reason": "incomplete_steps"}
        orchestration.finish_plan(connection, plan_id, "completed", decision.get("reason", ""))
        return {"applied": True, "outcome": "completed"}
    orchestration.finish_plan(connection, plan_id, outcome, decision.get("reason", ""))
    return {"applied": True, "outcome": outcome}


def finalize_unclaimed(connection, run_id):
    """Resolve a run whose worker could not claim its queued task.

    Without this, a claim rejected by a cancellation (or by an already-terminal
    task) leaves the agent run ``running`` forever.
    """
    task = None
    if _has_table(connection, "background_agent_tasks"):
        task = background_agent.get(connection, run_id)
    if task is None:
        outcome = "interrupted"
        reason = "No worker claimed this run and it has no coordination record."
    elif task["status"] in background_agent.TERMINAL:
        outcome = task["status"]
        reason = "The task reached a terminal state before a worker claimed it."
    elif task["cancel_requested"] or task["status"] == "cancel_requested":
        outcome = "cancelled"
        reason = "Cancellation was requested before the worker claimed the task."
    else:
        outcome = "failed"
        reason = f"A worker could not claim the task from status {task['status']!r}."
    return decide(connection, run_id, outcome, source="claim_failure", reason=reason)["decision"]


def _run_source(run):
    try:
        metadata = json.loads(run["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return None
    return metadata.get("source")


def _repair_steps(connection, plan, decision):
    """Repair step state from the step's own execution evidence.

    A step still marked ``running`` cannot have a live executor once its run
    holds a terminal decision. Pending steps of a non-completed run are skipped,
    matching the plan-level terminal transition. Completed steps are never
    rewritten.
    """
    repaired = []
    steps = connection.execute(
        "SELECT id,status FROM agent_plan_steps WHERE plan_id=? ORDER BY position",
        (plan["id"],)).fetchall()
    for step in steps:
        if step["status"] == "running":
            try:
                orchestration.finish_step(
                    connection, plan["id"], step["id"], "interrupted",
                    "Evo restarted; the step was not replayed.")
            except ValueError:
                continue
            repaired.append({"step_id": step["id"], "outcome": "interrupted"})
        elif step["status"] == "pending" and decision["outcome"] != "completed":
            cursor = connection.execute(
                "UPDATE agent_plan_steps SET status='skipped',finished_at=? "
                "WHERE id=? AND status='pending'", (_now(), step["id"]))
            if cursor.rowcount == 1:
                orchestration.record_event(
                    connection, plan["id"], "step_skipped",
                    {"reason": "Run finalized as " + decision["outcome"]}, step["id"])
                repaired.append({"step_id": step["id"], "outcome": "skipped"})
    return repaired


def _reconcile_scheduler(connection, report):
    """Repair jobs only from their own execution evidence."""
    if not _has_table(connection, "workload_jobs"):
        return
    from evo_experiments.scheduler import finish_job
    jobs = [dict(row) for row in connection.execute(
        "SELECT id,status FROM workload_jobs WHERE status IN ('running','reserved')")]
    if not jobs:
        return
    executions = {row["job_id"]: dict(row) for row in connection.execute(
        "SELECT job_id,status,error,returncode FROM workload_executions")} \
        if _has_table(connection, "workload_executions") else {}
    for job in jobs:
        execution = executions.get(job["id"])
        if execution is None:
            report["unresolved"].append({
                "entity_type": "workload_job", "entity_id": job["id"],
                "reason": "job_without_execution",
                "detail": "No execution evidence exists; the job is not repaired or cancelled."})
            continue
        if execution["status"] not in EXECUTION_TERMINAL:
            report["unresolved"].append({
                "entity_type": "workload_job", "entity_id": job["id"],
                "reason": "execution_not_terminal",
                "detail": f"Execution is still {execution['status']!r}; reconciliation does not invent an outcome."})
            continue
        if job["status"] != "running":
            report["unresolved"].append({
                "entity_type": "workload_job", "entity_id": job["id"],
                "reason": "reserved_job_with_terminal_execution",
                "detail": f"Execution is {execution['status']!r} while the job is reserved."})
            continue
        outcome = "completed" if execution["status"] == "completed" else "failed"
        note = (execution.get("error") or
                f"Reconciled from execution status {execution['status']!r}")
        try:
            finish_job(connection, job["id"], outcome, note, commit=False)
            _record_event(connection, f"workload_job:{job['id']}:{outcome}", "workload_job",
                          job["id"], "terminal_state_repaired", outcome,
                          {"execution_status": execution["status"]}, commit=False)
            connection.commit()
        except ValueError as exc:
            connection.rollback()
            report["unresolved"].append({
                "entity_type": "workload_job", "entity_id": job["id"],
                "reason": "scheduler_transition_rejected", "detail": str(exc)})
            continue
        report["scheduler"].append({"job_id": job["id"], "applied": True, "outcome": outcome})


def reconcile(store, lab_db, *, live_run_ids=None):
    """Converge every lifecycle record onto its durable decision.

    Safe to call at startup and safe to repeat. Each repair is committed on its
    own; an interruption leaves already-repaired records fixed and the rest for
    the next invocation. Nothing is replayed and no process is touched.

    ``live_run_ids`` protects workers that are still active in this process when
    reconciliation is invoked outside startup.
    """
    live = set(live_run_ids or ())
    report = {
        "decisions": [], "agent_runs": [], "background_tasks": [], "plans": [],
        "steps": [], "scheduler": [], "unresolved": [], "skipped_live": [],
        "events": 0,
    }
    connection = lab_db.connection
    with lab_db.lock:
        _ensure_schema(connection)
        task_rows = {}
        if _has_table(connection, "background_agent_tasks"):
            task_rows = {row["run_id"]: dict(row) for row in
                         connection.execute("SELECT * FROM background_agent_tasks")}
        plan_rows = []
        if _has_table(connection, "agent_plans"):
            plan_rows = [dict(row) for row in connection.execute("SELECT * FROM agent_plans")]
        decision_rows = {row["run_id"]: _decision(row) for row in
                         connection.execute("SELECT * FROM agent_run_finalizations")}
        events_before = connection.execute(
            "SELECT COUNT(*) FROM lifecycle_reconciliation_events").fetchone()[0]

    candidates = set(task_rows) | set(decision_rows)
    candidates |= {row["run_id"] for row in plan_rows if row["run_id"]}
    candidates |= {row["id"] for row in store.list_active_agent_runs()}
    candidates = sorted(candidates)
    run_states = {run_id: store.get_agent_run(run_id) for run_id in candidates}

    # 1. Ensure each coordinated run has exactly one durable terminal decision.
    for run_id in candidates:
        if run_id in live:
            report["skipped_live"].append(run_id)
            continue
        if run_id in decision_rows:
            continue
        run = run_states.get(run_id)
        run_status = run["status"] if run is not None else None
        task = task_rows.get(run_id)
        if run_status in TERMINAL:
            source, outcome = "legacy_agent_run", run_status
            reason = ("Adopted the terminal agent-run outcome recorded before the "
                      "finalization decision ledger existed.")
        elif task is not None and task["status"] in background_agent.TERMINAL:
            source, outcome = "background_task_adopted", task["status"]
            reason = ("Adopted the terminal background-task outcome recorded before "
                      "the finalization decision ledger existed.")
        elif task is not None:
            source = "startup_recovery"
            if task["cancel_requested"] or task["status"] == "cancel_requested":
                outcome = "cancelled"
                reason = "Cancellation had been requested; no worker remains after restart."
            else:
                outcome = "interrupted"
                reason = "Evo restarted; in-flight work was not resumed and nothing was replayed."
        elif run_status is not None and _run_source(run) in APP_OWNED_SOURCES:
            source, outcome = "startup_recovery", "interrupted"
            reason = ("Evo restarted before this run was attached to a worker; "
                      "nothing was replayed.")
        else:
            report["unresolved"].append({
                "entity_type": "agent_run", "entity_id": run_id,
                "reason": "orphan_run_without_coordination_record",
                "detail": ("No decision, no background task, and the run is not owned by "
                           "this application, so its outcome cannot be inferred safely.")})
            continue
        with lab_db.lock:
            result = decide(connection, run_id, outcome, source=source, reason=reason,
                            evidence={"reconciled": True})
        decision_rows[run_id] = result["decision"]
        report["decisions"].append({"run_id": run_id, "outcome": result["decision"]["outcome"],
                                    "created": result["created"], "adopted": result["adopted"]})

    # 2. Mirror decisions into EvoStore without overwriting conflicting evidence.
    for run_id in sorted(decision_rows):
        decision = decision_rows[run_id]
        result = apply_decision(store, decision)
        report["agent_runs"].append({"run_id": run_id, **result})
        if result.get("reason") == "conflict":
            report["unresolved"].append({
                "entity_type": "agent_run", "entity_id": run_id,
                "reason": "terminal_conflict",
                "detail": (f"Durable decision is {decision['outcome']!r} but the agent run is "
                           f"{result.get('existing')!r}; the existing record is preserved.")})

    # 3. Repair or reconstruct background tasks for durable decisions.
    for run_id in sorted(decision_rows):
        decision = decision_rows[run_id]
        outcome = decision["outcome"]
        reconstructed = False
        if run_id not in task_rows:
            run = store.get_agent_run(run_id)
            if run is None:
                report["unresolved"].append({
                    "entity_type": "background_agent_task", "entity_id": run_id,
                    "reason": "decision_without_agent_run",
                    "detail": "The durable decision has no corresponding agent-run record; no task was created."})
                report["background_tasks"].append({
                    "run_id": run_id, "applied": False,
                    "reason": "missing_agent_run", "reconstructed": False})
                continue
            with lab_db.lock:
                reconstructed = background_agent.reconstruct_terminal(
                    connection, run_id, outcome,
                    decided_at=decision.get("decided_at"),
                    source=decision.get("source", "lifecycle"),
                    reason=decision.get("reason", ""))
                if reconstructed:
                    _record_event(
                        connection, f"background_task:{run_id}:reconstructed",
                        "background_agent_task", run_id, "reconstructed_from_finalization",
                        outcome, {"source": decision.get("source", "lifecycle")}, commit=False)
                    connection.commit()
                task = background_agent.get(connection, run_id)
                if task is not None:
                    task_rows[run_id] = task
        with lab_db.lock:
            result = apply_background_from_decision(connection, decision)
            if result.get("applied"):
                _record_event(connection, f"background_task:{run_id}:{outcome}",
                              "background_agent_task", run_id, "terminal_state_repaired",
                              outcome, {"previous": result.get("previous")})
        result = dict(result)
        result["reconstructed"] = reconstructed
        report["background_tasks"].append({"run_id": run_id, **result})
        if result.get("reason") == "conflict":
            report["unresolved"].append({
                "entity_type": "background_agent_task", "entity_id": run_id,
                "reason": "terminal_conflict",
                "detail": (f"Durable decision is {outcome!r} but the task "
                           f"is {result.get('existing')!r}; the existing record is preserved.")})

    # 4. Reconcile plan steps from their own evidence, then the parent plan.
    for plan in plan_rows:
        decision = decision_rows.get(plan["run_id"]) if plan["run_id"] else None
        if decision is None:
            if plan["status"] in {"approved", "executing"}:
                with lab_db.lock:
                    orchestration.finish_plan(
                        connection, plan["id"], "interrupted",
                        "Evo restarted; plan steps were not replayed.")
                    _record_event(connection, f"plan:{plan['id']}:interrupted", "agent_plan",
                                  plan["id"], "terminal_state_repaired", "interrupted",
                                  {"reason": "no_durable_decision"})
                report["plans"].append({"plan_id": plan["id"], "applied": True,
                                        "outcome": "interrupted", "decision": None})
            continue
        with lab_db.lock:
            step_repairs = _repair_steps(connection, plan, decision)
            result = apply_plan_decision(connection, plan["id"], decision)
            if result.get("applied"):
                _record_event(connection, f"plan:{plan['id']}:{result.get('outcome')}",
                              "agent_plan", plan["id"], "terminal_state_repaired",
                              result.get("outcome"), {"decision": decision["outcome"]})
        report["steps"].extend({"plan_id": plan["id"], **item} for item in step_repairs)
        report["plans"].append({"plan_id": plan["id"], **result,
                                "decision": decision["outcome"]})
        if result.get("reason") == "incomplete_steps":
            report["unresolved"].append({
                "entity_type": "agent_plan", "entity_id": plan["id"],
                "reason": "completed_run_with_incomplete_steps",
                "detail": "The run is completed but at least one plan step is not completed; "
                          "the plan is not marked completed."})
        elif result.get("reason") == "conflict":
            report["unresolved"].append({
                "entity_type": "agent_plan", "entity_id": plan["id"],
                "reason": "terminal_conflict",
                "detail": (f"Durable decision is {decision['outcome']!r} but the plan is "
                           f"{result.get('existing')!r}; the existing record is preserved.")})

    # 5. Repair scheduler jobs that disagree with their execution evidence.
    with lab_db.lock:
        _reconcile_scheduler(connection, report)

    # 6. Persist unresolved findings once so they stay observable without noise.
    with lab_db.lock:
        for item in report["unresolved"]:
            key = f"unresolved:{item['entity_type']}:{item['entity_id']}:{item['reason']}"
            _record_event(connection, key, item["entity_type"], item["entity_id"],
                          "unresolved", None, {"reason": item["reason"],
                                               "detail": item.get("detail", "")},
                          commit=False)
        connection.commit()
        events_after = connection.execute(
            "SELECT COUNT(*) FROM lifecycle_reconciliation_events").fetchone()[0]
    report["events"] = events_after - events_before
    return report
