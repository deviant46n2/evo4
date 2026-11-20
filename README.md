# Evo 4

Evo 4 is a local-first project to make existing hardware more useful through measured inference optimization and capability engineering.

## First deliverable: inference experiment harness

The first MVP is a small experiment harness, deliberately separate from the eventual assistant application.

### Current capabilities

- Calls an OpenAI-compatible local chat-completions endpoint, initially intended for llama.cpp.
- Runs repeatable JSONL task suites with configurable repetitions.
- Records prompts, responses, model/server identity, configuration snapshot, run status and timing.
- Captures time to first streamed content and token counts when the server supplies usage metadata.
- Samples NVIDIA GPU utilization, VRAM, temperature and power through nvidia-smi.
- Samples system RAM from /proc/meminfo.
- Stores experiment records and timestamped resource samples in SQLite.
- Includes unit tests that do not require a GPU or running model server.
- Uses only the Python standard library at runtime.

### Explicit limitations

- It does not launch, stop, modify or reconfigure llama.cpp.
- It does not measure pure kernel decode speed; timing includes HTTP/streaming overhead.
- Token throughput is calculated only when the server returns completion-token usage metadata. Missing usage remains null, never guessed.
- GPU sampling is periodic and can miss brief peaks.
- It does not isolate background desktop activity or automatically score answer quality.
- It does not yet capture exact model file hashes, full llama.cpp launch flags, context/KV settings, CPU utilization or disk I/O. Those belong in the next iteration after local validation.
- Streaming usage metadata and accepted request fields vary by server version; compatibility must be checked on the target runtime.

## Requirements and install

- Linux recommended (RAM sampling uses /proc/meminfo).
- Python 3.11 or newer.
- nvidia-smi for NVIDIA telemetry (optional).
- A running local server exposing /v1/chat/completions with streaming support.

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config.example.toml config.toml
```

Edit config.toml to match the actual server URL and model name. The example uses port 18997 from the previously documented Qwen profile; verify that it is currently listening before running. Machine-specific config and generated results are git-ignored.

## Commands

```bash
evo-exp hardware
evo-exp init-db
evo-exp run --tasks tasks/smoke.jsonl --repetitions 3
evo-exp report --limit 20
```

Without installing the console command:

```bash
PYTHONPATH=src python -m evo_experiments.cli hardware
PYTHONPATH=src python -m evo_experiments.cli init-db
PYTHONPATH=src python -m evo_experiments.cli run
PYTHONPATH=src python -m evo_experiments.cli report
```

See the [experiment protocol](docs/EXPERIMENT-PROTOCOL.md) for baseline discipline, measurement definitions and interpretation caveats.

## Data model

- experiments: one row per task repetition, including input, response, configuration snapshot, status and timing.
- resource_samples: timestamped GPU/RAM samples linked to the active experiment.

Failed requests are retained for diagnosis. Do not delete failed rows when comparing configurations.

## Validation status

**Code has been added to GitHub but has not been executed on the target CachyOS machine.** Do not treat the harness or its measurements as validated yet.

First validation sequence:
1. Install in a fresh virtual environment.
2. Run `python -m unittest discover -s tests -v`.
3. Run `evo-exp hardware` and inspect GPU/RAM values.
4. Confirm the local server accepts streaming chat completions.
5. Run the smoke suite once and inspect the database.
6. Repeat with fixed settings to estimate run-to-run variance.

The research and design rationale lives in the [research archive](https://github.com/deviant46n2/airesearchandtesting) and its [research-derived implementation plan](https://github.com/deviant46n2/airesearchandtesting/blob/main/design/09-research-derived-implementation-plan.md).
