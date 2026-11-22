# Evo 4 Architecture

This document describes Evo4's intended architecture. It distinguishes current implementation from designed and long-term capabilities.

## Evo's identity

Evo is a portable, model-agnostic AI development and experimentation platform. Its purpose is to assemble, configure, evaluate, experiment with, coordinate, and continuously improve increasingly capable AI systems using existing models, agents, memory systems, tools, frameworks, and execution infrastructure.

The long-term ambition is to pursue increasingly capable, potentially superintelligent AI systems through software engineering rather than foundation-model engineering. Target areas include memory architectures, context management, agent architectures, orchestration, tool integration, evaluation, hardware/resource efficiency, autonomous research and software development, and controlled self-improvement.

Evo is not a foundation-model trainer, custom neural-network engineering project, or general-purpose machine-learning laboratory. Existing models and frameworks are components that Evo uses and experiments with; they are not the foundation of Evo's architecture.

The personal assistant and coding-agent experiences are configurations assembled using Evo, not Evo's fundamental identity.

## Fundamental entities

### Evo
The portable application providing shared infrastructure, management, integration interfaces, experimentation, evaluation, orchestration, resource management, and development capabilities.

### AI configurations
Reusable, independently versioned definitions of AI systems. A configuration may specify model/provider assignments, agent definitions and roles, memory architecture and namespaces, retrieval/context strategies, tools and integrations, orchestration strategies, execution preferences, resource requirements and limits, permissions and policies, and component versions/dependencies.

Configurations must be independently developed, versioned, branched, compared, restored, and promoted. They must not belong to a particular software project.

### Software projects
Independent development targets with their own source code, repository references, branches, permissions, dependencies, and history. A project may be Evo itself or unrelated software.

### Workspaces and sessions
Runtime environments connecting an AI configuration to one or more authorized development targets. A workspace establishes actual assignments and access boundaries. One configuration should eventually be usable against multiple projects with independent sessions/workspaces, and multiple configurations should be usable against the same project. The configuration does not own the project, and the project does not own the configuration.

### Experiments
Persistent, identifiable investigations combining a configuration, target, hypothesis, methodology, and evaluation. They must preserve hypothesis/objectives, exact configuration version, exact software-project commit/revision, relevant execution environment, model/provider identities, settings and dependencies, methodology and inputs, resource consumption, results and measurements, failures and incomplete runs, conclusions and decisions, reproducibility information, and references to source changes/artifacts. Failed experiments are valuable engineering knowledge.

### Execution environments
Infrastructure on which models, agents, tools, and experiments execute. The architecture must eventually support local execution, connected machines, external cloud providers, containers/isolated environments, and distributed execution. Execution location must not be hardcoded into the fundamental architecture.

### Resource management
A distinct subsystem responsible for discovering and managing compute, memory, models, endpoints, concurrency, provider quotas, costs, task priorities, reservations, and scheduling. It must accommodate both resource-constrained single-user installations and large distributed deployments. Coordination overhead and available resources must inform scheduling; more agents do not automatically improve results.

## Conceptual relationship

```text
Evo provides the platform.
AI configurations define reusable AI systems.
Software projects define development targets.
Workspaces and sessions connect configurations to authorized targets.
Experiments investigate and evaluate combinations of configurations, targets, and execution environments.
The experiment registry and artifact storage preserve results and evidence.
Resource management determines what can execute and where.
```

These entities must be independently identifiable and maintain appropriate histories.

## Version control and persistent engineering knowledge

AI configurations and software projects must have independent version histories. The architecture should support independent Git-backed histories and branching without assuming every entity requires a separate physical Git repository.

Use Git for source code, configuration definitions, versioned documentation, and reproducible development states. Use a persistent experiment registry for structured experiment records and searchable findings. Use artifact storage for large logs, datasets, benchmark outputs, and other large files.

Every experiment should reference exact relevant source commits, configuration revisions, and execution environment. Successful approaches, failures, abandoned hypotheses, and unexpected discoveries should be retained. Evo should be able to search historical findings and avoid unknowingly repeating unsuccessful experiments. Git should not become an indiscriminate dumping ground for large binary artifacts.

## Current implementation status

Implemented capabilities are described in `README.md` and existing docs, especially `docs/AGENT-ORCHESTRATION.md` and `docs/BACKGROUND-AGENT-EXECUTION.md`.

This architecture is not fully implemented. In particular, AI configurations, software-project management, workspaces/sessions, experiment registry, resource management, agent lifecycle, and development control plane are designed or proposed capabilities, not validated runtime features.

## Long-term self-development

Evo should eventually participate extensively in its own development: understanding its architecture and history, identifying weaknesses and opportunities, researching solutions, designing and running isolated experiments, implementing improvements in controlled environments, validating changes independently, proposing or integrating approved improvements, and improving its own research and development processes.

Autonomy should increase as reliability is demonstrated. Routine, reversible, authorized work should eventually be autonomous. Consequential operations require safeguards and appropriate approval. Safety, authorization, demonstrated reliability, and available resources constrain autonomy; there is no arbitrary prohibition on self-development.

Evo must not be allowed to declare its own improvements successful without independent evidence.

Self-improvement is a long-term capability, not something required in the initial release.

## Agent collaboration and governance

Retain the hybrid model:

- Hierarchical governance for authority, permissions, accountability, and consequential decisions.
- Cooperative agent-to-agent communication, research, challenges, task delegation, and handoffs within authorized scopes.
- Dynamic, replaceable roles rather than permanent model-specific dependencies.
- One accountable owner per task.
- No requirement for the user to manually relay messages once authorized direct integrations are available.
- Bounded delegation, concurrency, budgets, timeouts, and loop prevention.
- Persistent task history, communication records, evidence, and decisions.
- Explicit capability, trust, and authority separation.
- Progressive agent evaluation and authorization.
- Immediate suspension and revocation capability.
- Provider-specific compliance verification.

Provider terms, licensing, API permissions, automation restrictions, and data-handling rules must be respected. No bypasses or undocumented interfaces.

Agent lifecycle: discovery, evaluation, registration, authorization, availability, assignment, active work, suspension, retirement, and revocation.

The development control plane is a first-class Evo subsystem, with an independent minimal bootstrap and recovery mechanism outside it.

## Development philosophy and implementation strategy

Real AI models are not required to make substantial progress. Use deterministic mocks, simulated agents, fixtures, and conventional tests to develop and validate the platform. Real models become integration targets and experimental subjects.

Build interfaces for eventual capabilities without implementing all of them prematurely. Keep scope focused on improving AI systems through software architecture and engineering. Reuse existing software and research where practical. Preserve useful existing implementation rather than assuming a rewrite is necessary.

Every significant milestone should deliver a reusable capability, an experimentally validated improvement, or a measurable increase in what Evo can support.

## Initial deployment and portability

Initial release: single user, local-first, no mandatory accounts or cloud services, local project/configuration storage, optional cloud providers, secrets stored separately from project/configuration repositories, portable definitions where practical.

Eventually support export/import, reconstruction on another machine, and multi-user authentication. Do not make future multi-user support a prerequisite for initial development. Design for portability without sacrificing immediate optimization for the user's existing hardware.

## Platform Registry

The proposed persistent platform entity model is specified in `docs/PLATFORM-REGISTRY-V1-SPEC.md`. It is proposed architecture, not an implemented feature.

## Current vs designed vs long-term

1. Current implemented capabilities: described in `README.md` and existing docs.
2. Designed but not yet implemented architecture: this document and `docs/DEVELOPMENT-CONTROL-PLANE.md`.
3. Long-term ambitions: increasingly capable, potentially superintelligent AI systems through software engineering, including controlled self-improvement.

No proposed capability should be described as already implemented.
