# Development Control Plane (Proposed)

**Status: proposed architecture, not implemented.** This document describes the intended control plane as one subsystem of Evo. It does not authorize implementation, establish a schedule, or claim that direct external-agent orchestration currently exists. Development order is governed only by `ROADMAP.md`.

## Purpose

The development control plane coordinates development work across heterogeneous models, agents, tools, services, and human contributors. Its purpose is not to maximize the number of agents or to automate every action. Its purpose is to make collaboration produce measurably better outcomes than independent work while preserving authority, accountability, safety, and resource discipline.

The control plane should eventually allow Evo to coordinate work on its own development and on independent software projects. A minimal bootstrap, diagnostic, and recovery path must remain outside the control plane so that Evo can be built, started, and repaired if the control plane fails.

## Current reality and initial reference workflow

The current GPT-6/Kilo collaboration is human-mediated:
- GPT-6 provides technical reasoning, architecture, review, and selected critical implementation.
- Kilo operates locally for repository inspection, broad implementation/integration, and local validation.
- The user sets vision and retains final authority.
- GitHub is the shared source of truth and handoff mechanism.

This is a practical reference workflow, not an Evo-managed integration. Evo must not claim that it can currently dispatch work to GPT-6 or Kilo, relay their messages, observe their sessions, or coordinate them directly. Any future integration must use supported interfaces and comply with the applicable provider terms, API rules, automation policies, licensing, and data-handling requirements.

## Governance model

The control plane uses hybrid governance:

- **Hierarchical authority:** the user retains ultimate authority over purpose, policy, permissions, consequential approvals, and system-level decisions. A task has one accountable owner. Delegated participants cannot enlarge their own authority.
- **Cooperative execution:** authorized participants may deliberate, research, implement, challenge, review, and hand work to one another within explicit task and permission boundaries.
- **Independent challenge:** consequential results should receive review from a participant or verification mechanism that is not solely dependent on the contributor's own claim.
- **Evidence-based trust:** participant access and autonomy may expand only through explicit authorization and demonstrated performance. Capability claims and past success inform evaluation but do not create permissions automatically.

The system must distinguish identity, capability, trust, availability, registration, assignment, and authorization. These are separate facts and must not be inferred from one another.

## Core conceptual responsibilities

The proposed control plane is responsible for:

1. **Participant registry and discovery** — identify models, agent runtimes, tools, services, and human contributors; record versions, capabilities, interfaces, constraints, and availability.
2. **Role and assignment management** — assign task-scoped roles such as planner, implementer, researcher, reviewer, or verifier to eligible participants. Roles are replaceable responsibilities, not permanent model identities.
3. **Task ownership and orchestration** — maintain one accountable owner, explicit objectives, acceptance criteria, subtasks, dependencies, state transitions, and bounded delegation.
4. **Communication and handoffs** — exchange typed, attributable messages and artifacts; record what is being handed off, to whom, with what expected action, and under which scope.
5. **Context distribution** — provide the minimum relevant context with explicit global/project/task scope, provenance, trust classification, and access checks.
6. **Permission and approval enforcement** — authorize actions at execution boundaries, enforce least privilege, and require approval for consequential operations according to policy.
7. **Evidence and decision records** — retain proposals, challenges, decisions, verification results, source revisions, and unresolved disagreements.
8. **Execution isolation and recovery** — bind work to authorized projects/workspaces, supervise bounded execution, and recover safely from interruption or participant failure.
9. **Resource admission and monitoring** — account for compute, memory, provider quotas, latency, and cost before admitting or parallelizing work.
10. **Compliance governance** — record the applicable provider/interface constraints and prevent integrations that have not passed compliance review.

These are conceptual responsibilities, not a mandate to create one service or database table for each item. Implementation boundaries should follow demonstrated needs and existing architecture.

## Task and assignment lifecycle

The task lifecycle must be explicit and durable. A conceptual flow is:

`proposed → accepted → planned → assigned → running → review → completed`

Alternative terminal or holding states include `rejected`, `blocked`, `cancelled`, `failed`, and `interrupted`. A task may return to planning or execution after a recorded review decision, but state transitions must be validated and auditable.

Each task should retain:
- Objective, scope, priority, acceptance criteria, and accountable owner.
- Project/workspace and configuration references, where applicable.
- Authorized participants, assignments, permissions, and resource budgets.
- Context references and provenance.
- Messages, handoffs, artifacts, decisions, and verification evidence.
- State transition history, timestamps, failures, interruptions, and recovery actions.

An assignment is a bounded commitment by one participant. It defines the expected contribution, inputs, output contract, scope, permission set, resource/time budget, and completion condition. A handoff must identify the next owner/action and preserve the task's existing authority boundary. Delegation depth, concurrency, retries, and total work must be bounded to prevent loops, runaway cost, and unproductive debate.

A participant failure, timeout, or unavailable provider must not be represented as successful completion. The owner must be able to retry within policy, reassign, request human intervention, or terminate the task with an explicit reason.

## Collaboration quality and evaluation

Multi-agent execution is not inherently superior. The control plane must make it possible to compare:
- A single participant performing the task.
- Multiple participants working independently and then combining results.
- Coordinated participants using explicit roles, handoffs, and review.

Comparisons should use equivalent task definitions, inputs, environments, and acceptance criteria. Evaluate task-relevant correctness and quality alongside latency, token/compute consumption, cost, failure rate, and human intervention. Preserve negative results and cases where collaboration adds overhead without improving the outcome.

Independent review is not a ceremonial second opinion. The reviewer should have access to the required evidence and acceptance criteria, and should be able to identify unsupported claims, missed requirements, security issues, and invalid verification. Where practical, the reviewer or verifier should not be the same component that produced the result.

## Provider compliance

Every integration and communication mechanism must comply with the applicable provider's current Terms of Service, usage policies, API rules, automation restrictions, licensing requirements, and data-handling rules. Use supported interfaces and official APIs. Technical feasibility does not establish permission. No bypasses, undocumented interfaces, permission laundering, or attempts to evade provider restrictions are acceptable.

If compliance is uncertain, do not enable the integration until it has been reviewed. Compliance is checked per integration and may change when provider terms or capabilities change.

## Security and failure boundaries

- Registration is not authorization; capability is not trust; trust is not permission.
- Every action is checked against the current task, participant, project/workspace, and permission scope at the execution boundary.
- Participants cannot grant themselves permissions, approve their own privilege expansion, or silently change the task owner.
- Retrieved content, tool output, and participant messages are untrusted data unless separately validated; they cannot masquerade as privileged instructions.
- Secrets are not copied into shared context or version-controlled artifacts unless explicitly required and safely handled.
- Cancellation, timeouts, bounded retries, loop prevention, and resource budgets are mandatory.
- Important task state and evidence survive restart; incomplete work remains visibly incomplete.
- The control plane must fail closed for unauthorized execution and preserve a recovery path independent of itself.

## Relationship to the broader architecture and roadmap

The control plane implements cooperative task governance and coordination within Evo's broader platform. It depends on reliable project/workspace boundaries, participant contracts, scoped context, durable task state, evaluation, and resource management.

The authoritative implementation sequence and phase gates are in `ROADMAP.md`. The domain model and platform-wide engineering contracts are in `docs/ARCHITECTURE.md`. Product interaction requirements are in `docs/PRODUCT-REDESIGN-PLAN.md`.

No autonomous self-modification, self-approval, or self-deployment is authorized by this proposal. Future autonomy must be introduced progressively, with explicit user authorization, isolated execution, independent verification, bounded budgets, and demonstrated recovery.
