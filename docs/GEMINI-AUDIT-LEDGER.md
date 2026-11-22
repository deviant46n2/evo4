# Gemini Audit Ledger

Canonical, version-controlled record of the Gemini audit findings for Evo4. This is the single authoritative audit source. Other documents link here rather than duplicating the full audit.

Status values: `confirmed`, `partially confirmed`, `false positive`, `inconclusive`.

Evidence types:
- Source inspection: direct review of current source.
- Existing regression coverage: tests already in repository.
- New tests: tests added during registered-workspace implementation.
- Unverified: not independently executed or not covered.

## A. Experiment metrics

- Subsystem: Evo Lab reporting
- Source: `src/evo_experiments/db.py:117` (`aggregates`)
- Classification: False positive for performance aggregation; status counts are intentionally comprehensive
- Evidence: `aggregates()` reports counts by status and computes elapsed/TTFT/tokens-per-second only over `status='completed'`. Non-completed runs are excluded from performance averages.
- Severity: Low
- Existing tests: experiment DB/report tests
- New tests: None
- Unverified assumptions: None
- Required remediation: None for performance aggregation; optionally clarify report semantics.
- Acceptance criteria: Report distinguishes run counts from completed-run performance.
- Status: Closed as false positive for misleading performance metrics.

## B. Provider streaming reliability

- Subsystem: Provider streaming
- Source: `src/evo_core/provider.py:59-72` (SSE event loop)
- Classification: Confirmed
- Evidence: Source inspection shows events with no `choices` are skipped, including SSE frames containing `{"error": ...}`. An error frame without choices is silently ignored. A response with no choices can leave an empty successful result.
- Severity: High
- Existing tests: Provider tests do not cover error frames without choices.
- New tests: None
- Unverified assumptions: None
- Required remediation: Detect `error` frames and raise `ProviderError`; do not silently accept empty successful responses.
- Acceptance criteria: Error frames surface as provider errors; empty-choice successful responses are rejected or explicitly handled.
- Status: Implemented and accepted in commit `af10694ab35481929e565523c1306cf378b2ddad`.
- Fix: SSE error frames raise `ProviderError`; streams with no valid events are rejected; empty non-truncated completions are rejected; usage-only events and truncated responses are preserved.
- New tests: `tests/test_provider_tools.py` (`ProviderReliabilityTests`: error frame, usage-only then content, empty completion, malformed SSE).

## C. Tool-call argument validation

- Subsystem: Coding agent tool dispatch
- Source: `src/evo_core/coding_agent.py:399-407`; `src/evo_core/provider.py` parses arguments with `json.loads`
- Classification: Confirmed
- Evidence: Provider parses tool-call arguments into arbitrary JSON values. `coding_agent.py` calls `args.keys()` without verifying `args` is a dict, which crashes for non-dict arguments.
- Severity: High
- Existing tests: `tests/test_coding_agent.py` does not cover non-dict arguments.
- New tests: None
- Unverified assumptions: None
- Required remediation: Validate parsed arguments are a dict before dispatch; reject or recover malformed tool calls through the existing malformed-tool-call path.
- Acceptance criteria: Non-dict arguments do not crash the agent; the run records a clear malformed-tool-call outcome.
- Status: Implemented and accepted in commit `af10694ab35481929e565523c1306cf378b2ddad`.
- Fix: tool calls are validated for dict structure, non-empty ID, non-empty function name, and dictionary arguments before dispatch; invalid calls enter bounded recovery and no tool in the response batch executes.
- New tests: `tests/test_coding_agent.py` (`MalformedToolArgumentTests`).

## D. Untrusted retrieved context

- Subsystem: Assistant context construction
- Source: `src/evo_core/assistant.py:75-78` (prompt construction); `src/evo_core/assistant.py:80-130` (`_fit_context`)
- Classification: Partially confirmed
- Evidence: Retrieved memories, lessons, and research are appended to the system prompt. Research is labeled as source material. `_fit_context` applies a conservative character budget and preserves base system policy/current request. However, memory and lesson content is not clearly isolated as untrusted data.
- Severity: Medium
- Existing tests: Assistant/context tests cover budgeting, not injection isolation.
- New tests: None
- Unverified assumptions: Whether current model behavior is affected has not been tested.
- Required remediation: Wrap retrieved context in explicit untrusted-data delimiters while preserving `_fit_context`.
- Acceptance criteria: Retrieved content cannot be mistaken for system instructions; context budget behavior remains intact.
- Status: Partially confirmed; scheduled for investigation/remediation.

## E. Workspace isolation and filesystem boundaries

- Subsystem: Workspace and coding agent
- Source: `src/evo_core/workspace.py:32` (`_is_excluded`); `src/evo_core/workspace.py:52` (`Workspace`); `src/evo_core/workspace.py:74` (`list_files`); `src/evo_core/workspace.py:134` (`search_text`); `src/evo_core/workspace.py:178` (`run`); `src/evo_core/workspace.py:162` (`write_file`)
- Classification: Partially confirmed
- Evidence:
  - `list_files` uses `rglob("*")` and filters ignored paths afterward, so traversal descends into ignored directories before filtering.
  - `_is_excluded` does not exclude SQLite databases, result directories, or other internal/generated files by default.
  - `list_files` and `search_text` silently stop at limits without reporting incompleteness.
  - `resolve` and `write_file` perform path checks, but symlink and parent-creation races remain a documented limitation.
  - `run` matches command prefixes but allows arbitrary additional argv and inherits the process environment.
- Severity: Medium to high, depending on workspace contents
- Existing tests: Workspace tests cover path escape and exclusions partially; no tests for traversal limits or sensitive-file exposure.
- New tests: None
- Unverified assumptions: Whether symlink traversal can escape in practice on the target Python version.
- Required remediation: Restrict traversal, add exclusions for sensitive/internal artifacts, report truncation, and document command/environment boundaries.
- Acceptance criteria: Sensitive files are not exposed; truncation is communicated; command and environment behavior is documented and tested.
- Status: Partially confirmed; scheduled in stabilization roadmap.

- Subsystem: Registered workspace execution boundary
- Source: `src/evo_core/workspaces.py` (`resolve_executable_workspace`); `src/evo_core/api.py` (`start_agent`, `run_agent`, `propose_agent_plan`, `execute_agent_plan`); `src/evo_core/orchestration.py` (`create_plan`, `attach_run`); `desktop/src/Workspaces.tsx` (`AgentsWorkspace`)
- Classification: Implemented and accepted for API execution
- Evidence: API execution requires `workspace_id`; central resolver validates active workspace/project/configuration/revision/checkout and live filesystem canonical path; direct and plan workers re-resolve before `CodingAgent`; legacy plans fail closed. Raw `workspace` paths no longer authorize API execution.
- Severity: N/A (implemented control)
- Existing tests: `tests/test_verification_approval.py`
- New tests: `tests/test_workspace_execution_boundary.py`
- Required remediation: None for the accepted boundary; future hardening remains possible.
- Acceptance criteria: API execution authority is exclusively a valid registered `workspace_id`.
- Status: Accepted.

## F. Experiment lifecycle

- Subsystem: Evo Lab runner
- Source: `src/evo_experiments/runner.py:111` (`except Exception`); `src/evo_experiments/runner.py:123-126` (`finally`, `monitor.stop`, `db.close`)
- Classification: Confirmed
- Evidence: `except Exception` does not catch `KeyboardInterrupt` or `SystemExit`. An interrupted run can leave its experiment row in `running`.
- Severity: Medium
- Existing tests: Runner tests do not cover interruption.
- New tests: None
- Unverified assumptions: None
- Required remediation: Finalize interrupted runs as failed/interrupted in a `BaseException`-aware or explicit `KeyboardInterrupt` path.
- Acceptance criteria: Interrupted experiments are finalized consistently.
- Status: Unresolved; scheduled in stabilization roadmap.

## G. ResourceMonitor lifecycle

- Subsystem: Evo Lab monitoring
- Source: `src/evo_experiments/monitor.py:152-155` (`stop`, `thread.join`)
- Classification: Confirmed potential race
- Evidence: `stop()` joins with a timeout. If the thread is still alive after the timeout, the runner's outer `finally` closes the database while the monitor callback may still access it.
- Severity: Medium
- Existing tests: No dedicated lifecycle test.
- New tests: None
- Unverified assumptions: Whether the timeout has been observed in practice.
- Required remediation: Ensure monitor shutdown completes or database closure waits for monitor termination; document any remaining limitation.
- Acceptance criteria: No database access after shutdown.
- Status: Unresolved; scheduled in stabilization roadmap.

## H. Previously challenged Gemini claims

### H1. Evaluation false positive
- Subsystem: Evaluation
- Source: `src/evo_experiments/evaluation.py:1` (`evaluate_task`)
- Classification: False positive
- Evidence: `evaluate_task` only runs explicitly declared deterministic checks and returns `None` when no checks are declared. It does not judge free-form quality.
- Existing tests: Evaluation tests
- New tests: None
- Status: Closed as false positive.

### H2. Unbudgeted context
- Subsystem: Assistant context
- Source: `src/evo_core/assistant.py:80` (`_fit_context`)
- Classification: False positive
- Evidence: `_fit_context` applies a conservative character budget, preserves base system policy and current request, omits retrieved sections as needed, and reports omitted sections.
- Existing tests: Assistant/context tests
- New tests: None
- Status: Closed as false positive for the claim that context is wholly unbudgeted. Untrusted-content isolation remains a separate partial concern in finding D.

## Additional accepted implementation work

- Registered-workspace execution boundary: implemented and accepted.
- Desktop asynchronous selection-response race correction: implemented and accepted.
- Agent lifecycle reconciliation, verified background coding, build identity, truncated-response safety, malformed-tool-call recovery, and verification completion guards: implemented in the current branch and validated by the test suite.

## Open status

No new feature work is authorized until all confirmed serious unresolved findings are fixed, tested, reviewed, and accepted.
