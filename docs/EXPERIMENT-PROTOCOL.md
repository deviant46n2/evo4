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

The current MVP stores only a subset of this manifest in each row. Until richer manifest capture is implemented, keep the missing runtime/model details in a versioned run-notes file alongside the experiment ID range.

## Recommended first sequence

1. Capture idle GPU/RAM telemetry with `evo-exp hardware`.
2. Run the smoke suite once to verify endpoint compatibility.
3. Run the fixed suite three times with no configuration changes.
4. Inspect failures, response bodies, timing fields and resource samples.
5. Repeat only after changing one major variable.
6. Preserve failed and incomplete runs; do not delete inconvenient results.

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
