# Evo4 Roadmap

Evo is a portable, model-agnostic AI development and experimentation platform. Its purpose is to assemble, configure, evaluate, experiment with, coordinate, and continuously improve increasingly capable AI systems using existing models, agents, memory systems, tools, frameworks, and execution infrastructure.

The long-term ambition is to pursue increasingly capable, potentially superintelligent AI systems through software engineering rather than foundation-model engineering. The personal assistant and coding-agent experiences are configurations built on this platform, not its fundamental identity.

This roadmap is provisional. Dependencies and acceptance criteria must be refined before implementation.

## Agreed principles

- Evo is not a foundation-model trainer or general-purpose ML laboratory.
- Models and external frameworks are replaceable components, not architectural foundations.
- Evo owns its interfaces, integration contracts, experiment records, evaluation criteria, and orchestration.
- Real models are integration targets and experimental subjects, not prerequisites for development.
- GitHub remains the immediate shared engineering workspace and permanent source of truth.
- Human steering, accountability, provider compliance, and safety constraints remain mandatory.
- Every task has one accountable owner.
- Routine, reversible, authorized work may eventually become autonomous; consequential actions require safeguards and authorization.
- Evo must not declare its own improvements successful without independent evidence.

## Proposed roadmap

0. Architectural reconciliation and development governance.
1. Portable application foundation, persistent storage, and entity management.
2. Independent software-project and AI-configuration management.
3. Git integration, version histories, branching, and workspace isolation.
4. Provider/model/agent integration contracts and execution adapters.
5. Resource discovery and resource-aware execution management.
6. Persistent experiment registry, artifacts, evaluation, and reproducibility.
7. Agent lifecycle, communication, and orchestration.
8. Memory, context, retrieval, and intelligence experimentation.
9. Autonomous research and increasingly capable software development.
10. Controlled self-improvement and more advanced autonomous development.

Do not treat this order as immutable. Refine dependencies where architecture justifies it. Avoid building elaborate orchestration before simpler GitHub-first foundations are proven.

## Platform Registry specification

The proposed v1 platform registry specification is in `docs/PLATFORM-REGISTRY-V1-SPEC.md`. It is a proposed engineering baseline, not implemented functionality.

## Current implementation status

Implemented capabilities remain described in `README.md` and existing docs. Proposed architecture is described in `docs/ARCHITECTURE.md` and `docs/DEVELOPMENT-CONTROL-PLANE.md`. Nothing in this roadmap should be read as claiming that proposed capabilities are already implemented.
