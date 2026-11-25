# Background Agent Execution v1

## What this milestone adds

Evo's existing approval-gated coding agent now runs as a durable background task. The task lifecycle is recorded separately from the existing agent/tool-event history:

- queued
- running
- awaiting_approval
- cancel_requested
- completed / failed / cancelled / interrupted

Each lifecycle transition is append-only and timestamped. Tool proposals and results are also reflected in the lifecycle feed with bounded summaries; detailed tool inputs/outputs remain in the existing agent event log.

## Safety and execution semantics

- A task is atomically claimed from the queued state. Concurrent workers cannot claim the same task.
- Read-only project inspection remains automatic.
- File writes and allowlisted commands still require explicit approval for each action.
- Cancellation is cooperative. Evo checks the cancellation signal before and after provider calls and before starting each next tool action. A provider request or an already-started tool action cannot currently be interrupted; cancellation takes effect when that operation returns or reaches its own timeout. Evo checks again before beginning the next side effect.
- Denied actions are not executed. Cancelling while awaiting approval resolves the approval as denied.
- Existing managed command execution continues to use its own argv allowlist, timeout, output bounds, and private child process group.
- No arbitrary model-generated shell strings, process attachment, or process management is introduced.
- Existing tool history remains the detailed audit trail. Lifecycle event payloads avoid copying write contents and cap output summaries.

## Restart behavior and limitations

On startup, any nonterminal background task is marked interrupted. Evo does not automatically resume a provider call or replay a tool action: it cannot know whether an external side effect completed immediately before the crash. The previous state and interruption are retained in the event history. The user must inspect the task/tool history and explicitly start a new task if work should continue.

This is durable task tracking and safe-boundary cancellation, not checkpointed continuation. Pause/resume, redirect, durable approval recovery, per-step retry, model-generated explicit plans, and automatic verification orchestration are not implemented in v1.

## Shutdown

Application shutdown resolves pending approvals as denied and signals the normal shutdown flag. Background provider calls are not forcibly interrupted; the existing executor drains before SQLite is closed. The provider's configured request timeout therefore bounds how long shutdown may wait for an in-flight request. Managed command workers retain their separate configured execution timeout.

## API

- GET /api/v1/agents/{run_id} includes background_task and background_events.
- GET /api/v1/agents/{run_id}/events?after_id=0&limit=200 returns incremental lifecycle events.
- POST /api/v1/agents/{run_id}/cancel requests cooperative cancellation.
- /api/v1/capabilities reports background task, cancellation, event history, restart recovery, and explicitly reports background_agent_resume: false.

## Validation boundaries

Automated tests cover task claims, lifecycle transitions, cancellation persistence, ordered/incremental event retrieval, and restart interruption. Production build and full API/agent integration must be independently validated. No browser or live-model claim is made by this document.


## Persisted project/workspace scope

Background-agent task rows persist `project_id` and `workspace_id` as first-class columns, populated from the corresponding run's creation metadata. The queued lifecycle event also records those identifiers. The columns survive cancellation, terminal transitions, and restart recovery; recovery changes task status to `interrupted` without dropping or rewriting scope. Legacy runs without scope metadata remain explicitly unscoped. A workspace identifier without a project identifier is rejected when creating a task. Scope columns are provenance and queryable ownership data; they do not themselves grant authorization.
