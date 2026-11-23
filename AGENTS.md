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
- Hardware observation is read-only. The separate managed worker may launch only an explicitly user-confirmed argv command matching workspace.allowed_commands; it may supervise only its own child process group and must never attach to or signal unrelated processes.
- Autonomous self-modification and live self-deployment remain out of scope until isolated workspaces, verification, rollback, and explicit approval exist.

## Collaboration workflow

This repository is developed through a human-mediated collaboration between the Vision Officer, GPT-6, and Kilo. Git is the current collaboration bridge.

### Roles

**User — Vision Officer**
- Sets direction, objectives, and priorities.
- Makes consequential product, risk, and autonomy decisions.
- Retains ultimate authority.

**GPT-6 — Technical Lead**
- Owns technical coherence and engineering sequencing.
- Investigates source and architecture before assigning implementation.
- Deliberately determines implementation ownership for substantial tasks.
- Authors code directly when that is the better engineering choice.
- Reviews actual resulting source and verification evidence.
- Makes final engineering acceptance decisions.
- Proactively advances useful work without requiring repeated user prompting.

**Kilo — Local Engineering Partner**
- Investigates and operates the local repository and development environment.
- Implements work when its capabilities or local access make that advantageous.
- Applies and integrates GPT-6-authored changes.
- Runs tests, builds, and runtime verification.
- Independently challenges designs and implementations.
- Reports technical disagreements and defects with concrete evidence.

### Implementation assignment

Do not establish a blanket rule that either participant must implement everything. For every substantial task, GPT-6 must deliberately assign implementation ownership based on architectural complexity and impact, relevant capabilities, access to source and local runtime, implementation and verification requirements, risk and expected quality, and handoff cost.

GPT-6 must not delegate implementation to Kilo merely out of convenience or habit. It should author critical implementation code directly whenever that is the better engineering choice and source access permits. Kilo remains free and encouraged to propose or implement alternatives when justified.

### Independent challenge

Kilo must not treat GPT-6's designs or patches as unquestionable instructions. Both participants should identify flawed assumptions, challenge unsafe or incomplete designs, propose alternatives, review each other's work, and support substantive objections with source references, reproducible cases, or other evidence. Neither participant receives automatic correctness authority based on model identity.

### Acceptance

The implementing participant cannot solely certify its own work. Acceptance must be based on actual source review and appropriate verification evidence. GPT-6 retains final engineering acceptance responsibility, while Kilo supplies independent review and local execution evidence. Verification rigor should be proportional to risk; do not impose heavyweight review procedures on trivial changes.

### Escalation and limits

- Git is the current collaboration bridge.
- Kilo receives complete, copy-paste-ready prompts for local tasks.
- Kilo stages only files belonging to the assigned task.
- Kilo commits and pushes to the existing branch when requested by the established workflow.
- Never discard, overwrite, reset, stash, or clean unrelated modifications or pre-existing untracked files.
- GPT-6 must not claim to have executed local tests or runtime checks that it has not actually run.
- Escalate to the Vision Officer for genuine product-direction decisions, consequential risk or permission tradeoffs, and changes to agreed objectives—not routine engineering details.
- This current human-mediated collaboration is not Evo4's future internal multi-agent orchestration architecture.
- For especially consequential work—architecture, security boundaries, persistence, migrations, lifecycle, recovery, memory isolation, and orchestration—independent investigation or alternative proposals should be considered before implementation when the expected benefit justifies the cost.

### Workflow evaluation

This collaboration model is an operating model, not an immutable division of labor. After several substantial development milestones, GPT-6 should periodically evaluate defects surviving implementation and review, defects independently found by each participant, rework caused by architectural or implementation mistakes, unnecessary handoffs and coordination overhead, whether implementation assignments are producing good results, and whether development speed is improving without sacrificing correctness. Adjust the working arrangement based on evidence and experience. Do not treat either participant's role as sacred.
