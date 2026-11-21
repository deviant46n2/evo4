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


## Desktop interface

The React/Vite desktop client is a local web application backed by Evo's loopback-only Python API. The CLI remains fully supported. Current workspaces are Chat, Agents, Memory, Hardware, and Experiments. See [the desktop user guide](docs/DESKTOP-USER-GUIDE.md) for complete setup and behavior.

- **Chat:** persistent conversations, automatic first-message titles, search, rename/delete, streamed Markdown responses, copy controls, keyboard shortcuts, and provider/model/connection status.
- **Agents:** launch the bounded coding agent, inspect run/event history, and approve or deny every write and allowlisted command. Read-only inspection is automatic. Pending approvals expire after ten minutes and default to denial.
- **Memory:** browse/search active, archived, and superseded records; add, archive, supersede, and review tentative candidates. Candidates are not trusted context until accepted.
- **Hardware:** live CPU/RAM/GPU telemetry, GPU compute-process identity/VRAM, warnings, resource-headroom advice, and recorded sample history. Raw process command-line arguments are not exposed.
- **Experiments:** view Evo Lab run history and grouped performance aggregates.

The API binds to `127.0.0.1:8765`, restricts Host headers to loopback names, and allows the local development/preview origins. Provider credentials remain in the Python process and are not sent to the browser. Hardware management is observe-only. Agent pause/resume/redirect, stop-generation, live plan streaming, and in-app provider switching are not implemented; disconnecting the browser does not cancel an in-flight provider request.

Install optional API dependencies and frontend packages:

```bash
python -m pip install -e '.[desktop]'
cd desktop
npm install
```

From the repository root, start the backend in one terminal:

```bash
evo serve
```

In another terminal, run the frontend from `desktop/`:

```bash
cd desktop
npm run dev
```

Open the local Vite address printed in the terminal (normally `http://127.0.0.1:5173`). If the API is already running, do not start a duplicate backend.

### Desktop API

All routes are under `/api/v1`:

- `GET /health`, `GET /capabilities`
- `GET /conversations?limit=100&q=...`, `POST /conversations`
- `GET /conversations/{id}/messages`, `PATCH /conversations/{id}`, `DELETE /conversations/{id}`
- `POST /chat` — server-sent event stream
- `GET/POST /memories`, `POST /memories/{id}/archive`, `POST /memories/{id}/supersede`
- `GET /memory-candidates`, `POST /memory-candidates/{id}/review`
- `GET /agents`, `GET /agents/{run_id}`, `POST /agents`, `POST /agents/{run_id}/approval`
- `GET /hardware/current`, `GET /hardware/history`, `GET /experiments`

The capabilities endpoint reports the current feature contract. The browser is a presentation/client layer; persistence, prompts, memory retrieval, provider calls, and orchestration remain in Python/SQLite.

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

## Current limitations and boundaries

This is a substantial early foundation, not a finished autonomous assistant. Memory and research retrieval are lexical; there is no semantic/vector retrieval, general memory consolidation, automatic contradiction resolution, or source-verifying web research agent. Automatic memory capture is narrow and heuristic. Supersession and contradiction links are user-directed. The memory benchmark is synthetic and does not claim real-world personal-memory recall.

The coding agent is bounded and approval-gated. Tool-call compatibility depends on the selected model/server; the agent is not an unattended worker. The desktop does not currently support stop-generation, pause/resume/redirect for agents, live plan streaming, or in-app provider switching. Closing the browser stream does not guarantee cancellation of an in-flight provider request.

Hardware monitoring is observe-only. It reports telemetry and advisory pressure; it does not kill processes, control GPU clocks/power, stop services, load/unload models, or reconfigure the inference server. There is no resource-aware scheduler yet. The desktop is a local web preview, not a packaged native application.

Context budgeting is a conservative character-based estimate rather than tokenizer-exact accounting. A successful automated test/build does not establish live-model response quality, target-machine compatibility, or browser-level usability.

## Documentation map

- [Project status and validated baseline](docs/PROJECT-STATUS.md)
- [Desktop setup and user guide](docs/DESKTOP-USER-GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Experiment protocol](docs/EXPERIMENT-PROTOCOL.md)
- [Learning and memory design](docs/LEARNING-AND-MEMORY.md)
- [Local handoff and independent review](docs/LOCAL-HANDOFF.md)

## Validation status

The `hardware-observability-v1` baseline at `ce0c05b87b6db8060071d015cfb680dc0261e75d` was independently reviewed: 105 Python unit tests passed (0 failures/errors/skips), Python compileall passed, and the frontend TypeScript/Vite production build passed. The reviewer verdict was **PASS WITH ISSUES**, with no critical bugs identified. Non-blocking findings and the scope of that validation are recorded in [Project status](docs/PROJECT-STATUS.md).

Those results apply only to that exact commit. They do not establish browser visual usability or live-model quality on every configuration. See [the desktop guide](docs/DESKTOP-USER-GUIDE.md) for local run instructions and manual checks.

The research and design rationale is maintained in the [research archive](https://github.com/deviant46n2/airesearchandtesting).
