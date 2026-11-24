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

The user communicates the desired outcome or objective. GPT-6 investigates the repository, existing architecture, and relevant constraints. GPT-6 determines the implementation strategy and assigns ownership. The assigned participant implements: GPT-6 authors code directly when appropriate; Kilo implements when its local access or comparative advantage makes that preferable. Kilo performs local integration, testing, builds, and runtime checks when required. The non-implementing participant independently challenges and reviews the work where practical. GPT-6 retrieves and examines the exact resulting commit, diff, and evidence. GPT-6 resolves technical disagreements and makes the final engineering acceptance decision. GPT-6 identifies and advances the next useful task without requiring the user to manage routine engineering coordination.

Operational constraints:
- Git is the current collaboration bridge.
- Kilo receives complete, copy-paste-ready prompts for local tasks.
- Kilo stages only files belonging to the assigned task.
- Kilo commits and pushes to the existing branch when requested by the established workflow.
- Never discard, overwrite, reset, stash, or clean unrelated modifications or pre-existing untracked files.
- GPT-6 must not claim to have executed local tests or runtime checks that it has not actually run.
- The user should not have to manage routine agent assignment, technical sequencing, or repeated incomplete handoffs.
- Escalate to the Vision Officer for genuine product-direction decisions, consequential risk or permission tradeoffs, and changes to agreed objectives—not routine engineering details.
- This current human-mediated collaboration is not Evo4's future internal multi-agent orchestration architecture.
- For especially consequential work—architecture, security boundaries, persistence, migrations, lifecycle, recovery, memory isolation, and orchestration—independent investigation or alternative proposals should be considered before implementation when the expected benefit justifies the cost.
- After several substantial development milestones, GPT-6 should periodically evaluate defects surviving implementation and review, defects independently found by each participant, rework caused by mistakes, unnecessary handoffs, whether assignments are producing good results, and whether development speed is improving without sacrificing correctness. Adjust the working arrangement based on evidence.

## Next steps

1. Obtain an independent Gemini critique of the current documentation pass.
2. Evaluate each critique against the vision, architecture, implementation evidence, and freeze boundary.
3. Revise the documents and reconcile contradictions.
4. Project Provisioning v1 has been implemented under explicit user authorization; broader redesign implementation still requires authorization.

## Phase 2 implementation status

The authoritative status and acceptance gates are in `ROADMAP.md`. Phase 2 is **partially implemented, not accepted as complete**. Do not use this continuity summary to override the roadmap.

Implemented source foundations recorded by the roadmap include:
- Project Provisioning v1, Registry v1, and registered-workspace execution-boundary validation.
- Project/workspace scope on conversations; messages inherit scope through their parent conversation.
- Project/workspace scope on memories, memory candidates, lessons, research documents, and tasks, with scope-aware storage/retrieval paths.
- Scope fields and validation on agent plans, with API visibility checks.
- Fail-closed project command-prefix policy intersected with the operator's global command allowlist.
- Workspace-scoped repository instruction discovery; repository-provided instruction files remain untrusted.
- Projects and Workspaces UI components.

These are implementation observations, not proof that every Phase 2 acceptance gate has passed.

Outstanding Phase 2 acceptance work remains:
- CLI/API equivalence for scope-sensitive operations.
- Instruction trust and precedence across assistant, plan, and coding-agent paths.
- Adversarial checkout overlap, symlink, and canonical-path verification.
- Scope continuity and mismatch rejection across approval, execution, cancellation, restart recovery, and resumption paths.
- Cross-project retrieval and execution leakage tests across scoped records and API operations.
- Review of project-selection UX and uncertain-scope behavior.

A further important boundary is already visible in source: workspace resolution returns the exact pinned Registry configuration revision, but current assistant chat and agent-plan proposal generation still use the application-global assistant/provider. Phase 3 must bind the pinned revision to every workspace-bound runtime entrypoint; it must fail explicitly rather than silently falling back to global TOML. See `ROADMAP.md` and `docs/PHASE-3.1-CONTRACT-PROPOSAL.md`.

Project deletion remains explicitly deferred and is not a Phase 2 exit prerequisite. Automatic project inference/switching and cross-project consultation remain out of scope unless separately authorized.
