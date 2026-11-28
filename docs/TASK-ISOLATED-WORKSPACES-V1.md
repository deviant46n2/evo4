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
