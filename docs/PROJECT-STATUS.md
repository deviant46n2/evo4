# Evo 4 — project status

**Status date:** 2026-11-21  
**Documentation baseline:** `hardware-observability-v1`, commit `ce0c05b87b6db8060071d015cfb680dc0261e75d`  
**Documentation work:** `documentation-refresh-v1`, branched from that baseline.

This document is the concise source of truth for what exists today, what has been independently checked, and what remains planned. It intentionally separates implemented behavior from roadmap ideas.

## Project purpose and scope

Evo 4 is a local-first assistant and experimental platform intended to increase the useful capabilities of the user's existing workstation. The initial phase prioritizes measurable improvements to local inference workflows, memory, coding assistance, and hardware utilization.

The current system is a substantial early foundation, not a finished autonomous assistant. Autonomous self-modification, online weight training, and unattended self-evolution are out of scope for the current phase.

## Current implementation

### Assistant and persistent state

- OpenAI-compatible streaming chat client; llama.cpp is the initial local target.
- Named provider profiles can select compatible endpoints and model IDs. Credentials can be read from environment variables. Optional cloud-compatible profiles are possible; no paid provider is required.
- SQLite persistence for conversations/messages, memories, memory candidates, lessons, tasks, research notes, agent runs, tool events, and user run feedback.
- Conversation resume, search, rename, and delete.
- Lexical memory, lesson, and saved-research retrieval. SQLite FTS5 is used where available for memory search, with a LIKE fallback.
- Memory records carry category, tags, source, confidence, timestamps, and status. User-directed archive and supersession preserve historical records and links; explicit supports/contradicts relations preserve conflicting evidence.
- A limited heuristic proposes tentative memory candidates from selected explicit first-person statements. Candidates are not trusted context until accepted. Explicit remember requests are saved directly.
- Context assembly uses a conservative character-based estimate, not exact tokenizer accounting.
- User-reviewed run feedback can be converted into provenance-linked reusable lessons. Evo does not autonomously adjudicate outcomes or promote its own claims as trusted lessons.

### Coding agent

- Bounded model-directed tool loop for project inspection, file listing, reading, literal search, writing, and allowlisted command execution.
- Workspace path restrictions, bounded reads, common secret filtering, and argv-based command allowlisting.
- Read-only tools do not require approval. Every file write and command execution requires explicit approval.
- Agent runs and tool events are persisted for review.
- A recognized test-runner command after the latest successful file write can produce a verification signal. This is evidence that a command exited successfully, not proof of correctness or test adequacy.
- The desktop agent worker uses a bounded executor. It is not a general unattended background agent.

### Desktop client and local API

The React/Vite client currently exposes five workspaces:

1. **Chat** — persistent conversations, search/rename/delete, streamed responses, Markdown rendering, provider/model/connection display.
2. **Agents** — launch coding-agent runs, inspect run/event history, and approve or deny pending writes and commands.
3. **Memory** — browse/search active, archived, and superseded memories; add, archive, supersede, and review proposed candidates.
4. **Hardware** — live CPU/RAM/NVIDIA telemetry, GPU compute-process identity and VRAM, pressure warnings, resource headroom advice, and recorded sample history.
5. **Experiments** — Evo Lab run history and grouped performance aggregates.

The API is loopback-only, versioned under `/api/v1`, and serves the browser client. The CLI remains supported. The browser is a client/presentation layer; Python owns provider calls, orchestration, persistence, and agent execution.

The current desktop capability contract explicitly reports that stop-generation and in-app provider switching are not implemented. Closing a browser stream does not cancel an in-flight provider request. Agent pause/resume/redirect and live plan streaming are not implemented.

### Evo Lab and hardware observability

- Repeatable JSONL task suites against an OpenAI-compatible endpoint.
- Experiment records include task/configuration identity, model/server metadata, runtime manifest, status, timings, token usage, deterministic evaluation, and optional model-file hash.
- Time-series telemetry can include NVIDIA utilization, VRAM, temperature, power and compute processes, plus CPU utilization/load and system RAM.
- System CPU/RAM telemetry can be sampled without NVIDIA hardware; GPU fields are unavailable in that case.
- Additive migrations extend existing `resource_samples` tables while preserving prior samples.
- Reports are available as JSONL or CSV, with aggregate summaries.

Hardware recommendations are **observe-only**. Evo currently does not kill processes, set GPU clocks or power limits, stop services, unload models, or reconfigure inference runtimes. Resource-aware scheduling is a future milestone, not an existing capability.

## Validation record

The `hardware-observability-v1` branch was independently reviewed by Kilo at exact HEAD `ce0c05b87b6db8060071d015cfb680dc0261e75d`.

Reported results:

- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`: **105 tests, 0 failures, 0 errors, 0 skipped**.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `cd desktop && npm run build`: passed (`tsc -b` and Vite production build).
- Overall independent verdict: **PASS WITH ISSUES**.
- No critical bugs were identified in the reviewed telemetry, migration, shared-database, endpoint-redaction, or advisory-only behavior.

Non-blocking findings from that review:

- Experiments polling did not have the same in-flight guard as Hardware polling.
- Process-table copy implied command-line details were shown, although the API deliberately omits raw argv.
- The current hardware API's telemetry-known classification requires GPU availability as well as RAM data, so a CPU/RAM-only machine can be reported as unknown.
- Browser-level visual and narrow-window usability testing had not been performed.

The above test results apply to the exact reviewed commit, not automatically to later commits or a different local checkout. They do not establish live-model quality or browser usability.

## Known limitations

- Memory/research retrieval is lexical, not semantic/vector-based.
- Automatic memory capture is narrow and heuristic; no general consolidation, deduplication, or automatic contradiction resolution.
- Memory benchmark fixtures are synthetic and do not measure recall on a real personal-memory collection.
- No source-verifying web research agent.
- Coding-agent tool-call compatibility depends on the selected model/server.
- Per-action approval is required for writes and commands; no unattended coding workflow.
- No persistent background-job scheduler, interruption/resumption, or resource-aware queue.
- No model loading/unloading or GPU arbitration.
- No packaged native desktop application; current UI is a local web development client.
- No automatic provider routing/fallback or capability-based model selection.
- No autonomous self-modification or online training.

## Near-term direction

The next engineering work should be guided by actual use of the interface and a user-reported UI/UX review. A likely subsequent systems milestone is a conservative resource-aware scheduler for Evo-managed work, with inference headroom protection, bounded concurrency, observable decisions, and no arbitrary control over unrelated system processes.

Before scheduling work, address the small documentation/UX validation findings above in a coherent pass rather than representing them as already fixed.

## Branch and change discipline

- Preserve `main`; develop on feature branches.
- Prefer broad, coherent implementation milestones followed by independent validation.
- Record exact branch and commit tested.
- Never report tests, live-model checks, or browser checks as passed unless they were actually run.
- Treat Kilo reports as independent review evidence; distinguish reproduced defects from static-review concerns.
