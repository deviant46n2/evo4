# Local handoff and independent review

This handoff describes the current desktop + hardware-observability baseline. For the exact independently reviewed commit and caveats, see [Project status](PROJECT-STATUS.md).

## First local setup

For desktop use, follow [the desktop user guide](DESKTOP-USER-GUIDE.md), which includes the optional API dependencies and separate backend/frontend terminals.

```bash
git clone -b documentation-refresh-v1 https://github.com/deviant46n2/evo4.git
cd evo4
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config.example.toml config.toml
```

Set `[server].model` to the exact ID exposed by the running llama.cpp server. Keep `config.toml` local; it is git-ignored.

## Suggested first checks

```bash
python -m unittest discover -s tests -v
evo doctor
evo doctor --test-tools
evo chat
evo code --workspace .
evo memory add "Evo is a local-first assistant project" --category project --source user
evo memory search "local-first assistant"
evo memory evaluate --cases tasks/memory-retrieval.json --top-k 5 --backend auto
evo memory evaluate --cases tasks/memory-retrieval.json --top-k 5 --backend fallback
evo memory candidates
evo learn add "Run tests before claiming success" --trigger "coding tests" --category coding
evo learn search "coding tests"
evo runs list --limit 20
evo runs summary
evo runs show RUN_ID
evo runs review RUN_ID --outcome partial --feedback "Describe what worked and what did not." --lesson "A reusable correction." --trigger "relevant trigger terms"
evo task add "Run first local validation" --priority 1
evo task list
evo research add "Example source note" --url "https://example.org" --content "Replace this with actual sourced notes."
evo backup backups/initial.sqlite3
evo-exp hardware
evo-exp doctor
evo-exp run --tasks tasks/smoke.jsonl --repetitions 1
```

The example research note above is a CLI usage example, not a real research claim.

For coding mode, the default configuration allowlists `python -m unittest` and `pytest`. The model can inspect files automatically; each file write and command requires an interactive approval. Add other safe command prefixes to `[workspace].allowed_commands` only when needed. Tool-call support must be verified against the selected llama.cpp build and model.

## Independent review prompt

Review this repository as a skeptical senior Python engineer. Do not assume the implementation is correct because tests exist. First inspect the complete repository and identify architectural and correctness risks. Then:

1. Install it in a clean virtual environment and run all tests.
2. Inspect SQLite schema creation, migrations, FTS5 fallback, concurrency, and persistence behavior.
3. Inspect streaming SSE parsing, error handling, multi-turn message construction, usage metadata, and llama.cpp compatibility.
4. Inspect path traversal/symlink handling and command allowlisting in the workspace API.
5. Exercise the CLI against the actual local model endpoint without changing model/runtime settings.
6. Test restart persistence for conversations, memories, tasks, and research documents.
7. Verify the synthetic memory benchmark under both FTS5 and forced fallback; confirm it does not create or touch the configured live database.
8. Test that superseded memories remain historically linked, are not retrieved as current facts, and can still be surfaced when a query matches the old wording. Test that explicit contradictions are surfaced without the model silently resolving them.
9. Test that run feedback links user-authored lessons to their source run, and that run summaries report correct verification and feedback metrics.
10. Attack the coding-agent verification heuristic: command classification, nonzero exit codes, denied commands, and a later file write invalidating an earlier successful check.
11. Identify missing features and bugs; distinguish reproduced failures from static-review concerns.
12. Do not make broad rewrites. Produce a prioritized report with file/line references, reproduction steps, severity, and suggested minimal fixes.

Do not run arbitrary commands or modify files outside the cloned repository. Do not change the local model server configuration without explicit approval.

## Reporting back

Return:
- exact commit SHA tested
- OS/Python version and model endpoint identity
- commands run and exit codes
- test failures and tracebacks
- runtime compatibility findings
- resource measurements
- recommended fixes ranked by severity

Do not report an untested hypothesis as a confirmed defect. The earlier live Qwen test does not validate later features; repeat real endpoint checks on the exact commit under review. For desktop work, separately test browser interactions and narrow-window behavior. Do not treat a successful TypeScript/Vite build as browser UX validation. CI covers Python 3.11 and 3.14, but does not validate the user's local model behavior.
