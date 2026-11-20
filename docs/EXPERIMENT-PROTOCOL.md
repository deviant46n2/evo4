# Experiment protocol

## Purpose

Keep comparisons reproducible and prevent noisy measurements from being mistaken for real improvements. This harness records observations; it does not decide which model or configuration is best.

## Before a run

1. Record the exact model file and quantization in the experiment notes.
2. Record the llama.cpp build/version and complete launch command.
3. Record context size, KV-cache types, GPU-layer count, batch/ubatch, flash-attention setting and any speculative-decoding options.
4. Keep the same desktop state for paired comparisons. Note GPU-heavy applications and unusual background activity.
5. Use the same task file, system prompt, generation limit and temperature.
6. Warm up the model consistently before collecting comparison runs.
7. Do not run two model benchmarks concurrently on the single GPU.

The current MVP stores a manually supplied runtime manifest with each experiment. It does not introspect the running llama.cpp process, so verify every value against the actual launch command and server configuration.

## Recommended first sequence

1. Capture idle GPU/RAM telemetry with `evo-exp hardware`.
2. Run `evo-exp doctor` and verify the exposed model ID.
3. Run the smoke suite once to verify endpoint compatibility.
4. Run the fixed suite three times with no configuration changes.
5. Inspect per-run results and `evo-exp summary`, including VRAM/RAM samples.
6. Repeat only after changing one major variable.
7. Preserve failed and incomplete runs; do not delete inconvenient results.

## Interpretation

- Time to first token is measured from request start until the first non-empty streamed text chunk. It includes HTTP and server overhead; it is not a pure prefill measurement.
- Elapsed time is the complete HTTP streaming request duration.
- Tokens/sec is computed from server-reported completion-token usage divided by time from first content to stream completion. It is an approximate end-to-end generation rate, not a kernel-only decode benchmark.
- Missing usage metadata produces null token counts and null throughput.
- GPU telemetry is sampled periodically. It can miss short spikes and the first sample may occur just after request start.
- RAM is host-wide used memory estimated from MemTotal minus MemAvailable.
- A run marked completed means the endpoint returned a completed stream, not that the answer is correct.

## Quality evaluation

The harness does not automatically grade outputs. For coding and reasoning comparisons, use fixed tasks with explicit acceptance criteria and independent checks (tests, builds, exact-answer checks or human review). Keep quality and resource/performance results side by side.

## Baseline discipline

Preserve the known-working Qwen3.8-27B Q3_K_M setup as the control. Do not replace or mutate its working launch configuration for experiments. A Q4 quant is a separate candidate, not a replacement baseline. Compare candidates under matched prompts, context limits, runtime build and generation settings where feasible.


## Runtime manifest

The optional `[run]` table in config.toml is copied into each experiment's configuration snapshot. Record the values that actually apply:

- `label`: human-readable configuration name, unique enough to distinguish quant/runtime variants.
- `model_file`: local model file path. If set, the harness validates that it exists and computes SHA-256 once per benchmark invocation.
- `runtime`, `runtime_version`, `launch_command`: runtime identity and exact launch invocation.
- `context_size`, `kv_cache_k`, `kv_cache_v`, `gpu_layers`, `batch_size`, `ubatch_size`, `flash_attention`: inference settings.
- `notes`: desktop/background conditions or other relevant observations.

The harness does not inspect your running process to infer these values. Fill them from the actual launch command and runtime output. Blank or unknown values should remain blank.

## Deterministic task checks

A JSONL task may optionally include `expected_exact` or `expected_contains`. These checks are intentionally simple and transparent:
- `expected_exact` compares the trimmed response to the expected string.
- `expected_contains` accepts a string or list of strings and checks case-insensitive substring presence.

Tasks without either field are recorded as unscored. These checks are not a substitute for code tests, semantic evaluation or human review. Do not turn subjective tasks into brittle substring tests.
