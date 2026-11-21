# Hardening and context-budget validation handoff

Target branch: `hardening-context-v1`

This pass builds on `learning-feedback-v1`. It is intentionally additive and does not modify `main`.

## Changes to validate

1. **SQLite contention**
   - Both assistant `EvoStore` and lab `ResultsDB` use a 30-second connection timeout and `PRAGMA busy_timeout=30000`.
   - WAL mode remains enabled; synchronous mode is set to NORMAL.
   - Validate concurrent assistant and experiment-lab writes against the shared configured database. Confirm there are no transient `database is locked` errors under ordinary simultaneous use.

2. **Coding-agent verification**
   - Only recognized test-runner commands can set the test-verification status to passed/failed.
   - Lint-only commands, build-only commands, and `git diff --check` do not count as tests.
   - The signal remains deliberately modest: a successful test-runner exit is not proof of coverage or semantic correctness.
   - Validate that a test command before the latest successful write does not count, and a non-test command after a write does not count.

3. **Workspace boundaries**
   - Sensitive filename filtering includes common token/password/credential/private-key patterns.
   - Direct workspace writes to test/spec paths are blocked unless the caller explicitly enables them.
   - The coding-agent loop enables test-file writes only after the ordinary per-write approval callback; the CLI shows an additional warning.
   - Validate both a denied test-file write and an approved test-file write. Confirm normal source writes still work.

4. **Context budgeting**
   - `assistant.context_window_tokens` controls a conservative character-based input budget.
   - The base system prompt and current user request are preserved. Retrieved context is retained before older conversation history; history is trimmed oldest-first.
   - The 3.5 characters/token estimate is not tokenizer-exact. Compare prompt sizes with the configured runtime context and watch for unexpected truncation.

5. **Named provider profiles**
   - `[providers.NAME]` profiles override endpoint, model, timeout, and optional API-key environment variable.
   - Select with `evo chat --provider NAME`, `evo code --provider NAME`, or `evo doctor --provider NAME`.
   - Credentials must be supplied through `api_key_env`; no key should be committed to TOML.
   - Backward compatibility with existing `[server]` config must remain intact.
   - This is profile selection for OpenAI-compatible endpoints, not automatic routing/failover and not a native adapter for every provider.

## Automated checks

Run from a clean checkout of this branch:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

New focused coverage is in `tests/test_hardening_features.py`. Existing coding-agent and config tests must continue passing.

## Live validation

- Run `evo doctor --provider local` against the configured local endpoint.
- Run a short chat and a small coding task with Qwen.
- For coding, test a source write, an approved test-file write, a denied test-file write, a successful `python -m unittest`, and a lint-only command after a write.
- Run a small `evo-exp run` while the assistant database is active, then inspect both histories.
- Try a deliberately small context budget and verify that the latest user request and system policy survive.
- If a free cloud-compatible endpoint is configured, test it with `--provider NAME`; do not make cloud access a required test.

## Explicitly not claimed

No local test suite or live Qwen run has been executed by this GitHub-only editing pass. Kilo/OpenCode should independently run the automated and live checks above, report exact commands/results, and inspect the diff for regressions. Do not merge into `main` until that review is complete.
