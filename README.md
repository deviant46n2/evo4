# Evo 4

Evo 4 is a local-first project to make existing hardware more useful through measured inference optimization and capability engineering.

## First deliverable: inference experiment harness

The first MVP is a small experiment harness, deliberately separate from the eventual assistant application.

### Current capabilities

- Calls an OpenAI-compatible local chat-completions endpoint, initially intended for llama.cpp.
- `evo-exp doctor` checks the server's model-list endpoint and warns if the configured model ID is not exposed.
- Runs repeatable JSONL task suites with configurable repetitions.
- Records prompts, responses, model/server identity, runtime manifest, run status and timing.
- Captures an optional model-file SHA-256 when `[run].model_file` is configured.
- Samples NVIDIA GPU utilization, VRAM, temperature and power through nvidia-smi.
- Samples system RAM from /proc/meminfo.
- Stores experiment records, deterministic task-check results and timestamped resource samples in SQLite.
- Provides per-run reports and aggregate summaries grouped by configuration label and task category, including sampled peak VRAM, RAM and average GPU utilization.
- Reports results as JSON Lines or CSV.
- Includes unit tests for configuration, manifest hashing, SQLite concurrency, task validation and a local fake OpenAI-compatible streaming server.
- Uses only the Python standard library at runtime.

### Explicit limitations

- It does not launch, stop, modify or reconfigure llama.cpp.
- It does not measure pure kernel decode speed; timing includes HTTP/streaming overhead.
- Token throughput is calculated only when the server returns completion-token usage metadata. Missing usage remains null, never guessed.
- GPU sampling is periodic and can miss brief peaks.
- It does not isolate background desktop activity or automatically score open-ended answer quality. Optional exact/substring checks are deliberately limited and transparent.
- It does not yet capture CPU utilization, disk I/O, per-process VRAM, or automatically parse the llama.cpp launch command. Fill in the runtime manifest manually for now.
- Streaming usage metadata and accepted request fields vary by server version; compatibility must be checked on the target runtime.

## Requirements and install

- Linux recommended (RAM sampling uses /proc/meminfo).
- Python 3.11 or newer.
- nvidia-smi for NVIDIA telemetry (optional).
- A running local server exposing /v1/models and /v1/chat/completions with streaming support.

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config.example.toml config.toml
```

Edit config.toml. Run `evo-exp doctor` to see the model IDs exposed by the server, then set `[server].model` to the exact ID. Fill in the `[run]` section with the actual model file, runtime version, launch command and settings. Do not guess missing values. If `model_file` is nonempty, the harness computes its SHA-256 once at the start of each benchmark invocation. Machine-specific config and generated results are git-ignored.

## Commands

```bash
evo-exp hardware
evo-exp doctor
evo-exp init-db
evo-exp run --tasks tasks/smoke.jsonl --repetitions 3
evo-exp report --limit 20
evo-exp summary --csv > summary.csv
evo-exp report --limit 100 --csv > results.csv
```

Without installing the console command:

```bash
PYTHONPATH=src python -m evo_experiments.cli hardware
PYTHONPATH=src python -m evo_experiments.cli doctor
PYTHONPATH=src python -m evo_experiments.cli init-db
PYTHONPATH=src python -m evo_experiments.cli run
PYTHONPATH=src python -m evo_experiments.cli report
PYTHONPATH=src python -m evo_experiments.cli summary
```

See the [experiment protocol](docs/EXPERIMENT-PROTOCOL.md) for baseline discipline, measurement definitions and interpretation caveats.

## Data model

- experiments: one row per task repetition, including input, response, configuration snapshot, status and timing.
- resource_samples: timestamped GPU/RAM samples linked to the active experiment.

Failed requests are retained for diagnosis. Do not delete failed rows when comparing configurations.

## Validation status

**Code has been added to GitHub but has not been executed on the target CachyOS machine.** GitHub Actions validates the standard-library tests, including a simulated local streaming server, but not your actual llama.cpp build, model or driver.

First validation sequence:
1. Install in a fresh virtual environment.
2. Run `python -m unittest discover -s tests -v`.
3. Run `evo-exp hardware` and inspect GPU/RAM values.
4. Run `evo-exp doctor` and confirm the expected model ID appears.
5. Fill in the actual runtime manifest.
6. Run the smoke suite once and inspect the database.
7. Repeat with fixed settings to estimate run-to-run variance.

The research and design rationale lives in the [research archive](https://github.com/deviant46n2/airesearchandtesting) and its [research-derived implementation plan](https://github.com/deviant46n2/airesearchandtesting/blob/main/design/09-research-derived-implementation-plan.md).
