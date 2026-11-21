# Experimental Integrity v1

## Measurement contract

An experiment is not considered complete merely because the HTTP/SSE stream ended. The harness records the server's final OpenAI-compatible finish_reason and classifies the result:

- completed: explicit stop; deterministic task checks may be scored.
- truncated: length; the response is retained for diagnosis but is not scored.
- incomplete: another reported finish reason (for example, content filtering or an unexpected tool-call ending); not scored.
- unknown: the server omitted finish_reason; not scored.
- failed: the request or processing raised an error.

The CLI exits nonzero if any run in the requested batch is not completed. Reports retain the raw finish reason and evaluation status. Performance means, medians, and sample standard deviations for elapsed time, TTFT, and tokens/second use only explicitly completed runs. Hardware samples remain useful for incomplete runs and are retained.

## Reproducibility

[experiment].seed is optional. If configured, repetition 1 uses that seed, repetition 2 uses seed + 1, and so on. The effective seed is stored in its own database column and in each run's manifest. Omitting the setting leaves sampling behavior to the server.

For llama.cpp endpoints, the harness attempts a short GET /props request once per batch. It stores only an allowlist of runtime fields (build info, model path/type, context/batch sizes, parallelism, and slot count). Unsupported endpoints or unavailable properties are recorded as unavailable; they do not prevent experiments from running. User-entered runtime metadata remains available for settings the server does not expose. No launch command is inferred.

## Database compatibility

Existing experiment databases are migrated additively with finish_reason and seed columns. Historical rows marked completed but lacking a finish reason are reclassified as unknown, and their old deterministic scores are excluded from aggregate totals. Their original response and evaluation detail payloads are retained for audit; the migration does not delete experiment records.

## Interpretation limits

- A fixed seed improves repeatability only when the inference server honors it; the manifest records what Evo requested, not proof that a backend honored it.
- Mean/median/standard deviation describe observed runs; they do not establish statistical significance or causality.
- A server may omit or misuse finish_reason; Evo reports unknown/incomplete rather than guessing.
- The /props snapshot is a partial runtime fingerprint, not a complete reproduction of every server launch flag, GPU state, or environment variable.
- Deterministic task checks evaluate only declared string conditions. They are not a general measure of answer quality.
