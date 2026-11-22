# Gemini Audit Ledger

Canonical, version-controlled record of the Gemini audit findings for Evo4. This is the single authoritative audit source. Other documents link here rather than duplicating the full audit.

Status values: `confirmed`, `partially confirmed`, `false positive`, `inconclusive`.

## A. Experiment metrics

- Subsystem: Evo Lab reporting
- Source: `src/evo_experiments/db.py` (`aggregates`)
- Classification: False positive for performance aggregation; status counts are intentionally comprehensive
- Evidence: `aggregates()` reports run counts by status (`completed`, `failed`, `running`, `truncated`, `incomplete`, `unknown`) and computes elapsed/TTFT/tokens-per-second only over `status='completed'`. Performance aggregates exclude non-completed runs.
- Severity: Low
- Regression tests: Existing experiment DB tests
- Status: Closed as false positive for misleading performance metrics. Status-count semantics are intentional and visible.

## B. Provider streaming reliability

- Subsystem: Provider streaming
- Source: `src/evo_core/provider.py` (SSE event loop)
- Classification: Confirmed
- Evidence: Events with no `choices` are skipped with `continue`, including SSE frames containing `{"error": ...}`. An error frame without choices is silently ignored. A response with no choices can therefore leave an empty successful result.
- Severity: High
- Regression tests: No dedicated test currently
- Required remediation: Detect `error` frames and raise `ProviderError`; do not silently accept empty successful responses.
- Acceptance criteria: Error frames surface as provider errors; empty-choice successful responses are rejected or explicitly handled.
- Status: Unresolved; scheduled in stabilization roadmap.

## C. Tool-call argument validation

- Subsystem: Coding agent tool dispatch
- Source: `src/evo_core/coding_agent.py` around tool-call dispatch; `src/evo_core/provider.py` parses arguments with `json.loads`
- Classification: Confirmed
- Evidence: Provider parses tool-call arguments into arbitrary JSON values. `coding_agent.py` calls `args.keys()` without verifying `args` is a dict, which crashes for non-dict arguments.
- Severity: High
- Regression tests: No dedicated test currently
- Required remediation: Validate parsed arguments are a dict before dispatch; reject or recover malformed tool calls through the existing malformed-tool-call path.
- Acceptance criteria: Non-dict arguments do not crash the agent; the run records a clear malformed-tool-call outcome.
- Status: Unresolved; scheduled in stabilization roadmap.

## D. Untrusted retrieved context

- Subsystem: Assistant context construction
- Source: `src/evo_core/assistant.py` (`_fit_context`, memory/lesson/research block construction)
- Classification: Partially confirmed
- Evidence: Retrieved memories, lessons, and research are appended to the system prompt. Research is labeled as source material. `_fit_context` does budget context and never silently truncates the base system policy or current request. However, memory and lesson content is not clearly isolated as untrusted data.
- Severity: Medium
- Regression tests: Existing assistant/context tests
- Required remediation: Wrap retrieved context in explicit untrusted-data delimiters and preserve `_fit_context` budgeting.
- Acceptance criteria: Retrieved content cannot be mistaken for system instructions; context budget behavior remains intact.
- Status: Partially confirmed; scheduled for investigation/remediation.

## E. Workspace isolation and filesystem boundaries

- Subsystem: Workspace and coding agent
- Source: `src/evo_core/workspace.py` (`list_files`, `search_text`, `resolve`, `write_file`, `run`, `_is_excluded`, `_looks_sensitive_name`)
- Classification: Partially confirmed
- Evidence:
  - `list_files` uses `rglob("*")` and filters ignored paths afterward, so traversal descends into ignored directories before filtering.
  - `_is_excluded` does not exclude SQLite databases, result directories, or other internal/generated files by default.
  - `list_files` and `search_text` silently stop at limits without reporting incompleteness.
  - `resolve` and `write_file` perform path checks, but symlink and parent-creation races remain a documented limitation.
  - `run` matches command prefixes but allows arbitrary additional argv and inherits the process environment.
- Severity: Medium to high, depending on workspace contents
- Regression tests: Workspace tests exist; no tests for traversal limits or sensitive-file exposure
- Required remediation: Restrict traversal, add exclusions for sensitive/internal artifacts, report truncation, and document command/environment boundaries.
- Acceptance criteria: Ignored/sensitive files are not exposed; truncation is communicated; command and environment behavior is documented and tested.
- Status: Partially confirmed; scheduled in stabilization roadmap.

- Subsystem: Registered workspace execution boundary
- Source: `src/evo_core/workspaces.py`, `src/evo_core/api.py`, `src/evo_core/orchestration.py`, `desktop/src/Workspaces.tsx`
- Classification: Implemented and accepted for API execution
- Evidence: API execution requires `workspace_id`; central resolver validates active workspace/project/configuration/revision/checkout and live filesystem canonical path; direct and plan workers re-resolve before `CodingAgent`; legacy plans fail closed. Raw `workspace` paths no longer authorize API execution.
- Severity: N/A (implemented control)
- Regression tests: `tests/test_workspace_execution_boundary.py`
- Status: Accepted.

## F. Experiment lifecycle

- Subsystem: Evo Lab runner
- Source: `src/evo_experiments/runner.py`
- Classification: Confirmed
- Evidence: `except Exception` does not catch `KeyboardInterrupt` or `SystemExit`. An interrupted run can leave its experiment row in `running`.
- Severity: Medium
- Regression tests: No dedicated interruption test
- Required remediation: Finalize interrupted runs as failed/interrupted in a `BaseException`-aware or explicit `KeyboardInterrupt` path.
- Acceptance criteria: Interrupted experiments are finalized consistently.
- Status: Unresolved; scheduled in stabilization roadmap.

## G. ResourceMonitor lifecycle

- Subsystem: Evo Lab monitoring
- Source: `src/evo_experiments/monitor.py`
- Classification: Confirmed potential race
- Evidence: `stop()` joins with a timeout. If the thread is still alive after the timeout, the runner's outer `finally` closes the database while the monitor callback may still access it.
- Severity: Medium
- Regression tests: No dedicated lifecycle test
- Required remediation: Ensure monitor shutdown completes or database closure waits for monitor termination; document any remaining limitation.
- Acceptance criteria: No database access after shutdown.
- Status: Unresolved; scheduled in stabilization roadmap.

## H. Previously challenged Gemini claims

### H1. Evaluation false positive
- Subsystem: Evaluation
- Source: `src/evo_experiments/evaluation.py`
- Classification: False positive
- Evidence: `evaluate_task` only runs explicitly declared deterministic checks and returns `None` when no checks are declared. It does not judge free-form quality.
- Status: Closed as false positive.

### H2. Unbudgeted context
- Subsystem: Assistant context
- Source: `src/evo_core/assistant.py` (`_fit_context`)
- Classification: False positive
- Evidence: `_fit_context` applies a conservative character budget, preserves base system policy and current request, omits retrieved sections as needed, and reports omitted sections.
- Status: Closed as false positive for the claim that context is wholly unbudgeted. Untrusted-content isolation remains a separate partial concern in finding D.

## Additional accepted implementation work

- Registered-workspace execution boundary: implemented and accepted.
- Desktop asynchronous selection-response race correction: implemented and accepted.
- Agent lifecycle reconciliation, verified background coding, build identity, truncated-response safety, malformed-tool-call recovery, and verification completion guards: implemented in the current branch and validated by the test suite.

## Open status

No new feature work is authorized until all confirmed serious unresolved findings are fixed, tested, reviewed, and accepted.
