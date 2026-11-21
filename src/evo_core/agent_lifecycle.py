"""Cross-component agent lifecycle reconciliation.

This module does not create a global transaction across EvoStore and ResultsDB.
It records durable finalization decisions in ResultsDB, then converges dependent
records in small, repeatable, per-database transactions.
"""
from datetime import datetime, timezone

import sqlite3

from . import background_agent, orchestration
from evo_experiments.execution import get_execution, recover_interrupted_executions
from evo_experiments.scheduler import finish_job, get_job


def _now():
    return datetime.now(timezone.utc).isoformat()


def initialize(connection):
    background_agent.initialize(connection)


def decide_finalization(connection, run_id, outcome, summary="", metadata=None):
    return background_agent.decide_finalization(connection, run_id, outcome, summary, metadata)


def get_finalization(connection, run_id):
    return background_agent.get_finalization(connection, run_id)


def _terminal_store_status(store, run_id):
    row = store.get_agent_run(run_id)
    return row["status"] if row is not None else None


def _reconcile_finalization(lab_connection, store, decision, unresolved):
    run_id = decision["run_id"]
    outcome = decision["outcome"]
    summary = decision["summary"]
    store_status = _terminal_store_status(store, run_id)
    if store_status is None:
        unresolved.append({"run_id": run_id, "reason": "agent run missing"})
    elif store_status not in store.TERMINAL_AGENT_RUN_STATUSES:
        store.finish_agent_run(run_id, outcome, summary)
    elif store_status != outcome:
        unresolved.append({
            "run_id": run_id,
            "reason": "conflicting terminal agent run status",
            "decision": outcome,
            "stored": store_status,
        })

    task = background_agent.get(lab_connection, run_id)
    if task is None:
        stamp = _now()
        with lab_connection:
            lab_connection.execute(
                """INSERT OR IGNORE INTO background_agent_tasks
                   (run_id, status, cancel_requested, worker_token, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (run_id, outcome, 0, None, stamp, stamp))
            background_agent._event(lab_connection, run_id, "reconciled", {"outcome": outcome})
        task = background_agent.get(lab_connection, run_id)
    elif task["status"] not in background_agent.TERMINAL:
        background_agent.transition(lab_connection, run_id, outcome, {"summary": summary})
        task = background_agent.get(lab_connection, run_id)
    elif task["status"] != outcome:
        unresolved.append({
            "run_id": run_id,
            "reason": "conflicting terminal background task status",
            "decision": outcome,
            "stored": task["status"],
        })

    plan = None
    for candidate in orchestration.list_plans(lab_connection, 500):
        if candidate.get("run_id") == run_id:
            plan = orchestration.get_plan(lab_connection, candidate["id"])
            break
    if plan is not None:
        if plan["status"] not in orchestration.PLAN_STATES - {"proposed", "approved", "executing"}:
            # already terminal
            if plan["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
                pass
        if plan["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
            plan_outcome = outcome if outcome in {"completed", "failed", "cancelled", "interrupted"} else "failed"
            if plan_outcome == "completed":
                remaining = lab_connection.execute(
                    "SELECT COUNT(*) FROM agent_plan_steps WHERE plan_id=? AND status!='completed'",
                    (plan["id"],)).fetchone()[0]
                if remaining:
                    plan_outcome = "failed"
            orchestration.finish_plan(lab_connection, plan["id"], plan_outcome, summary)
        elif plan["status"] != outcome and plan["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
            unresolved.append({"plan_id": plan["id"], "reason": "unrecognized plan status", "status": plan["status"]})


def reconcile_executions(lab_connection, unresolved):
    recover_interrupted_executions(lab_connection)
    rows = lab_connection.execute("SELECT * FROM workload_executions").fetchall()
    for raw in rows:
        item = dict(raw)
        status = item["status"]
        job = get_job(lab_connection, item["job_id"])
        if job is None:
            unresolved.append({"execution_id": item["id"], "reason": "scheduler job missing"})
            continue
        if job["status"] not in {"running"}:
            continue
        if status in {"completed"}:
            try:
                finish_job(lab_connection, item["job_id"], "completed", item.get("error") or "Recovered completion", commit=True)
            except Exception:
                unresolved.append({"execution_id": item["id"], "reason": "scheduler completion failed"})
        elif status in {"failed", "interrupted", "launch_uncertain"}:
            try:
                finish_job(lab_connection, item["job_id"], "failed", item.get("error") or "Recovered terminal state", commit=True)
            except Exception:
                unresolved.append({"execution_id": item["id"], "reason": "scheduler failure finalization failed"})
        else:
            # queued/launching/running without a durable terminal decision remain unresolved.
            unresolved.append({"execution_id": item["id"], "reason": "execution not terminal", "status": status})


def reconcile(lab_connection, store):
    """Converge lifecycle records. Returns a deterministic summary."""
    initialize(lab_connection)
    unresolved = []
    decisions = background_agent.list_finalizations(lab_connection)

    # 1. Apply durable decisions.
    for decision in decisions:
        try:
            _reconcile_finalization(lab_connection, store, decision, unresolved)
        except Exception as exc:
            unresolved.append({"run_id": decision["run_id"], "reason": f"reconciliation error: {type(exc).__name__}: {exc}"})

    # 2. Tasks without durable decisions: conservative interrupted outcome.
    for task in background_agent.list_tasks(lab_connection, 500):
        run_id = task["run_id"]
        if background_agent.get_finalization(lab_connection, run_id) is not None:
            continue
        if task["status"] in background_agent.TERMINAL:
            continue
        store_status = _terminal_store_status(store, run_id)
        if store_status in store.TERMINAL_AGENT_RUN_STATUSES:
            background_agent.decide_finalization(lab_connection, run_id, store_status, "Reconciled from agent run")
            decision = background_agent.get_finalization(lab_connection, run_id)
            try:
                _reconcile_finalization(lab_connection, store, decision, unresolved)
            except Exception as exc:
                unresolved.append({"run_id": run_id, "reason": f"reconciliation error: {type(exc).__name__}: {exc}"})
        else:
            background_agent.decide_finalization(lab_connection, run_id, "interrupted", "Reconciled as unresolved after recovery")
            decision = background_agent.get_finalization(lab_connection, run_id)
            try:
                _reconcile_finalization(lab_connection, store, decision, unresolved)
            except Exception as exc:
                unresolved.append({"run_id": run_id, "reason": f"reconciliation error: {type(exc).__name__}: {exc}"})

    # 3. Plans without finalization: conservative interrupted recovery.
    orchestration.recover_plans(lab_connection)

    # 4. Scheduler/execution reconciliation.
    try:
        reconcile_executions(lab_connection, unresolved)
    except Exception as exc:
        unresolved.append({"reason": f"execution reconciliation error: {type(exc).__name__}: {exc}"})

    return {
        "decisions": len(decisions),
        "unresolved": unresolved,
        "reconciled_at": _now(),
    }
