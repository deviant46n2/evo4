# Development Control Plane (Proposed)

This document describes a proposed Evo4 subsystem. It is not an implemented feature.

## Purpose

The development control plane is intended to become a first-class Evo4 subsystem for coordinating development work, compatible agents, evidence, permissions, and approvals. It is not merely an external development helper.

Evo should eventually be able to use its own control plane to coordinate development work. A minimal independent bootstrap/recovery mechanism must remain outside the control plane so Evo can still be built, started, and repaired if the control plane fails.

## Agreed principles

- Hybrid collaboration: cooperative agent networks plus hierarchical governance.
- Every task has one accountable owner.
- Multiple agents may independently review or challenge work.
- The system must prevent uncontrolled delegation, circular handoffs, infinite debate, duplicate work, and permission escalation.
- Agents may discover problems, investigate opportunities, conduct authorized research, and propose tasks.
- Low-risk work may execute within explicitly granted scopes.
- Consequential actions require appropriate approval.
- Agents cannot grant themselves permissions or expand their own authority.
- Budgets, timeouts, delegation depth, concurrency, cancellation, and auditability must be explicit.
- Provider compliance is mandatory and must be verified before enabling an integration.
- Human steering and accountability remain central.
- Agent activity, proposals, decisions, evidence, permissions, and pending approvals should be visible and understandable.

## Proposed components

- Human interface and oversight.
- Agent registry and capability discovery.
- Role and assignment management.
- Task orchestration and ownership.
- Durable communication and handoff protocol.
- Context distribution and shared task records.
- Permission and approval engine.
- Evidence and decision ledger.
- Provider/model/tool adapters.
- Isolated execution environments and workspaces.
- Monitoring, diagnostics, budgets, and recovery.
- Provider compliance register.

## Provider compliance

Every integration and communication mechanism must comply with the applicable provider's current Terms of Service, usage policies, API rules, automation restrictions, and licensing requirements. Use supported interfaces and official APIs. Technical feasibility does not establish permission. If compliance is uncertain, do not enable the integration until verified.

## Current status

This is proposed architecture only. GitHub remains the immediate shared engineering workspace. Direct agent-to-agent integrations should be considered only when supported by provider terms and when they offer a meaningful advantage over the GitHub-first workflow.

No autonomous self-modification or self-deployment is authorized by this document.
