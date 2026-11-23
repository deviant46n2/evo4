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

**The stabilization freeze is active.** Do not change application code, runtime behavior, schemas, APIs, tests, dependencies, or deployment state unless the user explicitly lifts the freeze.

The six Gemini audit priorities are recorded as completed and accepted in `docs/GEMINI-AUDIT-LEDGER.md` and `ROADMAP.md`:
1. Provider streaming reliability.
2. Tool-call argument validation.
3. Workspace filesystem boundary hardening.
4. Untrusted retrieved-context isolation.
5. Experiment lifecycle interruption finalization.
6. ResourceMonitor shutdown race.

Reported validation: 525 Python tests passed, compileall passed, and `git diff --check` passed. These results were reported by implementation runs; GPT-6 did not independently rerun the complete suite. No desktop production build was run for the Priority 6 follow-up. Do not overstate the validation evidence.

There are no outstanding stabilization tasks in the accepted audit ledger. The freeze nevertheless remains active until the user explicitly lifts it. Documentation work does not lift the freeze and does not authorize implementation, restart, or deployment.

## Current documentation state

The unified roadmap/architecture reconciliation remains in progress. Gemini's independent critique identified material architectural, sequencing, and factual gaps; the current revision is being updated to address or explicitly disposition those findings. Do not mark Phase 1 complete until that review is reconciled and the canonical documents are mutually consistent.

The first planned implementation milestone after explicit freeze-lift authorization is **Project Provisioning v1**, defined in `ROADMAP.md`. It is planned only, not started or authorized. It provisions a language-neutral skeleton and Git checkout; workspace binding requires an explicitly selected existing configuration revision. If no configuration exists, the project remains unbound rather than receiving an invented default. Project deletion is deferred beyond this milestone and is not a Phase 2 exit prerequisite.

## Working collaboration protocol

- The user is Vision Officer and final authority for purpose, direction, boundaries, and consequential decisions.
- GPT-6 acts as technical/product lead: independently makes routine architecture, product, sequencing, and engineering decisions; challenges assumptions; and reports evidence and uncertainty candidly.
- Kilo is the local implementation/integration and validation partner. When Kilo must inspect or change local repository state, provide a complete copy-paste-ready prompt.
- GPT-6 should directly author critical implementation logic when implementation is authorized and the relevant source is available; Kilo integrates locally, handles broad/mechanical/UI work, and runs local validation.
- Git is the current collaboration bridge. Kilo makes task-scoped changes, stages only task files, preserves unrelated modifications/untracked files, commits and pushes the existing branch. GPT-6 reviews the actual pushed diff and evidence.
- Gemini may provide independent critique. Treat its findings as hypotheses to evaluate, not automatic instructions; accept, reject, or modify them with reasons.
- Do not ask the user to decide routine implementation details. Ask only for vision-level input, missing authority, or genuinely consequential trade-offs.

## Next steps

1. Obtain an independent Gemini critique of the current documentation pass.
2. Evaluate each critique against the vision, architecture, implementation evidence, and freeze boundary.
3. Revise the documents and reconcile contradictions.
4. Only after documentation is accepted and the user explicitly lifts the freeze, begin Project Provisioning v1.
