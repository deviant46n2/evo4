# Hardening and context-budget validation handoff

Target branch: `audit-fixes-v1` (based on audited commit `80d96a465a44dc3e4ecdf178c1171f8b7ae7cfc8`)

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
   - Sensitive filename filtering includes common secret/password/credential/API-key/private-key/token combinations while avoiding generic source filenames such as `auth_helpers.py`, `private_types.py`, and `tokenizer.py`.
   - Direct workspace writes to test/spec paths require a one-use, path-scoped approval token.
   - The coding-agent loop mints that token only after the explicit per-write approval callback succeeds. The token cannot be reused for a second write or a different path.
   - Detection includes common JavaScript/TypeScript `.test.*`, `.spec.*`, and `__tests__` conventions.
   - Validate both a denied test-file write and an approved test-file write. Confirm normal source writes still work.

4. **Context budgeting**
   - `assistant.context_window_tokens` controls a conservative character-based input budget using 3 characters/token, plus a fixed 512-token safety margin and the configured output reserve.
   - The base system prompt and current user request are never silently truncated. If they cannot fit, Evo raises a clear `ValueError` before persisting/sending the turn.
   - Retrieved context is retained as complete blank-line-separated sections; omitted sections receive an explicit notice. History is retained as complete messages only, newest-first selection, without slicing message bodies.
   - The estimate is still not tokenizer-exact. Validate with code-heavy and non-ASCII prompts against the actual runtime context.

5. **Named provider profiles**
   - `[providers.NAME]` profiles override endpoint, model, timeout, and API key. `api_key_env` is preferred; a direct `api_key` value is also supported for compatibility.
   - Select with `evo chat --provider NAME`, `evo code --provider NAME`, or `evo doctor --provider NAME`.
   - Prefer `api_key_env` for credentials; never commit actual secrets to TOML.
   - Backward compatibility with existing `[server]` config must remain intact.
   - This is profile selection for OpenAI-compatible endpoints, not automatic routing/failover and not a native adapter for every provider.

## Automated checks

Run from a clean checkout of this branch:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

New focused coverage is in `tests/test_hardening_features.py`. Existing coding-agent and config tests must continue passing. The audit-fix pass adds regression coverage for oversized requests, whole-section context omission, output-reserve clamping, JavaScript test paths, secret-filter false positives, one-use test-write approvals, and direct profile API keys.

## Live validation

- Run `evo doctor --provider local` against the configured local endpoint.
- Run a short chat and a small coding task with Qwen.
- For coding, test a source write, an approved test-file write, a denied test-file write, a successful `python -m unittest`, and a lint-only command after a write.
- Run a small `evo-exp run` while the assistant database is active, then inspect both histories.
- Try a deliberately small context budget and verify that the latest user request and system policy survive.
- If a free cloud-compatible endpoint is configured, test it with `--provider NAME`; do not make cloud access a required test.

## Explicitly not claimed

No local test suite or live Qwen run has been executed by this GitHub-only editing pass. The reported 81/81 result belongs to the parent `hardening-context-v1` commit, not this follow-up branch. Kilo/OpenCode should independently run the automated and live checks above, report exact commands/results, and inspect the diff for regressions. Do not merge into `main` until that review is complete.
