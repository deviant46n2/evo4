# Evo4 Development Continuity

This is the concise handoff record for future development conversations. The authoritative roadmap and subsystem specifications contain the durable detail.

## Vision and operating priority

Evo4's immediate purpose is to become a dependable local-first AI workbench and development system that makes the user's existing hardware more useful. The first product objective is reliable local execution, resource-aware model/runtime management, and a development workflow that can progressively take over the local repository work currently performed by Kilo.

The long-term ambition is a user-controlled substrate for increasingly capable AI systems, potentially including superintelligence, through software engineering, memory, context, tools, orchestration, evaluation, and controlled research. This is a distant ambition, not a current capability claim.

Current collaboration:
- The user is the Vision Officer and retains authority over goals, priorities, consequential risk, permissions, and acceptance.
- GPT-6 is the technical lead: it owns architectural coherence, sequencing, implementation strategy, source review, and engineering decisions.
- Kilo is the local engineering partner: it provides local repository/environment access, implementation, independent challenge, tests, builds, and runtime evidence. Keep it useful; do not disable or remove it.
- Evo's goal is to progressively take over Kilo's local-hands work. Kilo remains a valuable fallback and independent reviewer even after Evo can perform that work.
- GitHub is the current shared engineering source of truth and handoff mechanism. Evo does not currently directly control external GPT-6 or Kilo sessions.

## Document authority

- `ROADMAP.md`: sole authority for priorities, sequence, phase status, dependencies, and acceptance gates.
- `docs/ARCHITECTURE.md`: durable system architecture, entities, and boundaries.
- `docs/PRODUCT-REDESIGN-PLAN.md`: UX requirements only; no competing phase sequence.
- `docs/DEVELOPMENT-CONTROL-PLANE.md`: proposed cooperative development-control semantics, not an implementation schedule.
- `README.md`: user-facing implemented capabilities and limitations.
- `AGENTS.md`: engineering, safety, and collaboration rules.

If documents conflict, follow this hierarchy and reconcile dependent documents in the same documentation pass.

## Current repository state

- Repository: `deviant46n2/evo4`.
- The active development branch for the current roadmap work is `agent-p4-selected-participant-admission-v1`. Always verify the branch and HEAD before a new handoff; this value may become stale.
- Original local checkout preservation invariant: branch `local-demo-ready-v1`, HEAD `a8ab59324caceab5b6fb2e5c674276c5ba96d072`; do not modify or clean it unless explicitly authorized.
- Preserve all existing worktrees and uncommitted changes. Never use destructive Git cleanup/reset operations.
- Phase 2 isolation was accepted 2026-11-24.
- Phase 3 participant contracts/runtime integration was accepted 2026-11-25.
- The Phase 4 experiment-accounting correction at `591126548d08b40e1112690443a9b2688158eb05` passed Kilo validation: 58/58 focused tests, 978/978 full tests, compileall, desktop production build, and diff-check. This does not accept the entire former cooperative-experiment phase or demonstrate live multi-participant execution.
- Project Provisioning v1 was accepted and closed at `d0b56afee86b208aab738994cee8a13c63bff107`.
- Existing hardware telemetry, advisory resource admission/scheduling, managed workload execution, background agent tasks, memory, experiments, and runtime integration are foundations with documented limits, not a complete local execution or hardware-management system.

## Current priority

Follow `ROADMAP.md`. The immediate next implementation phase is **Phase 4 — Local execution bridge**. Its exit benchmark is the ability to take a GPT-6-authored bounded task and safely inspect, edit, execute, verify, and report work in an explicitly selected local workspace, returning a reviewable diff and reproducible evidence.

The next phases are hardware/model-runtime management, the GPT-6-to-Evo local development loop, measured local intelligence, stronger memory/context, evaluation, and only later advanced cooperative orchestration and controlled autonomy.

Do not resume the live multi-participant cooperative benchmark merely because its design and accounting infrastructure exist. It is deferred to Phase 10 unless the user explicitly changes priority.

## Engineering workflow

1. GPT-6 investigates source, architecture, constraints, and current branch state.
2. GPT-6 chooses implementation ownership deliberately. It authors critical code directly when that is the better engineering choice and source access permits; Kilo implements when local access or comparative advantage makes it preferable.
3. Kilo receives complete, copy-paste-ready prompts for local tasks. Prompts specify exact branch/SHA, scope, allowed actions, tests, preservation requirements, and expected evidence.
4. The implementing participant does not solely certify its own consequential work. The other participant reviews source and evidence where practical.
5. GPT-6 inspects the exact resulting diff/commit and validation report, resolves technical disagreements, and makes the engineering acceptance decision.
6. The user makes product-direction, consequential-risk, permission, and formal phase-acceptance decisions.

## Safety and evidence invariants

- Preserve user data, local configuration, uncommitted changes, and every pre-existing worktree.
- Do not deploy or modify the running Evo instance during ordinary development.
- Use isolated feature branches/worktrees for code changes.
- Local execution is workspace-bound, least-privilege, and explicitly authorized. Commands use argv arrays, not generated shell strings.
- A managed worker may supervise only processes it starts and owns. It must not attach to, signal, kill, or reconfigure unrelated processes or an existing inference server.
- Hardware telemetry is read-only unless a separate, explicit control contract authorizes an operation.
- Optional cloud providers must remain optional; paid cloud access is never a core dependency.
- Do not claim tests, builds, runtime checks, or live-model calls were run unless their exact output was observed.
- Distinguish implemented, tested, independently reviewed, and accepted.
- Do not autonomously merge, deploy, delete, or expand privileges.
- GPT-6 should advance routine engineering work without requiring the user to manage handoffs; escalate only genuine product decisions and consequential tradeoffs.
