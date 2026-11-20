# Local handoff and independent review

This branch is a substantial early implementation, not a claim of target-machine validation.

## First local setup

```bash
git clone -b substantial-v1 https://github.com/deviant46n2/evo4.git
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
evo chat
evo memory add "Evo is a local-first assistant project" --category project --source user
evo memory search "local-first assistant"
evo task add "Run first local validation" --priority 1
evo task list
evo research add "Example source note" --url "https://example.org" --content "Replace this with actual sourced notes."
evo-exp hardware
evo-exp doctor
evo-exp run --tasks tasks/smoke.jsonl --repetitions 1
```

The example research note above is a CLI usage example, not a real research claim.

## OpenCode independent review prompt

Review this repository as a skeptical senior Python engineer. Do not assume the implementation is correct because tests exist. First inspect the complete repository and identify architectural and correctness risks. Then:

1. Install it in a clean virtual environment and run all tests.
2. Inspect SQLite schema creation, migrations, FTS5 fallback, concurrency, and persistence behavior.
3. Inspect streaming SSE parsing, error handling, multi-turn message construction, usage metadata, and llama.cpp compatibility.
4. Inspect path traversal/symlink handling and command allowlisting in the workspace API.
5. Exercise the CLI against the actual local model endpoint without changing model/runtime settings.
6. Test restart persistence for conversations, memories, tasks, and research documents.
7. Identify missing features and bugs; distinguish reproduced failures from static-review concerns.
8. Do not make broad rewrites. Produce a prioritized report with file/line references, reproduction steps, severity, and suggested minimal fixes.

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

Do not report an untested hypothesis as a confirmed defect.
