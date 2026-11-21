# Evo 4

Evo 4 is a local-first assistant and permanent experimental platform for increasing the useful capabilities of existing hardware. Phase 1 is hardware/capability optimization. Autonomous self-modification is explicitly out of scope.

The repository contains two independently usable applications:

- **Evo assistant** (`evo`): local conversations, persistent memory, and task tracking.
- **Evo Lab** (`evo-exp`): reproducible inference experiments, deterministic evaluation, and hardware telemetry. The lab is a permanent subsystem, not disposable scaffolding.

## Current assistant capabilities

- Streams conversations through an OpenAI-compatible endpoint (initial target: llama.cpp); optional named endpoint/model profiles can be selected with `--provider NAME`, with API keys loaded from environment variables.
- Applies a configurable context-window budget, prioritizing persistent context and the current request over older chat history.
- Persists conversations and messages in SQLite; resume a conversation by ID.
- Retrieves relevant persistent memories, user lessons, and saved research notes into the model context.
- Stores memories with category, tags, source, confidence, timestamps, and access counts.
- Uses SQLite FTS5 when available, with a LIKE-based fallback.
- Includes a deterministic synthetic memory-retrieval benchmark reporting hit rate, recall@k, and mean reciprocal rank without touching the live database. It can compare SQLite FTS5 against the relevance-ranked LIKE fallback.
- Supports explicit memory creation, search, listing, and archival. User-directed supersession preserves replaced records and links; explicit supports/contradicts relationships are surfaced when related memories are retrieved.
- Stores user corrections and lessons with trigger phrases, provenance, category, and confidence; relevant lessons are retrieved into future conversations.
- Heuristically captures a small set of explicit first-person preferences, goals, project facts, and environment statements as tentative candidates. Candidates are not injected into model context until accepted; explicit "remember that ..." requests are saved directly with provenance.
- Persists lightweight tasks with priority and status.
- Uses only the Python standard library at runtime.
- Uses SQLite WAL with a 30-second busy timeout to tolerate short-lived contention between assistant and lab processes.
- Includes an approval-gated coding-agent loop with streamed tool calls for project inspection, file listing, reading, searching, writing, and running explicitly allowlisted commands. The agent receives a bounded, secret-filtered project overview and explicit instructions to inspect before editing, verify changes with tests, and report only observed results. After successful file writes, Evo independently reports whether a recognized test/check/build command exited successfully after the latest edit; otherwise the run is explicitly marked unverified or failed.
- Records agent runs and tool-call inputs/outcomes in SQLite for later review.
- Adds an explicit experiential-feedback loop: inspect prior agent runs, record success/partial/failure and user feedback, and optionally turn a verified correction into a reusable lesson linked to that run.

## Current Evo Lab capabilities

- Calls an OpenAI-compatible local chat-completions endpoint.
- `evo-exp doctor` checks server model discovery.
- Runs repeatable JSONL task suites.
- Records prompts, responses, model/server identity, runtime manifest, status, timing, token usage, and deterministic evaluation.
- Captures optional model-file SHA-256.
- Samples NVIDIA GPU utilization, VRAM, temperature, power, compute-process identity/VRAM, CPU utilization, CPU load averages, and system RAM. Telemetry works without NVIDIA hardware for system metrics.
- Stores experiments and timestamped resource samples in SQLite.
- Produces per-run and aggregate reports as JSONL or CSV.
- Preserves failed runs for diagnosis.


### Desktop API additions

The desktop API exposes:
- `GET /api/v1/hardware/current` — live CPU, RAM, NVIDIA GPU, GPU process, active provider/model, resource headroom, and advisory pressure status.
- `GET /api/v1/hardware/history` — recent persisted samples from Evo Lab runs.
- `GET /api/v1/experiments` — recent experiment runs and grouped performance aggregates.

The desktop API initializes/migrates the Evo Lab tables in the same SQLite database used by the assistant. Older experiment databases gain the expanded telemetry columns in place; existing samples are preserved. Hardware polling is read-only. The dashboard deliberately does not expose process command-line arguments, which can contain credentials.

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

Edit `config.toml`; set `[server].model` to the exact model ID exposed by your server, or define named `[providers.NAME]` profiles and select one with `evo chat --provider NAME`, `evo code --provider NAME`, or `evo doctor --provider NAME`. Set `api_key_env` to the name of an environment variable rather than storing cloud credentials in the TOML file. Set `[assistant].context_window_tokens` to the configured model context size; this is a conservative estimate, not tokenizer-exact accounting. The experiment manifest is manually supplied; it is not automatically inferred from a running llama.cpp process.


## Desktop interface (0.1 development milestone)

The desktop client is a React/Vite application backed by Evo's local Python API. The CLI remains fully supported. This milestone provides:

- Persistent conversations with automatic first-message titles.
- Search across conversation titles and message bodies.
- Conversation rename and deletion (including message cleanup).
- Streaming chat with Markdown, GitHub-flavored tables/lists, and readable code blocks.
- Copy-response controls, keyboard send behavior, a new-chat shortcut, loading/error states, and a responsive narrow-window layout.
- Provider/model identity and API connection status.

The desktop now includes functional Agents, Memory, Hardware, and Experiments workspaces:
- Agents can launch the existing bounded coding agent in the configured workspace (or an explicitly entered workspace path), inspect run history and recorded tool events, and approve or deny every file write and allowlisted command. Read-only inspection tools run without approval. Pending approvals expire after ten minutes and are denied by default.
- Memory can search active, archived, and superseded records; add user-sourced memories; archive active records; replace incorrect memories while preserving supersession provenance; and accept or reject automatically proposed candidates. Candidate records are not injected as trusted memory until accepted.\n- Hardware shows live CPU/RAM/GPU metrics, NVIDIA compute processes, pressure warnings, and recorded resource history. Process command-line arguments are deliberately not exposed because they can contain credentials.\n- Experiments displays Evo Lab run history and configuration aggregates, including tokens/sec, time-to-first-token, evaluation outcomes, and sampled VRAM/RAM peaks.
- Chat turns reserve their conversation before executor submission. Conversation deletion and turn reservation are synchronized, so queued work cannot lose its conversation. Chat now validates conversation IDs with a direct indexed lookup rather than scanning a capped history list, and reconciles the completed stream with the persisted transcript.
- Hardware resource management is observe-only in this milestone: Evo recommends deferring work under resource pressure but does not kill processes, change GPU clocks/power limits, stop services, or modify runtime settings. Agent cancellation, pause/resume, live plan streaming, and provider switching are not implemented and are not simulated. Closing the desktop client stops event delivery but does not interrupt an in-flight provider request.

Install the optional API dependencies and frontend packages:

```bash
python -m pip install -e '.[desktop]'
cd desktop
npm install
```

In one terminal, from the repository root, start the API:

```bash
evo serve
```

In another terminal:

```bash
cd desktop
npm run dev
```

Open the local Vite address shown in the terminal (normally `http://127.0.0.1:5173`). The API binds only to `127.0.0.1:8765`, restricts Host headers to loopback names, and allows only the local development/preview origins. Provider credentials remain in the Python process and are never sent to the browser.

### Desktop API

The API is versioned under `/api/v1`. Current routes:

- `GET /health` and `GET /capabilities`
- `GET /conversations?limit=100&q=...`
- `POST /conversations`
- `GET /conversations/{id}/messages`
- `PATCH /conversations/{id}` with a `title`
- `DELETE /conversations/{id}` (returns conflict while that conversation is active)
- `POST /chat` as a server-sent event stream
- `GET/POST /memories`, `POST /memories/{id}/archive`, `POST /memories/{id}/supersede`, `GET /memory-candidates`, and `POST /memory-candidates/{id}/review`
- `GET /agents`, `GET /agents/{run_id}`, `POST /agents`, and `POST /agents/{run_id}/approval`

The capabilities endpoint is the source of truth for which future workspace areas the running backend actually supports. The browser is a presentation/client layer; conversation persistence, prompts, memory retrieval, provider calls, and assistant orchestration remain in Python/SQLite.

## Evo assistant commands

```bash
evo doctor
evo doctor --test-tools
evo chat
evo chat --conversation CONVERSATION_ID
evo code --workspace /path/to/project
evo conversations
evo backup backups/evo.sqlite3
evo memory add "The user prefers concise, evidence-based explanations" --category preferences --source user
evo memory search "explanation preferences"
evo memory list
evo memory candidates
evo memory accept CANDIDATE_ID
evo memory reject CANDIDATE_ID
evo memory archive MEMORY_ID
evo memory supersede OLD_ID "Replacement fact" --reason "User corrected the previous fact."
evo memory relate MEMORY_ID OTHER_ID --relation contradicts --evidence "Conflicting user-provided records."
evo memory relations MEMORY_ID
evo memory evaluate --cases tasks/memory-retrieval.json --top-k 5 --backend auto
# Compare the LIKE fallback independently:
evo memory evaluate --cases tasks/memory-retrieval.json --top-k 5 --backend fallback
evo learn add "Run tests before claiming success" --trigger "coding tests" --category coding
evo learn search "coding tests"
evo runs list --limit 20
evo runs summary
evo runs show RUN_ID
evo runs review RUN_ID --outcome failure --feedback "A targeted test passed but the full suite found a regression." --lesson "Run the full existing test suite after targeted checks." --trigger "coding regression tests"
evo research add "Paper notes" --url "https://example.org/paper" --content "Sourced notes go here."
evo research search "retrieval performance"
evo task add "Investigate llama.cpp context performance" --priority 2
evo task list
evo task status TASK_ID in_progress
```

The chat interface accepts `/new` and `/exit`. Conversation IDs are printed when exiting and can be used to resume later. The coding interface uses model tool calls; `evo doctor --test-tools` runs a harmless compatibility probe. Read-only tools run automatically, while every file write and command requires explicit approval. Commands must also match a prefix in `[workspace].allowed_commands`. Tool calls and outcomes are recorded for audit. A successful verification signal means a recognized check command exited zero after the latest file write; it is not proof that the change is correct.

## Evo Lab commands

```bash
evo-exp hardware
evo-exp doctor
evo-exp init-db
evo-exp run --tasks tasks/smoke.jsonl --repetitions 3
evo-exp report --limit 20
evo-exp summary --csv > summary.csv
```

See [the experiment protocol](docs/EXPERIMENT-PROTOCOL.md) and [the learning/memory implementation notes](docs/LEARNING-AND-MEMORY.md).

## Architecture and boundaries

- `evo_core`: assistant orchestration, provider adapter, configuration, and persistent application state.
- `evo_experiments`: independent experiment runner, evaluation, telemetry, and result aggregation.
- SQLite is the initial durable store. Conversation state, user memories and their explicit relations, task state, research captures, agent runs, tool events, and user run feedback have distinct tables.
- Provider access is behind an OpenAI-compatible adapter; model/runtime changes should not require replacing the assistant.
- The lab remains usable to evaluate Evo components from the outside.
- No unapproved code execution, background autonomous operation, or self-modification is enabled in this version.

## Important limitations

This is a substantial early foundation, not a validated finished assistant. It does not yet have a web research agent, semantic memory retrieval, robust automatic memory consolidation or contradiction resolution, background task execution, model scheduling/unloading, or a graphical UI. Memory and research retrieval are lexical. Supersession and contradiction links are user-directed; Evo does not automatically decide which conflicting fact is true. Automatic memory capture is a small heuristic that creates tentative candidates; it is not general language understanding. The current assistant sends recent conversation history and selected memories/lessons/research; history and retrieved records have conservative character limits, not exact tokenizer-based token budgeting.

Experiential learning is deliberately user-grounded at this stage: Evo does not decide on its own that a task succeeded or promote its own speculation into trusted lessons. A user can review an agent run and record its outcome; an optional lesson is stored with `user-run-feedback` provenance and linked to the feedback record. This creates a traceable correction loop, not autonomous self-training.

The coding agent depends on OpenAI-compatible streamed tool-call support. Some llama.cpp builds/models may not support the expected tool-call format; this must be tested on the actual endpoint. The agent is bounded by a tool-round limit; reaching that limit is recorded as a failed/incomplete run rather than success. It is not a background autonomous worker. The streaming client targets common OpenAI-compatible SSE behavior; server-specific quirks must be tested on the actual endpoint. A successful CI run cannot validate the target machine, model, CUDA stack, or real-world response quality.

## Validation status

**The base branch at 20a3991 was independently exercised against the user's Qwen3.8-27B llama.cpp server. The additions on this branch have not yet been validated against that live model.** Automated tests and CI are intended to catch basic regressions, not certify compatibility with your exact runtime. The first local validation should cover installation, `evo doctor`, a multi-turn chat, conversation resume, memory retrieval, task persistence, and the experiment smoke suite.

The memory benchmark is intentionally synthetic and isolated: it is a regression fixture for comparing retrieval implementations, not a claim about recall over a real user memory collection. The next step is to add user-curated held-out queries and measure retrieval against actual Evo memory records with consent.

The research and design rationale is maintained in the [research archive](https://github.com/deviant46n2/airesearchandtesting).


## Sample workspace data

Fresh installations can load reversible, clearly labeled sample memories, agent history, experiment results, and historical telemetry from the Memory, Agents, Hardware, and Experiments workspaces. Sample records are persisted in the configured SQLite database with explicit demo provenance; they are not real user activity or live hardware measurements. Use the workspace banner to load or remove them. See [the sample-data guide](docs/DEMO-DATA.md).
