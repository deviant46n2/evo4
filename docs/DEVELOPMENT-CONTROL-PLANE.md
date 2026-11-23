# Development Control Plane (Proposed)

**Status: proposed architecture, not implemented.** This document defines the intended coordination semantics. It is not an implementation schedule or evidence that Evo currently orchestrates heterogeneous participants. Development order is governed only by `ROADMAP.md`.

## Purpose and current reality

Evo exists to make cooperating AIs and tools more capable together than any one could be independently. The control plane should turn a set of models, agents, tools, services, and people into a governed collaborative system that can combine work, challenge assumptions, resolve disagreement, and demonstrate when collaboration improves outcomes.

The current GPT-6/Kilo workflow is human-mediated: GPT-6 provides reasoning/architecture/review, Kilo performs local repository work and validation, the user sets vision and retains final authority, and GitHub is the handoff/source-of-truth mechanism. This workflow is design inspiration only. Evo does not currently dispatch to or observe those external sessions. Phase 4 must validate Evo's own runtime contracts with participants Evo can actually invoke.

A minimal recovery path must remain usable when the control-plane worker is unavailable. Current support includes local CLI diagnostics and `evo backup <destination>` for a consistent SQLite backup, plus Git for source/configuration recovery. A dedicated application restore command is not currently documented as available; the exact SQLite-safe restore procedure, startup checks, and a recovery test must be specified before the control plane depends on this path. Recovery must not require the orchestration worker, scheduler, or a live participant provider.

## Governance and trust primitives

The user retains authority over purpose, policy, permissions, consequential approvals, and system-level decisions. Each task has one accountable owner. Participants may deliberate and delegate only within the authority granted to them.

Keep these concepts separate:
- **Identity:** which participant/runtime is being invoked.
- **Capability:** what it declares it can do and what interfaces it supports.
- **Availability:** whether it can currently accept work.
- **Compliance:** whether the proposed integration/use is permitted under current provider terms, API rules, licensing, automation restrictions, and data-handling requirements.
- **Evidence/trust:** observed reliability for specific task classes, with sample counts and uncertainty.
- **Role eligibility:** which task-scoped roles policy permits it to perform.
- **Registration:** whether Evo knows the participant.
- **Authorization:** what this participant may do for this task/project now.

None of these facts implies another. In particular, registration, capability, trust score, or successful past work never grants permissions automatically.

## Participants and configuration-to-runtime binding

Participants may be model endpoints, agent runtimes, tools, external services, or human contributors. A participant record should eventually retain stable identity, type, version, declared capabilities, input/output contract versions, availability, execution location, resource needs, provenance, trust profile, and compliance metadata.

Roles such as planner, researcher, implementer, challenger, synthesizer, reviewer, and verifier are task-scoped responsibilities, not permanent model identities.

Versioned AI Configurations are definitions, not executable participants by themselves. A runtime binding layer must:
1. Resolve an immutable configuration revision.
2. Validate its schema and component references.
3. Resolve each declared component to an installed, supported adapter.
4. validate provider/interface compliance and credential references without copying secrets into shared context.
5. Construct a participant instance with explicit capabilities, limits, and policy.
6. Report unavailable/unsupported components explicitly; never silently substitute a different model or policy.
7. Record the exact configuration revision, adapter version, provider/model identity, and effective policy used for each execution.

This binding is a Phase 3 deliverable. A Registry row or UI selection is not proof that a configuration can run.

Compliance metadata should be structured and versioned per integration: provider/service identity, terms/policy URL and checked version/date, permitted interface/API, automation permission/status, data retention/training constraints, geographic/data-handling constraints where relevant, rate/token quotas, license obligations, and review owner/status. If terms change or compliance becomes unknown, the integration is suspended or restricted pending review. No bypasses, undocumented interfaces, permission laundering, or attempts to evade provider restrictions.

## Task, assignment, and execution model

A **Task** is a durable objective with scope, priority, acceptance criteria, one accountable owner, project/workspace references, dependencies, authorization, and lifecycle.

An **Assignment** is a bounded contribution allocated to one participant. It states the expected result, inputs/context, output contract, task-scoped role, deadline, resource budget, and permissions. A child assignment's permissions must be a strict subset of the parent task's effective permissions. Delegation may narrow authority, never expand it. A participant cannot approve its own privilege expansion.

An **Execution** is one attempt to perform an assignment. It records the participant/config revision, effective permissions, context references, inputs/outputs, tool events, costs, status, and evidence.

A **Plan** is a proposed decomposition of a task. A **Workload reservation** is resource admission state. Neither is interchangeable with Task, Assignment, or Execution.

Task and assignment state transitions must be validated and durable. Conceptual task states include proposed, accepted, planned, assigned, running, review, disputed, adjudicated, completed, blocked, cancelled, failed, and interrupted. Not every task must use every state, but terminal states and transitions must be explicit. A child timeout, cancellation, or revocation propagates to descendants. Late results from a cancelled/expired child are retained as late evidence but cannot silently advance the parent.

## Cooperation patterns and synthesis

Evo should support multiple cooperation patterns rather than treating collaboration as one fixed linear agent chain. Initial patterns:

1. **Specialist decomposition:** an owner decomposes a task into bounded subtasks with explicit dependencies and contracts; different participants complete complementary pieces; the owner integrates the outputs against shared acceptance criteria.
2. **Independent parallel attempts:** two or more participants solve the same bounded problem in isolated worktrees/branches or isolated execution environments. Their outputs are compared using deterministic tests, objective criteria, and independent review. A synthesizer selects, combines, or rejects contributions with reasons.
3. **Implementer plus adversarial challenger:** one participant proposes/implements; another is tasked to find counterexamples, missed requirements, security weaknesses, or unsupported assumptions. The implementer responds; unresolved disagreements are escalated rather than hidden.
4. **Research-and-verification:** one participant gathers evidence; another checks source quality, claims, and reproducibility; a verifier runs deterministic checks where available.

A task may combine patterns, but each subtask and contribution remains attributable. Parallel attempts must not share a mutable working tree. Use dedicated Git worktrees/branches or another isolation mechanism; define merge ownership and conflict resolution before parallel editing is enabled.

**Synthesis is an explicit operation.** The task owner (or assigned synthesizer) compares candidate outputs against acceptance criteria, evidence, test results, and task constraints. It must record which contributions were accepted, rejected, or combined and why. Similarity or model confidence alone is not a valid selection rule.

## Handoff protocol

Every handoff must include task/assignment IDs, sender and recipient identities, expected next action, objective, scope, required inputs, relevant context/source references, output schema, acceptance criteria, permissions, remaining budget/deadline, and current state.

The receiver must explicitly accept or reject the handoff. Reject malformed, incomplete, out-of-scope, expired, or unauthorized handoffs with a reason; do not mark the assignment running until accepted. Acceptance does not enlarge permissions. A rejected handoff returns to its owner for correction or reassignment.

Handoffs that involve code must identify the source revision and isolated worktree/branch. A receiver must not unknowingly edit a dirty shared working tree or overwrite another participant's uncommitted work. Integration/merge is a separately owned action with conflict and test evidence.

## Disagreement and adjudication

Disagreement is a first-class state, not a prompt loop. When claims, patches, or verification results conflict:
1. Preserve each claim, author, supporting evidence, and source revision.
2. Run deterministic checks/oracles first when available (tests, type checks, schema validators, reproducible measurements, cryptographic hashes, or other objective checks appropriate to the claim).
3. Compare remaining claims against explicit acceptance criteria; ask participants for bounded evidence-based rebuttals if useful.
4. Allow a configured, finite number of review/adjudication rounds. No participant may extend the round limit unilaterally.
5. The accountable task owner may adjudicate within their authority when evidence is sufficient. If the owner is the disputed contributor, a designated independent reviewer or the user must adjudicate.
6. If evidence remains ambiguous, escalate to the user or mark the task disputed/blocked. Never manufacture consensus or silently select the most confident model.

A terminal disputed/escalated outcome is valid. The system records what remains unresolved and what decision is needed. A human decision is not represented as independent technical verification.

## Verification and evidence hierarchy

For consequential work, the contributor cannot be the sole certifier of its own success. Same-instance self-review is not independent review. When deterministic checks exist and are applicable, execute and retain their raw results before relying on model-written assessments. Model reviewers can add adversarial analysis but cannot override failed deterministic checks without a documented, authorized explanation of why the check is inapplicable or faulty.

Evidence precedence is claim-specific, but the default order is:
- Reproducible deterministic checks directly measuring the acceptance criterion.
- Independently reproduced measurements and source-backed observations.
- Independent human/agent review of the evidence and implementation.
- Participant self-report or confidence statements.

A passing test suite does not prove all correctness; a model review does not prove a test passed. Record both scope and limitations.

## Permissions, resource admission, and recovery

Every action is authorized at the execution boundary against current task, assignment, participant, project/workspace, and policy state. Permissions are least-privilege and attenuate down the delegation tree. Resource budgets also attenuate: child assignments cannot exceed remaining parent budget.

Before dispatch, perform admission against CPU/RAM/VRAM reserves, provider quotas, rate/token budgets, concurrency limits, and deadlines. If capacity is unknown, do not assume it is available. Minimal admission is required before the Phase 4 cooperative slice; durable concurrency scheduling is expanded in Phase 5.

Cancellation, timeout, revocation, and task termination propagate to child assignments and active executions. Workers must check cancellation at safe boundaries. A provider failure, timeout, partial output, or unavailable participant cannot be reported as success. Retry and reassignment are bounded and idempotent.

The independent recovery path must be concrete and documented: local CLI startup/diagnostics, direct database backup and restore using supported application commands or SQLite-safe procedures, and Git-based source/configuration recovery. It must not require the control-plane worker, scheduler, or provider endpoint. Recovery tests must include a control-plane startup failure and restoration from a known-good backup.

## Evaluation and participant reliability

Compare individual and cooperative modes using equivalent tasks, inputs, environment, and acceptance criteria. Preserve failures, ties, negative outcomes, latency, tokens/compute, costs, and human intervention.

Evaluation records should feed a task-class reliability profile for each participant/configuration: sample count, recency, confidence interval/uncertainty, deterministic check pass rates, failure modes, review findings, and known limitations. This profile may inform role eligibility and assignment recommendations through explicit policy thresholds. Thresholds must be inspectable, calibrated per task class, and subject to user policy. Scores may restrict or recommend; they never silently grant permissions, autonomy, or privileged roles. A change in trust/eligibility must be auditable and reversible.

## Security and failure boundaries

- Retrieved context, repository files, tool output, and participant messages are untrusted data unless separately validated.
- Project instructions from trusted Evo-managed metadata are separate from untrusted repository-provided instruction files.
- Secrets are referenced through approved credential handling; they are not copied into shared context or tracked artifacts.
- Malformed handoffs, unauthorized actions, stale configuration revisions, and unknown compliance state fail closed.
- Important state and evidence survive restart; incomplete work remains visibly incomplete.
- The control plane must not be its own only recovery mechanism.
- Autonomy and self-modification are not authorized by this proposal. They require separate future policy and evidence.

## Relationship to architecture and roadmap

`ROADMAP.md` is the sole authority for implementation sequence, milestones, and acceptance gates. `docs/ARCHITECTURE.md` defines platform entities, persistence boundaries, and isolation threat model. `docs/PRODUCT-REDESIGN-PLAN.md` defines how these capabilities should be presented to users. This proposal is not evidence that any listed contract is implemented.
