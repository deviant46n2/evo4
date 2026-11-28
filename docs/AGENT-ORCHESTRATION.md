# Agent Intelligence & Orchestration v1

## Purpose

Move from a single open-ended coding-agent loop to a user-reviewable plan with durable sequential steps. The model proposes a plan; the user decides whether it may run. The existing coding-agent policy remains the execution boundary.

## Lifecycle

Plan states:

- `proposed`: generated and persisted; no execution authorization.
- `approved`: user explicitly approved the plan.
- `executing`: an execution run was created and attached.
- `completed`, `failed`, `cancelled`, `interrupted`: terminal outcomes.

Step states:

- `pending` → `running` → `completed`
- A failed or interrupted step stops the plan. Later pending steps become `skipped`.
- Steps must start in position order. A step can only finish after it has started.

Plans and steps are stored in the Evo Lab SQLite database. Plan events are append-only. Each step stores its description, expected outcome, verification instruction, status, result summary, and timestamps.

## Model proposal

`POST /api/v1/agents/plans` asks the configured provider for a JSON proposal. The prompt requests 2–8 sequential steps, including inspection and verification where relevant. The server validates required fields, text bounds, and a maximum of 12 steps before persisting anything. Invalid JSON or malformed plans are rejected; no fallback plan is fabricated.

A model-generated plan is untrusted proposal data. It is not authorization to write files, execute commands, deploy, or access credentials.

## Approval and execution

- `GET /api/v1/agents/plans` lists recent plans.
- `GET /api/v1/agents/plans/{plan_id}` returns the plan, steps, and events.
- `POST /api/v1/agents/plans/{plan_id}/approve` explicitly approves a proposed plan.
- `POST /api/v1/agents/plans/{plan_id}/execute` starts an approved plan.

The worker executes steps sequentially. Each step is passed to the existing `CodingAgent` with the original request, step scope, expected outcome, and verification instruction. Each file write and allowlisted command still goes through the existing approval callback. The orchestrator does not bypass workspace path checks, test-file write approval, or command allowlisting.

The coding agent can now be called with `finalize_run=False` so a multi-step plan has one agent-run lifecycle and is finalized only after the plan ends.

## Cancellation and recovery

Cancellation is cooperative at provider/tool safe boundaries and between steps. Terminal completion is serialized against cancellation so a late cancellation cannot silently overwrite a completed task or vice versa. If the application restarts while a plan is approved or executing, it becomes `interrupted`; active steps are marked interrupted, pending steps skipped, and no work is replayed.

- When explicit verification commands are configured, each command still requires its own approval and is run through managed execution. The persisted verification record carries the managed execution ID. The review surface resolves that ID to the managed execution record only when its run ID, project, task workspace, pinned source revision, working directory, and exact argv all match the owning run and operation. Matching records expose the persisted command, effective command-policy snapshot, working directory, source revision, timeout, timestamps, exit status, elapsed time, and limited approval provenance. A missing or mismatched execution record remains visibly unlinked rather than being inferred from the ID. Before and after each command, Evo also computes a bounded SHA-256 fingerprint over regular files in the task workspace (excluding Git's internal metadata). The record retains both fingerprints and whether the snapshots were complete and identical. Symlinks, special files, concurrent changes, timeouts, and file/byte budget exhaustion fail closed to an unavailable fingerprint; they do not turn a command failure into success. A changed or unavailable snapshot is explicitly shown in review and must not be described as a stable tested state.
- The task-workspace review API joins agent runs and plan verification only when project ID, task workspace ID, operation ID, and pinned source revision all match. It exposes the run/plan status and bounded command results; this is provenance linkage, not proof that a passing command establishes overall correctness.

## Verification state semantics

Plan-level verification summaries preserve five distinct step outcomes: passed, failed, not run, not configured, and not required. A plan is reported as passed only when every step passes; any failed step makes the aggregate failed. Missing checks remain not run. Plans whose steps are all not required or all not configured retain those states. Mixed non-failing outcomes are reported as incomplete rather than being collapsed into not run or success.

## Important limitations

- Step completion currently means the coding-agent loop returned a completed result for that step. The verification instruction is included in the step prompt and stored for audit, but the instruction text itself is **not** an independent verification oracle. When a step defines explicit `verification_commands`, the worker separately executes each command through the existing approval callback and records its result; denied, failed, or unrun commands prevent the step from completing. These command results provide deterministic evidence for the checks they directly exercise, but do not prove overall correctness or replace independent review.
- The model may propose a poor or incomplete plan. The user must inspect it before approval.
- A plan may need multiple per-action approvals; approving the plan does not approve file writes or commands.
- There is no automatic retry, pause/resume, redirect, checkpointed recovery, or durable approval restoration.
- Agent orchestration does not currently reserve hardware scheduler capacity. Reliable per-plan VRAM/RAM demand estimates are unavailable; unknown demand is not treated as safe.
- This remains supervised execution, not unattended autonomy or self-modification.

## Validation expectations

Run the full Python unit suite, compileall, frontend production build, and `git diff --check`. Add tests for plan validation, approval gates, sequential step order, failure/skip behavior, event persistence, restart recovery, and API integration. Browser and live-model tests are separate and must be reported as unperformed unless actually run.
