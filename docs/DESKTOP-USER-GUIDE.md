# Evo 4 desktop — local user guide

This guide describes the desktop preview present in the `hardware-observability-v1` baseline. It is a local web application, not a packaged native desktop app.

## Requirements

- Python 3.11 or newer.
- Node.js and npm compatible with the versions required by the Vite project.
- A configured OpenAI-compatible model server. The initial target is a local llama.cpp server.
- The repository cloned locally.

## First-time setup

Run from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[desktop]'
cp config.example.toml config.toml
```

Edit `config.toml`:
- Set `[server].base_url` to the OpenAI-compatible API base URL (the example uses `http://127.0.0.1:18997`).
- Set `[server].model` to the exact model ID exposed by that server.
- Set `[experiment].database` to the SQLite database path you want Evo to use.
- Set `[workspace].root` to the project directory the coding agent may access.
- Review `[workspace].allowed_commands`; only explicitly allow commands you are comfortable approving and running.
- For a named provider profile, configure `[providers.NAME]` and put credentials in the environment variable named by `api_key_env`. Do not commit secrets.

The sample configuration is illustrative. It does not discover the running model automatically, and the context-window setting is a conservative application budget rather than tokenizer-exact accounting.

## Start Evo

The backend and frontend are separate processes. Keep each terminal open while using the application.

**Terminal 1 — backend**, from the repository root:

```bash
source .venv/bin/activate
evo serve
```

The API binds to `127.0.0.1:8765`.

**Terminal 2 — frontend**, also from the repository root:

```bash
cd desktop
npm install
npm run dev
```

Open the local Vite URL printed by the command; normally `http://127.0.0.1:5173`.

If the repository is in `~/Projects/evo4`, the frontend directory is `~/Projects/evo4/desktop`, not `~/evo4/desktop`. Run npm commands from the `desktop` directory because its `package.json` is there.

If the API is already running, do not start a duplicate backend. Start only the frontend terminal.

## Workspaces

### Chat

Create conversations, search existing titles/message text, rename or delete conversations, and stream assistant responses. Responses support Markdown and GitHub-flavored tables/lists. The header displays configured provider/model and API connection status.

There is no stop-generation control in this version. Closing the tab or stream does not guarantee that the provider request is cancelled; the backend may continue and persist the response.

### Agents

Start a bounded coding-agent run against the configured workspace or a workspace path supplied for that run. The agent can inspect/list/read/search files without approval. Each file write and allowlisted command requires an explicit approval decision. Runs and tool events remain available for inspection.

The current lifecycle/history display should not be interpreted as support for pause, resume, redirect, or unattended background work. Pending approval requests time out and are denied by default. Only commands matching the configured argv-prefix allowlist can execute.

### Memory

Search and browse active, archived, and superseded records. Add user-provided memories, archive active memories, replace a memory while retaining its history, and review tentative candidates.

Candidate acceptance makes a candidate eligible as a trusted memory; rejection discards the pending proposal. Candidate extraction is heuristic and limited. It is not comprehensive automatic memory formation.

### Hardware

View current CPU, RAM, and available NVIDIA metrics, compute-process identity/VRAM, resource warnings, and recorded telemetry history. GPU process command-line arguments are intentionally not exposed because they may contain credentials.

The resource budget is advisory. It does not control the operating system, inference server, GPU clocks, or other processes. A first CPU utilization sample may be unavailable until a later sample provides a counter delta.

### Experiments

Review Evo Lab runs and grouped performance aggregates. Experiments are created through the `evo-exp` CLI; the desktop workspace is a viewer in this milestone, not a full experiment editor/launcher.

## Useful CLI checks

From the repository root with the virtual environment active:

```bash
evo doctor
evo doctor --test-tools
evo chat
evo code --workspace /path/to/project
evo-exp hardware
evo-exp doctor
evo-exp run --tasks tasks/smoke.jsonl --repetitions 1
evo-exp report --limit 20
evo-exp summary
```

`evo doctor` checks model discovery. `evo doctor --test-tools` probes function-calling compatibility; actual coding-agent behavior still depends on the model/server.

## Troubleshooting

- **`cd: .../evo4/desktop: No such file or directory`** — use the actual clone location. Find it with `pwd` from the repository root or `find ~/Projects -maxdepth 3 -name package.json`.
- **npm says it cannot find `package.json`** — you are not inside `desktop/`. Run `cd /path/to/evo4/desktop` first.
- **Frontend loads but says API offline** — check that `evo serve` is running in the other terminal and that it is listening on `127.0.0.1:8765`.
- **Model request fails** — verify the model server is running, `[server].base_url` is correct, and `[server].model` exactly matches `evo doctor` output.
- **Agent cannot run a command** — inspect `[workspace].allowed_commands`; command prefixes are intentionally restrictive. Approving a request does not bypass the allowlist.
- **Hardware fields are missing** — NVIDIA fields require a working `nvidia-smi`; CPU/RAM telemetry is Linux-oriented and reads `/proc`. Missing metrics should be treated as unavailable, not zero.

## Stop

Stop the frontend and backend independently with `Ctrl+C` in their respective terminals. Stopping the browser frontend does not necessarily cancel work already running in the backend.
