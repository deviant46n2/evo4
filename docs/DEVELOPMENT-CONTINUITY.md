# Evo4 Development Continuity

This is the concise handoff record for future development conversations. Durable decisions belong in version-controlled documentation, not only chat history.

## Vision and identity

Evo exists to make cooperating AIs and tools more capable together than any of them could be independently.

Evo is a portable, model-agnostic platform for cooperative intelligence. It supplies the coordination, shared context, delegation, verification, evaluation, governance, resource management, and user oversight that let heterogeneous models, agents, tools, and people combine their capabilities.

The personal assistant and coding-agent experience is the initial practical product, not the platform's ultimate identity. GPT-6 and Kilo are the current human-mediated reasoning/implementation collaborators and a practical reference workflow, not permanent architectural dependencies. Evo does not currently orchestrate those external sessions directly. GitHub is the present handoff and source-of-truth mechanism.

The long-term ambition is to improve AI capability through software engineering and controlled system-level research, potentially pursuing increasingly capable and eventually superintelligent systems. This is an ambition, not a current capability claim.

## Document authority

- `ROADMAP.md`: sole authority for development sequence, priorities, phase status, dependencies, milestones, and acceptance gates.
- `docs/ARCHITECTURE.md`: system identity, domain model, architectural principles, and boundaries.
- `docs/PRODUCT-REDESIGN-PLAN.md`: target UX and product interaction requirements only; its legacy phase outline is subordinate to `ROADMAP.md`.
- `docs/DEVELOPMENT-CONTROL-PLANE.md`: proposed cooperative development-control architecture; not an implementation schedule or proof of implementation.
- `docs/GEMINI-AUDIT-LEDGER.md`: audit findings, remediation evidence, and acceptance record.
- `README.md`: user-facing description of implemented behavior and limitations.
- `AGENTS.md`: repository engineering and safety instructions.

If documents conflict, follow this hierarchy. Update the authoritative source first and reconcile dependent documents in the same documentation pass.

## Canonical architectural decisions

The durable architecture is defined in `docs/ARCHITECTURE.md`; cooperative governance, participant contracts, and collaboration semantics are defined in `docs/DEVELOPMENT-CONTROL-PLANE.md`; sequencing and acceptance gates are defined only in `ROADMAP.md`. Do not maintain competing copies of those detailed specifications here.

The operating invariants for handoff are: user authority remains ultimate; tasks have one accountable owner; registration/capability/trust/availability never imply authorization; provider integrations must comply with their terms and supported interfaces; permissions and resource budgets are bounded; project/context isolation is mandatory; and consequential results require evidence independent of contributor self-report.

## Current repository and implementation state

- Repository: `deviant46n2/evo4`.
- Active working branch: `agent-lifecycle-reconciliation-v1`.
- Check branch HEAD from Git before every new engineering handoff; do not assume a SHA recorded in chat remains current.
- Platform Registry v1 through M5 is implemented and validated: AI configurations, software projects, project checkouts, workspaces, and registered-workspace execution boundaries.
- Existing agent runs, plans, approvals, cancellation, background tasks, and recovery provide partial lifecycle/orchestration foundations. They do not constitute the intended heterogeneous cooperative control plane.
- Existing memory, experiment, and resource-management capabilities are partial. Consult the implementation documents and README before claiming completeness.
- The desktop is an existing chat-first client with supporting workspaces; the proposed target experience is not fully implemented.

## Stabilization freeze and authorization

**The stabilization freeze was lifted for the authorized Project Provisioning v1 milestone.** Broader redesign implementation still requires user authorization.

The six Gemini audit priorities are recorded as completed and accepted in `docs/GEMINI-AUDIT-LEDGER.md` and `ROADMAP.md`:
1. Provider streaming reliability.
2. Tool-call argument validation.
3. Workspace filesystem boundary hardening.
4. Untrusted retrieved-context isolation.
5. Experiment lifecycle interruption finalization.
6. ResourceMonitor shutdown race.

Reported validation: 525 Python tests passed, compileall passed, and `git diff --check` passed. These results were reported by implementation runs; GPT-6 did not independently rerun the complete suite. No desktop production build was run for the Priority 6 follow-up. Do not overstate the validation evidence.

There are no outstanding stabilization tasks in the accepted audit ledger. The freeze was lifted for the authorized Project Provisioning v1 milestone; broader implementation still requires user authorization.

## Current documentation state

The unified roadmap/architecture reconciliation remains in progress. Gemini's independent critique identified material architectural, sequencing, and factual gaps; the current revision is being updated to address or explicitly disposition those findings. Do not mark Phase 1 complete until that review is reconciled and the canonical documents are mutually consistent.

**Project Provisioning v1** was accepted and closed at commit `d0b56afee86b208aab738994cee8a13c63bff107`. It provisions a language-neutral skeleton and Git checkout; workspace binding requires an explicitly selected existing configuration revision. If no configuration exists, the project remains unbound rather than receiving an invented default. Project deletion is deferred beyond this milestone and is not a Phase 2 exit prerequisite.

## Working collaboration protocol

The user is the Vision Officer and ultimate authority. GPT-6 is the default technical lead, primary author, and implementation owner. Kilo is the local execution, verification, and independent-review partner. This is an explicit operating rule, not a per-task choice between two interchangeable implementers.

### GPT-6 authorship and ownership

- GPT-6 directly investigates the repository and authors application code, tests, architecture, and documentation using available repository tools.
- GPT-6 makes source changes directly whenever repository access permits, and owns implementation strategy, sequencing, integration, and final technical acceptance.
- GPT-6 creates task-scoped branches, commits, and pull requests as appropriate. It must inspect the current branch and HEAD before each new engineering handoff.
- GPT-6 proactively advances useful work and must not ask the user to relay implementation tasks GPT-6 can perform itself.
- Kilo is not the default implementation delegate. Local machine access alone is not a reason to transfer authorship.

### Kilo's role

Kilo is used when a task genuinely requires the user's local filesystem, development environment, hardware, running application, local build/test execution, or an independent challenge that GPT-6 cannot adequately perform directly. Kilo's normal responsibilities are:
- Run explicitly requested local tests, builds, integration checks, and runtime verification.
- Return exact commands, branch/commit identity, outcomes, logs, and other requested evidence.
- Independently challenge designs and changes, identify concrete defects, and propose alternatives supported by evidence.
- Report environment-specific constraints that cannot be observed through repository inspection.

Kilo does not routinely author or modify application source, tests, architecture, or documentation as a substitute for GPT-6. Any exception requires the user's explicit direction. GPT-6 evaluates Kilo's findings, makes any needed source corrections, and retains final acceptance responsibility.

When Kilo is needed, GPT-6 provides a complete, copy-paste-ready prompt that defines the exact task, branch/commit, scope, commands or review questions, evidence to return, and prohibitions. The user should not have to construct or relay an incomplete handoff.

### Safety and evidence

- Git is the current source-of-truth and collaboration bridge.
- Use isolated, task-scoped branches; preserve unrelated modifications and pre-existing untracked files.
- Never blindly stage all files or discard, overwrite, reset, stash, or clean unrelated work. Never use destructive commands such as `git reset --hard` or `git clean -fd`.
- Do not deploy or modify the running Evo instance during an ordinary development pass.
- Every code-changing pass must run relevant automated checks and rebuild affected runnable artifacts. Documentation-only changes do not require unnecessary rebuilds.
- Kilo supplies local execution evidence; GPT-6 must not claim to have run commands it did not observe.
- Never weaken tests to obtain a green result. Report failures and limitations accurately.
- Kilo should challenge GPT-6's work, not rubber-stamp it. GPT-6 must assess substantive objections against source and evidence.
- Escalate to the Vision Officer for genuine product-direction decisions, consequential risk or permission tradeoffs, and changes to agreed objectives—not routine engineering details.
- This is the current human-mediated collaboration model, not Evo4's future internal orchestration architecture or a permanent dependency on specific model products.

## Next steps

1. Obtain an independent Gemini critique of the current documentation pass.
2. Evaluate each critique against the vision, architecture, implementation evidence, and freeze boundary.
3. Revise the documents and reconcile contradictions.
4. Project Provisioning v1 has been implemented under explicit user authorization; broader redesign implementation still requires authorization.

## Phase 2 planning status

- Phase 2 planning documentation has been added to `ROADMAP.md`.
- Current verified implementation: Project Provisioning v1, Registry v1, registered-workspace execution boundary, global conversations/messages, global memory/lessons/research, and coding-agent context isolation for untrusted retrieved text.
- Current verified gaps: conversations, messages, memories, lessons, research, tasks, plans, and command policy are not project-scoped; project deletion remains deferred; automatic project selection is not authorized. Task/plan scope and command-policy enforcement are now explicit Phase 2 milestones.
- No Phase 2 implementation has been started.
