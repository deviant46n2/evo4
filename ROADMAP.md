# Evo4 Roadmap

This document records agreed planning decisions and a provisional development sequence. It is not a statement that any proposed capability is already implemented.

## Agreed principles

- Evo's first objective remains maximizing useful capabilities on the user's existing hardware.
- Local operation must remain useful; optional cloud providers must not become a paid dependency.
- Autonomous self-modification is not the current objective.
- GitHub remains the immediate shared engineering workspace and permanent source of truth.
- Human steering and accountability remain mandatory for consequential decisions.
- Provider compliance is mandatory: use supported interfaces and official APIs only.
- Roles are contracts, not fixed model identities. Provider/model identities must be replaceable.
- Every task has one accountable owner, even when several agents contribute.
- Cooperative agent communication is allowed, but authority, permissions, and consequential decisions remain governed.
- Agents may propose and execute bounded low-risk work only within explicitly granted scopes.
- Agents cannot grant themselves permissions or expand their own authority.
- A minimal independent bootstrap/recovery mechanism must remain outside the control plane.

## Proposed roadmap

This sequence is provisional. Dependencies and acceptance criteria must be refined before implementation.

0. Development governance: authority model, roles, task ownership, approval boundaries, decision records.
1. Shared engineering records: GitHub-first synchronization, durable tasks, decisions, evidence, and status.
2. Diagnostics and reproducibility: structured logs, diagnostic bundles, run identities, sanitized evidence.
3. Automated quality infrastructure: CI, tests, builds, security checks, regression gates, machine-readable results.
4. Agent abstraction: provider-independent identities, capabilities, adapters, and role assignment.
5. Communication protocol: persistent messages, task handoffs, context exchange, event records.
6. Development control plane: unified coordination, oversight, permissions, approvals, and monitoring.
7. Lifecycle supervision: builds, runtime identity, startup/shutdown, health checks, safe activation, rollback, recovery.
8. Compliance and integration governance: provider-specific policy records, verification, data handling, and ongoing review.

Dependencies and adjustments should be revisited before each milestone. Avoid building elaborate orchestration before simpler GitHub-first foundations are proven.

## Current implementation status

Implemented capabilities are described in `README.md` and the existing docs. In particular, `docs/AGENT-ORCHESTRATION.md` describes the current Agent Orchestration v1 implementation and its limitations. This roadmap does not mark any proposed capability as complete.
