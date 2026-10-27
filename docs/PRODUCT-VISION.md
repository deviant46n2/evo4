# Evo 4 Product Vision and Requirements Discovery

**Status:** Discovery draft. Not implementation authorization. Updated 2026-10-27.

This document captures established user goals and the process for resolving remaining product questions before implementation. Distinguish confirmed requirements from hypotheses and unresolved decisions. Do not treat assistant proposals as user-approved requirements.

## Product-level intent (confirmed direction)

Evo 4 should grow into a useful personal AI assistant and coding agent—not an empty framework or a demo that only becomes useful after months of infrastructure work. It should be deeply configurable, modular, expandable, and capable of evolving without tying its identity to one model provider or one memory engine.

The assistant's personal context, long-term memory, project knowledge, current task state, coding history, and ability to resume work should behave as one coherent continuity system. These may have distinct internal representations, but the user should not have to manually reconcile disconnected memories.

## Confirmed goals and constraints

- **Memory ambition:** both near-perfect historical recall and deep integrated understanding over very large accumulated histories; prioritize accuracy over latency/cost and allow multiple retrieval/verification passes.
- **Context windows:** a model's context window is a temporary working budget, not the limit of what the assistant can access. Aim to reason over millions or billions of effective historical tokens through reliable retrieval, source recovery, and synthesis. This is an aspiration to measure, not a guarantee.
- **Evidence and correction:** retain original evidence; distinguish explicit statements, observed results, inference, and uncertainty; support corrections and historical reconstruction without silently overwriting prior records.
- **Continuity:** preserve project decisions, task progress, blockers, verified results, and concrete next actions across compaction, interruptions, restarts, model changes, and long gaps.
- **Coding agent:** work against real repositories and tools; distinguish intended/attempted work from verified outcomes; use acceptance criteria and tests; preserve recoverable state.
- **Model/provider flexibility:** support local and remote models through replaceable interfaces. Do not assume paid inference is always available; free-tier availability and limits matter. Local models are desirable for privacy/control, but the current local setup is not fast enough to be the only execution path.
- **Resource awareness:** local-first where useful, avoid unnecessary infrastructure or services, and respect the user's desktop/hardware budget. Do not introduce heavyweight components without evidence they are needed.
- **Privacy and training:** conversations and arbitrary personal data must not automatically become training data. Any future training-data collection requires deliberate privacy controls and explicit consent.
- **Modularity:** build independently testable capabilities with stable contracts; avoid premature microservices and duplicated implementations. Reuse useful existing UIs/components rather than rebuilding them without a reason.
- **Scientific discipline:** separate verified implementation behavior from documentation/README claims and hypotheses. Use reproducible evaluations, fixed regression tests, baselines, resource limits, and rollback where appropriate.
- **Control and auditability:** the user should be able to inspect, steer, correct, pause, and recover the system's work and memory. Preserve provenance and exportability; use permissions and read-only inspection before consequential mutation.
- **Quality bar:** security and reliability matter. Do not release or recommend public-facing software merely because it works on a happy path; avoid unsupported assurances and explicitly identify unresolved risks.
- **Development preference:** do substantial research and synthesis for the user; do not require the user to benchmark several competing systems when a careful evidence-based choice can be made. Record design decisions and push note milestones, while clearly labeling them as proposals or confirmed requirements.

## Learning, autonomy, and self-modification (discovery updates, 2026-10-27)

### User-confirmed direction

- Evo should eventually replace both ChatGPT and OpenCode as the user's unified personal AI workspace, with detailed personal context under the user's control.
- It should begin broadly like ChatGPT but become more capable through use, learning meaningful lessons that change future behavior—not merely accumulating a searchable transcript.
- Learning should span anything the user does through Evo: conversations, research, coding, project work, games, planning, and task outcomes. Evo should connect domains when evidence supports a meaningful relationship.
- The user wants Evo to develop an increasingly rich understanding of their preferences, working style, projects, and intent, and to be able to inspect and steer that understanding.
- The user is comfortable with Evo initiating its own research and learning between interactions.
- Adaptation should be evidence-proportional: some well-supported, low-risk lessons can be applied immediately; uncertain lessons may need further testing; confidence alone is not evidence.
- Initially, Evo modifying its own code must be a human-in-the-loop process. This boundary may be revisited later.
- The user needs a reliable way to reclaim GPU VRAM. Which components must stop depends on the architecture: deterministic services may remain running if their resource costs are acceptable, while GPU-resident models may need unloading. Durable memory and task state should survive model unload/shutdown.

### Design implications (proposals, not finalized architecture)

- Preserve the original experiences and provenance behind learned lessons; distinguish statements, hypotheticals, preferences, observed outcomes, and inferences.
- Track candidate lessons with evidence, confidence/uncertainty, scope, observed outcomes, and correction/reversal history.
- Evaluate whether lessons generalize and improve future outcomes, including game strategy and cross-project synthesis.
- Provide inspectable autonomy controls and a tested resource-release path that can unload GPU models without destroying durable continuity.
- Keep ordinary learning distinct from code self-modification. Initially, code changes should be proposed and tested in isolation, then await human approval before activation.
- Do not infer permission for unrestricted self-modification, independent unrelated goal formation, or model-weight changes from the user's interest in autonomy.

### Still open

- Exact boundaries for autonomous research, data access, tool use, and external side effects.
- How the user inspects, corrects, or disables a learned lesson, and how Evo identifies drift or false patterns.
- What evidence and safeguards code changes require before approval and activation.
- Whether learning will eventually include training/changing model weights; no decision has been made.
- What “pause,” “VRAM release,” and “full shutdown” guarantee in measurable terms.
- Capture, retention, and deletion policies for sensitive content, accidental disclosures, hypothetical statements, and information the user asks Evo not to use.

## Recent external research (2026-10-27)

A preliminary scan found adjacent projects rather than a verified complete substitute for Evo:
- **Hermes Agent** is the most relevant candidate to investigate for an agent that advertises learning through experience and reusable skills. Those claims still require task-based validation; they do not prove reliable improvement at chess/MTG or general long-term intelligence.
- **OpenViking** is a possible structured context/filesystem layer for memories, resources, and skills, not a complete autonomous personal AI.
- **Hindsight** is a possible memory/reflective-belief component for retaining experiences and revising beliefs, not a complete agent.
- **OpenJarvis** is relevant to the personal/local assistant direction, but the reviewed material did not establish the same explicit experience-to-skill loop.
These are research leads, not selected dependencies. No decision has been made to adopt any of them. Compare against Evo-specific tasks, integration costs, security, resource usage, and actual observed behavior before selecting components.

## Current provisional memory direction

MemSearch is a provisional first coding-session memory component to test, not the whole Evo 4 architecture. See docs/ARCHAEOLOGY.md and docs/MEMORY-ARCHITECTURE.md. Its behavior must be verified in a disposable setup. Do not assume it handles full ChatGPT-history ingestion, cross-source claim provenance, temporal correction semantics, or evidence-sufficiency checks until tested.

## Discovery rules before implementation

1. **No implementation begins merely because a plausible architecture has been proposed.** First establish the user's intended experience, use cases, boundaries, and success criteria.
2. Ask focused conversational questions, generally one high-impact unresolved question at a time. Avoid overwhelming the user with a giant requirements form.
3. Maintain a decision log with: question, options considered, user's decision, rationale, evidence, consequences, and status (confirmed / provisional / open / rejected).
4. Distinguish user requirements from assistant recommendations, research findings, and implementation assumptions.
5. For each major capability, define realistic success/failure examples and how it will be tested.
6. Resolve important security, privacy, autonomy, cost, and failure-recovery requirements before selecting architecture that would make them difficult to retrofit.
7. Periodically summarize the emerging product specification for user correction. Do not begin substantial implementation until the user agrees that the specification accurately represents what they want.
8. Keep the first usable product in view. Avoid an indefinitely expanding architecture exercise: discover the minimum coherent, genuinely useful assistant and then define safe, measurable stages of evolution.

## High-priority open questions

These are intentionally unanswered; do not infer answers from assistant suggestions.

- What should the assistant feel like to use day to day? One conversational cockpit, a coding-first workspace, or several coordinated interfaces?
- Which initial tasks must it perform reliably to be genuinely useful from day one?
- What does “autonomous” mean in practice: what may it inspect, change, run, install, spend, or publish without approval?
- Which sources should be in memory (ChatGPT history, coding-agent sessions, repositories, local files, tool outputs, web research), and what are the opt-in/retention/deletion rules for each?
- What must be local/private by default, and what may be sent to remote model providers?
- How should model selection, fallback, free-tier limits, latency, and task routing work?
- What must the user be able to inspect, edit, correct, export, forget, or roll back?
- What are acceptable failure modes and required recovery guarantees?
- What is the smallest useful first release, and what would prove it is worth continuing?
- Which capabilities are explicitly out of scope for the initial product?

## Current state

This is a discovery charter, not a complete product specification. Only the goals and constraints in the confirmed sections should be treated as established. Open questions require discussion. No implementation is authorized by this document alone.
