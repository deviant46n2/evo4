# Evo 4 development instructions

## Permanent build-after-change policy

Every code-changing development pass must rebuild every affected runnable application artifact and run the relevant automated checks before it is considered complete.

Current repository commands:
- Python tests: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`
- Python compilation: `.venv/bin/python -m compileall -q src tests`
- Desktop production build: `cd desktop && npm run build`

A code change is not complete merely because tests pass. Rebuild the affected runnable application. Never claim a build succeeded unless the exact command completed successfully. Fix build failures before declaring completion; otherwise report the failure clearly. Documentation-only changes do not require unnecessary rebuilds.

## Development safety

- Preserve user data, local configuration, uncommitted changes, and existing worktrees.
- Never use destructive Git commands such as reset --hard or clean -fd.
- Do not deploy or modify the currently running Evo instance during an ordinary code pass.
- Implement and validate changes in an isolated feature branch/worktree. The running instance remains untouched until the user chooses to update it.
- Kilo validation must independently verify branch/HEAD, tests, compilation, production build, and changed behavior.
- Never claim tests, builds, live-model checks, or browser checks were run unless output was observed.
- Never weaken tests or assertions to obtain a green result.

## Architecture boundaries

- SQLite remains the durable source of truth.
- Preserve provenance, confidence, timestamps, and supersession/contradiction history.
- Tentative candidates are not trusted memories until user approval.
- Optional cloud providers remain optional; local operation must remain supported.
- Hardware observation is read-only unless a separately reviewed safety design enables an action.
- Autonomous self-modification and live self-deployment remain out of scope until isolated workspaces, verification, rollback, and explicit approval exist.
