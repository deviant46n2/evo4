# Evo 4 architecture (substantial-v1)

## Phase 1 objective

Increase the useful capabilities of the user's existing workstation through measured software, inference, memory, and workflow improvements. Self-modification and autonomous self-evolution are not part of Phase 1.

## Applications

### Evo assistant (`src/evo_core`)

- `config.py`: loads the shared TOML configuration.
- `provider.py`: OpenAI-compatible streaming chat adapter.
- `store.py`: durable SQLite state for conversations, messages, memories, tasks, research captures, agent runs, and tool events.
- `assistant.py`: conversation orchestration and lexical memory retrieval.
- `cli.py`: interactive terminal interface and data-management commands.
- `workspace.py`: constrained project workspace API.
- `coding_agent.py`: bounded model-directed tool loop with project orientation, explicit verification policy, approval-gated writes and command execution.
- `run_feedback`: records user assessment of agent outcomes and links reusable lessons to their originating runs.

### Evo Lab (`src/evo_experiments`)

The experiment harness remains independently usable. It runs repeatable tasks, records model/runtime manifests, deterministic checks, timing, and sampled hardware telemetry. Its role is to evaluate both models and future Evo subsystems from outside their implementation.

## Persistence

SQLite is the initial system of record. WAL mode and foreign keys are enabled. Memories retain category, tags, source, confidence, timestamps, and access counts. Conversation messages are append-only. Tasks have explicit status transitions. Research documents retain title, URL, content, source type, and capture time. A SQLite online-backup operation creates a consistent copy of both assistant and lab state.

FTS5 is used for memory retrieval when available. A lexical LIKE fallback keeps the assistant usable when FTS5 is unavailable. Retrieval is not semantic and does not imply perfect recall.

A separate lessons store retains user corrections and experiential rules with trigger phrases, provenance, category, and confidence. Relevant lessons are retrieved into later prompts. Agent runs and tool events form an append-oriented execution record. The `run_feedback` table links explicit user assessments (success, partial, failure) to a run and, optionally, to a reusable lesson created from that assessment. This makes the experiential loop inspectable: run → observed tool history → user assessment/correction → lesson → later retrieval. Lessons created this way carry `user-run-feedback` provenance. Evo does not infer verified success from a model self-report or autonomously promote generated claims into trusted lessons. Saved research documents are also retrieved lexically and injected as source material, with URLs and capture timestamps. A conservative rule-based capture pass detects a limited set of explicit first-person preferences, goals, project facts, and environment statements. These become tentative memory candidates with source, confidence, and conversation provenance. Candidates are excluded from retrieval until accepted. An explicit "remember that ..." request is saved directly as a user-sourced memory. This is a deliberately modest first step, not general automatic memory understanding.

## Provider boundary

The assistant depends on a narrow chat interface and currently ships one OpenAI-compatible SSE provider. This supports llama.cpp and compatible endpoints without coupling application state to a particular model. Additional provider adapters should preserve the same message/result contract.

## Coding-agent loop

The coding agent sends OpenAI-compatible function definitions to the provider and reassembles streamed tool-call deltas. It begins with a bounded project-inspection tool that returns safe top-level entries, a capped file list, and selected project manifests/instructions while excluding ignored and credential-like paths. Its system policy asks it to inspect before editing, minimize scope, run relevant checks, and report only observed outcomes. It supports workspace listing, reading, literal search, writing, and allowlisted command execution. Read-only operations are automatic; writes and commands require an explicit approval callback. Each run and tool event is persisted. Reaching the hard tool-round limit is recorded as a failed/incomplete run, not a completed one.

This is not yet a general autonomous software engineer: tool-call support varies by model/server, command allowlists need local configuration, and no target-machine validation has been performed.

## Workspace safety boundary

Workspace paths are resolved beneath a configured root. Reads are bounded by file size. Writes refuse to overwrite existing files unless explicitly authorized by the caller. Commands are argv arrays, never shell strings, and must match an explicitly configured command prefix. The workspace is a bounded tool foundation; the coding agent drives it through the approval-gated loop described above.

## Data ownership and migration

- Keep experiment history and assistant state durable across application versions.
- Use additive schema migrations when changing existing tables.
- Do not silently reinterpret or delete user memories.
- Preserve provenance and confidence when transforming memory records.
- New agent actions should create auditable tool-event records.
- Avoid coupling the lab database schema to internal assistant implementation details.

## Deliberately not implemented yet

- Automatic memory extraction, deduplication, contradiction resolution, and consolidation.
- Automated outcome adjudication or autonomous lesson promotion; current experiential feedback is explicitly user-confirmed.
- Semantic embeddings/vector retrieval or reranking.
- Browser/web research agent and source verification pipeline.
- Fully autonomous, unattended coding-agent operation; the current loop requires per-action approval.
- Background jobs, task interruption/resumption, and agent scheduler.
- Model loading/unloading and GPU arbitration.
- GUI/web application.
- Autonomous self-modification or online weight training.

These are future layers, not reasons to discard the current foundation.
