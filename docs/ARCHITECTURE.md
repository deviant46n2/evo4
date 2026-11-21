# Evo 4 architecture (hardware-observability-v1 baseline)

## Phase 1 objective

Increase the useful capabilities of the user's existing workstation through measured software, inference, memory, and workflow improvements. Self-modification and autonomous self-evolution are not part of Phase 1.

## Applications

### Evo assistant (`src/evo_core`)

- `config.py`: loads the shared TOML configuration, including selectable named OpenAI-compatible provider profiles; profile secrets are read from environment variables.
- `provider.py`: OpenAI-compatible streaming chat adapter.
- `store.py`: durable SQLite state for conversations, messages, memories, tasks, research captures, agent runs, and tool events.
- `assistant.py`: conversation orchestration and lexical memory retrieval.
- `memory_eval.py`: deterministic synthetic retrieval benchmark (hit rate, recall@k, MRR) isolated from the user's live database.
- `cli.py`: interactive terminal interface and data-management commands.
- `workspace.py`: constrained project workspace API.
- `coding_agent.py`: bounded model-directed tool loop with project orientation, explicit verification policy, approval-gated writes and command execution.
- `run_feedback`: records user assessment of agent outcomes and links reusable lessons to their originating runs.

### Evo Lab (`src/evo_experiments`)

The experiment harness remains independently usable. It runs repeatable tasks, records model/runtime manifests, deterministic checks, timing, and sampled hardware telemetry. Its role is to evaluate both models and future Evo subsystems from outside their implementation.

## Persistence

SQLite is the initial system of record. WAL mode and foreign keys are enabled. Memories retain category, tags, source, confidence, timestamps, and access counts. User-directed supersession marks the old record as superseded, creates a replacement, and stores an explicit relation so the history is not destroyed. Users can also mark two records as supporting or contradicting; retrieved relations are shown to the model as explicit evidence, not silently resolved. Conversation messages are append-only. Tasks have explicit status transitions. Research documents retain title, URL, content, source type, and capture time. A SQLite online-backup operation creates a consistent copy of both assistant and lab state.

Context construction now applies a configurable conservative character-based budget derived from `assistant.context_window_tokens`. The base system policy and current request are retained; retrieved memory/relations/lessons/research take priority over older conversation history, which is trimmed oldest-first. The estimate uses approximately 3.5 characters per token and is not a substitute for the target model's tokenizer or server-side context accounting.

FTS5 is used for memory retrieval when available. A relevance-ranked lexical LIKE fallback searches memory content, categories, and tags when FTS5 is unavailable. The synthetic benchmark can force either backend so regressions can be compared independently. Retrieval is not semantic and does not imply perfect recall. `evo memory evaluate` seeds an isolated in-memory database from a versioned synthetic fixture and reports hit rate, recall@k, and mean reciprocal rank. It is a retrieval regression test, not a measurement of real-world personal-memory recall.

A separate lessons store retains user corrections and experiential rules with trigger phrases, provenance, category, and confidence. Relevant lessons are retrieved into later prompts using query-match relevance before confidence/recency tie-breakers. Saved research similarly ranks title matches ahead of content-only matches. Agent runs and tool events form an append-oriented execution record. The `run_feedback` table links explicit user assessments (success, partial, failure) to a run and, optionally, to a reusable lesson created from that assessment. This makes the experiential loop inspectable: run → observed tool history → user assessment/correction → lesson → later retrieval. `evo runs summary` aggregates run status, verification signals, review coverage, feedback outcomes, and average tool-call counts so later iterations can be compared against a growing record. Lessons created this way carry `user-run-feedback` provenance. Evo does not infer verified success from a model self-report or autonomously promote generated claims into trusted lessons. Saved research documents are also retrieved lexically and injected as source material, with URLs and capture timestamps. A conservative rule-based capture pass detects a limited set of explicit first-person preferences, goals, project facts, and environment statements. These become tentative memory candidates with source, confidence, and conversation provenance. Candidates are excluded from retrieval until accepted. An explicit "remember that ..." request is saved directly as a user-sourced memory. This is a deliberately modest first step, not general automatic memory understanding.

## Provider boundary

The assistant depends on a narrow chat interface and currently ships one OpenAI-compatible SSE provider. This supports llama.cpp and compatible endpoints without coupling application state to a particular model. Named profiles in `[providers.*]` can select different compatible endpoints and model IDs at launch with `--provider NAME`; secrets are loaded from environment variables using `api_key_env`. This makes optional free/cloud-compatible endpoints pluggable without making them a dependency. It is not yet a multi-provider router or automatic fallback system, and non-OpenAI-compatible providers still need an adapter.

## Coding-agent loop

The coding agent sends OpenAI-compatible function definitions to the provider and reassembles streamed tool-call deltas. It begins with a bounded project-inspection tool that returns safe top-level entries, a capped file list, and selected project manifests/instructions while excluding ignored and credential-like paths. Its system policy asks it to inspect before editing, minimize scope, run relevant checks, and report only observed outcomes. It supports workspace listing, reading, literal search, writing, and allowlisted command execution. Read-only operations are automatic; writes and commands require an explicit approval callback. Each run and tool event is persisted. After successful writes, Evo tracks the latest write and any later recognized test-runner command, recording a verification signal of passed, failed, or not_run. Lint-only commands and `git diff --check` no longer count as test verification. This remains a command-pattern heuristic: exit code zero is evidence that a test runner completed, not proof that the tests cover the changed behavior or that the implementation is correct. Reaching the hard tool-round limit is recorded as a failed/incomplete run, not a completed one.

This is not yet a general autonomous software engineer: tool-call support varies by model/server, command allowlists need local configuration, and no target-machine validation has been performed.

## Workspace safety boundary

Workspace paths are resolved beneath a configured root. Reads are bounded by file size. Secret filtering covers common credential names and token/password/private-key filename patterns. Test/spec paths require an explicit approved write; the CLI calls out these writes separately, and the agent policy forbids weakening assertions or disabling tests. Writes refuse to overwrite existing files unless explicitly authorized by the caller. Commands are argv arrays, never shell strings, and must match an explicitly configured command prefix. The workspace is a bounded tool foundation; the coding agent drives it through the approval-gated loop described above.

## Data ownership and migration

- Keep experiment history and assistant state durable across application versions.
- Use additive schema migrations when changing existing tables.
- Do not silently reinterpret or delete user memories. Superseded records remain stored and linked to their replacements; contradiction links preserve both claims.
- Preserve provenance and confidence when transforming memory records.
- New agent actions should create auditable tool-event records.
- Avoid coupling the lab database schema to internal assistant implementation details.

## Desktop API and client

The React/Vite desktop client is a local web application served by a loopback-only FastAPI service. It currently exposes Chat, Agents, Memory, Hardware, and Experiments workspaces. The CLI remains supported; the browser is not the system of record.

The API provides health/capability discovery, conversation CRUD/search and SSE chat, memory browsing/mutation/candidate review, coding-agent run history and approval, hardware telemetry/history, and experiment summaries. The full route inventory and startup instructions are in the root README and [desktop user guide](DESKTOP-USER-GUIDE.md).

The API uses a bounded thread pool for blocking provider and agent work. Chat conversation reservations synchronize queued/in-flight turns against deletion. Agent writes and allowlisted commands require per-action approval; pending approvals time out and default to denial. The desktop does not currently expose generation cancellation or agent pause/resume/redirect.

Hardware telemetry is read-only. Resource advice is advisory and does not enact scheduling or system-level controls. The API initializes Evo Lab tables in the configured SQLite database and applies additive telemetry migrations so prior experiment samples remain available.

## Deliberately not implemented yet

- Semantic/vector memory retrieval, robust consolidation, deduplication, or automatic contradiction resolution.
- General automatic memory understanding; current candidate extraction is a narrow heuristic.
- Automated outcome adjudication or autonomous lesson promotion; experiential feedback is user-confirmed.
- Browser/web research agent and source-verification pipeline.
- Unattended coding-agent operation, pause/resume/redirect, or background-job scheduler.
- Resource-aware scheduling, GPU arbitration, model loading/unloading, or process/service control.
- Stop-generation and in-app provider switching.
- Automatic provider routing/fallback or capability-based model selection.
- Packaged native desktop application.
- Autonomous self-modification or online weight training.

These are future layers, not existing behavior.
