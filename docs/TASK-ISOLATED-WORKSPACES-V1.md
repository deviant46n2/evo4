# Task-isolated repository workspaces v1

## Purpose

A bounded task must operate on a specific source revision in a checkout that is
isolated from the registered source checkout and every other registered
checkout. The source checkout remains the user's reference checkout; task
changes belong only in a task-specific Git worktree.

## Contract

`create_task_workspace(store, parent_workspace_id, task_id, destination_parent,
source_revision=None)`:

1. Resolves an active Registry workspace and its registered, available checkout.
2. Requires the source checkout to be clean, including untracked files.
3. Pins the task to a full Git commit object ID. If omitted, the current source
   HEAD is captured; mutable refs such as branch names and `HEAD` are rejected
   as explicit revisions.
4. Creates a detached Git worktree under an existing, safe destination parent.
   The generated destination is checked against every registered checkout for
   ancestor/descendant overlap.
5. Registers the task worktree as a distinct checkout and creates a new
   Registry workspace inheriting the parent's exact immutable configuration
   revision.
6. Persists a task-to-workspace operation record with source revision,
   destination, identities, status, and error provenance.

The source checkout is never used as the task's write target. Task worktrees are
detached so they cannot silently move a project branch. A task ID is unique
within a project.

## Agent execution integration

The coding-agent endpoint and approved-plan execution endpoint can opt into
task isolation:

- `POST /api/v1/agents` accepts `isolate_workspace: true`.
- `POST /api/v1/agents/plans/{plan_id}/execute` accepts
  `isolate_workspace=true` as a query parameter.

When enabled, Evo provisions a task worktree from the selected parent workspace
before creating the runtime invocation snapshot. The run is bound to the new
task workspace—not the parent checkout—and inherits the parent's immutable
configuration revision and project policy. The response includes the task
`workspace_id` and `task_workspace_operation_id`; run metadata also records the
parent workspace, task identity, operation, and pinned source revision.

Before each coding-agent tool action, Evo verifies that the operation record is
still completed and that its task workspace ID, project, pinned source revision,
and canonical destination all match the agent's bound workspace. A missing,
changed, or mismatched operation fails closed before file or command actions;
the operation ID alone cannot redirect an agent into another task worktree.

The destination parent is the configured `workspace.root`, which must already
exist and must not overlap any registered checkout. The parent Git checkout
must be clean. Isolation is currently explicit opt-in for API compatibility;
non-isolated runs retain their existing behavior.

## Failure and recovery

The operation record is created before Git mutates worktree metadata. Failures
before worktree creation are recorded as `failed`. If Git created a worktree
but Registry registration or workspace binding fails, the record remains
`recovery_required`. Evo deliberately does not recursively delete or
automatically remove the worktree: an operator can inspect the exact path and
reconcile the incomplete Registry state.

This v1 operation does not merge, push, deploy, or clean up task worktrees. It
does not claim an OS-level sandbox; it provides revision and checkout
isolation within Evo's Registry model.

## Validation

The test suite covers clean creation, detached revision pinning, source
preservation, dirty and untracked source rejection, invalid revisions,
duplicate task identity, and unsafe destination placement. Local test/build
evidence is required before acceptance.
## Review and execution evidence

The review summary distinguishes passed, failed, not run, not configured, not required, and mixed incomplete verification states. It reports a plan as passed only when every step has passed evidence; missing or mixed evidence is never promoted to success. Command-level evidence separately reports configured-command coverage and result counts. Workspace snapshot evidence is independently classified as `stable`, `changed_or_incomplete`, `incomplete` (a mix of stable and unavailable snapshots), `unavailable`, or `not_available` when no checks were recorded. A command-coverage pass therefore cannot be mistaken for proof that the workspace remained unchanged.

The read-only review endpoint also includes a bounded history of file changes made through Evo's approval-gated task-workspace write paths, including coding-agent tool writes and the task-workspace file API. Each journal entry retains its change ID, path, before/after SHA-256, size, timestamp, and terminal or recovery status. Agent overwrites are approved per action and use an atomic replacement guarded by a file signature; API editor updates additionally require the caller's observed SHA-256. The aggregate distinguishes applied, pending, failed, and indeterminate writes; the history is capped at 500 entries and explicitly reports truncation. This journal is provenance for writes routed through Evo's approved paths, not a complete record of arbitrary filesystem changes or commands that modify files; the Git-based review diff remains authoritative for the workspace's visible changed-file set.

The read-only review endpoint also returns matching agent execution evidence. Each matching run also lists managed command records only when their persisted run, project, task workspace, pinned revision, and working directory match the operation. These records include argv, command policy, timeout, timing, exit status, approval provenance, and bounded stdout/stderr/error output. The review retains at most ten recent managed executions per run and the last 8 KiB of each output stream, reporting omitted records and truncated output explicitly. A run is associated with an operation only when its persisted task-workspace operation ID, project ID, task workspace ID, and pinned source revision agree with the operation record. For orchestrated plans, the plan must additionally point to that same run and workspace. Verification checks include their managed execution ID when one exists. Review resolves it to a persisted execution record only when the run, project, task workspace, pinned revision, working directory, and exact argv match; matching evidence includes the command-policy snapshot, timeout, timing, exit status, and limited approval provenance. Missing or mismatched records are left unlinked rather than guessed. Missing or mismatched provenance is omitted rather than guessed. Verification success remains evidence about the configured command only; it is not a general correctness guarantee. For each managed verification command, Evo records bounded SHA-256 fingerprints of regular files before and after execution. The fingerprint excludes `.git` internals and fails closed when it encounters symlinks, special files, concurrent filesystem changes, or configured file/byte/time limits. Review reports whether both snapshots were complete and identical. This establishes a limited workspace-state comparison, not hermetic execution: external dependencies and transient changes between snapshots are outside this guarantee.


## Local CLI diagnostics

The `evo task-workspaces` command group provides a provider- and desktop-independent,
read-only path for inspecting isolated task workspace operations:

- `evo task-workspaces list` lists recent operations; optional `--project-id`,
  `--status`, and `--limit` filters are available.
- `evo task-workspaces show <operation-id>` reports the recorded operation,
  whether its destination currently exists, and conservative recovery guidance.
- `evo task-workspaces review <operation-id>` prints the bounded read-only review
  artifact for a completed task, including its Git diff and approved file-change journal.

These commands do not resume workers, change operation state, remove worktrees,
or repair Git metadata. A `provisioning` or `recovery_required` operation is
diagnosed only; inspect its destination and Git worktree metadata before any
manual intervention. The CLI intentionally fails rather than guessing at cleanup.
