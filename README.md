# Evo 4

Evo 4 is a local-first assistant and permanent experimental platform for increasing the useful capabilities of existing hardware. Phase 1 is hardware/capability optimization. Autonomous self-modification is explicitly out of scope.

The repository contains two independently usable applications:

- **Evo assistant** (`evo`): local conversations, persistent memory, and task tracking.
- **Evo Lab** (`evo-exp`): reproducible inference experiments, deterministic evaluation, and hardware telemetry. The lab is a permanent subsystem, not disposable scaffolding.

## Current assistant capabilities

- Streams conversations through an OpenAI-compatible endpoint (initial target: llama.cpp).
- Persists conversations and messages in SQLite; resume a conversation by ID.
- Retrieves relevant persistent memories into the model context.
- Stores memories with category, tags, source, confidence, timestamps, and access counts.
- Uses SQLite FTS5 when available, with a LIKE-based fallback.
- Supports explicit memory creation, search, listing, and archival.
- Heuristically captures a small set of explicit first-person preferences, goals, project facts, and environment statements as tentative candidates. Candidates are not injected into model context until accepted; explicit "remember that ..." requests are saved directly with provenance.
- Persists lightweight tasks with priority and status.
- Uses only the Python standard library at runtime.
- Includes an approval-gated coding-agent loop with streamed tool calls for file listing, reading, searching, writing, and running explicitly allowlisted commands.
- Records agent runs and tool-call inputs/outcomes in SQLite for later review.

## Current Evo Lab capabilities

- Calls an OpenAI-compatible local chat-completions endpoint.
- `evo-exp doctor` checks server model discovery.
- Runs repeatable JSONL task suites.
- Records prompts, responses, model/server identity, runtime manifest, status, timing, token usage, and deterministic evaluation.
- Captures optional model-file SHA-256.
- Samples NVIDIA GPU utilization, VRAM, temperature, power, and system RAM.
- Stores experiments and timestamped resource samples in SQLite.
- Produces per-run and aggregate reports as JSONL or CSV.
- Preserves failed runs for diagnosis.

## Requirements and installation

- Linux recommended; RAM telemetry reads `/proc/meminfo`.
- Python 3.11 or newer.
- NVIDIA `nvidia-smi` is optional for GPU telemetry.
- A running local server exposing OpenAI-compatible `/v1/models` and `/v1/chat/completions`.

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config.example.toml config.toml
```

Edit `config.toml`; set `[server].model` to the exact model ID exposed by your server. The experiment manifest is manually supplied; it is not automatically inferred from a running llama.cpp process.

## Evo assistant commands

```bash
evo doctor
evo chat
evo chat --conversation CONVERSATION_ID
evo code --workspace /path/to/project
evo conversations
evo memory add "The user prefers concise, evidence-based explanations" --category preferences --source user
evo memory search "explanation preferences"
evo memory list
evo memory candidates
evo memory accept CANDIDATE_ID
evo memory reject CANDIDATE_ID
evo memory archive MEMORY_ID
evo research add "Paper notes" --url "https://example.org/paper" --content "Sourced notes go here."
evo research search "retrieval performance"
evo task add "Investigate llama.cpp context performance" --priority 2
evo task list
evo task status TASK_ID in_progress
```

The chat interface accepts `/new` and `/exit`. Conversation IDs are printed when exiting and can be used to resume later. The coding interface uses model tool calls; read-only tools run automatically, while every file write and command requires explicit approval. Commands must also match a prefix in `[workspace].allowed_commands`. Tool calls and outcomes are recorded for audit.

## Evo Lab commands

```bash
evo-exp hardware
evo-exp doctor
evo-exp init-db
evo-exp run --tasks tasks/smoke.jsonl --repetitions 3
evo-exp report --limit 20
evo-exp summary --csv > summary.csv
```

See [the experiment protocol](docs/EXPERIMENT-PROTOCOL.md).

## Architecture and boundaries

- `evo_core`: assistant orchestration, provider adapter, configuration, and persistent application state.
- `evo_experiments`: independent experiment runner, evaluation, telemetry, and result aggregation.
- SQLite is the initial durable store. Conversation state, user memories, task state, research captures, agent runs, and tool events have distinct tables.
- Provider access is behind an OpenAI-compatible adapter; model/runtime changes should not require replacing the assistant.
- The lab remains usable to evaluate Evo components from the outside.
- No autonomous code execution or self-modification is enabled in this version.

## Important limitations

This is a substantial early foundation, not a validated finished assistant. It does not yet have a web research agent, coding-agent loop, automatic memory extraction/consolidation, background task execution, model scheduling/unloading, or a graphical UI. Memory retrieval is lexical rather than semantic. The current assistant sends recent conversation history and selected memories; it does not guarantee perfect recall or enforce a hard token budget. Tool calling and autonomous actions are not enabled.

The coding agent depends on OpenAI-compatible streamed tool-call support. Some llama.cpp builds/models may not support the expected tool-call format; this must be tested on the actual endpoint. The agent is bounded by a tool-round limit and is not a background autonomous worker. The streaming client targets common OpenAI-compatible SSE behavior; server-specific quirks must be tested on the actual endpoint. A successful CI run cannot validate the target machine, model, CUDA stack, or real-world response quality.

## Validation status

**No target-machine validation has been performed by this implementation pass.** Automated tests and CI are intended to catch basic regressions, not certify compatibility with your exact runtime. The first local validation should cover installation, `evo doctor`, a multi-turn chat, conversation resume, memory retrieval, task persistence, and the experiment smoke suite.

The research and design rationale is maintained in the [research archive](https://github.com/deviant46n2/airesearchandtesting).
