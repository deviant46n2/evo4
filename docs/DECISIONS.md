# Evo 4 Decision Register

This is the canonical record of decisions that materially constrain Evo 4. Add an entry when a choice changes project direction, architecture, scope, safety, workflow, or acceptance criteria.

## Status definitions

- **Active:** Current decision.
- **Provisional:** Working choice pending evidence or explicit user confirmation.
- **Superseded:** Replaced by a later decision; retained for history.
- **Rejected:** Considered and explicitly ruled out.

## D-001 — Maintain durable notes throughout discovery

- **Status:** Active
- **Date:** 2026-10-27
- **Decision:** Keep working notes, a decision register, and an archaeology index in the Evo 4 GitHub repository, updating them as the project develops.
- **Rationale:** Important choices and lessons must survive context changes and long gaps between sessions.
- **Consequences:** Meaningful discussions should end with repository notes updated. Changed decisions must retain their history and explain why they changed.

## D-002 — Investigate prior art before committing to architecture

- **Status:** Provisional
- **Date:** 2026-10-27
- **Decision:** Start with evidence-based review of existing projects rather than immediately designing or implementing Evo 4.
- **Rationale:** The software graveyard contains both reusable work and lessons about approaches that did not deliver.
- **Consequences:** Separate documented intent, implementation, tests, and verified behavior. Present a synthesis for user review before treating architectural recommendations as requirements.

## D-003 — Optimize for a small tool the user will use daily

- **Status:** Active
- **Date:** 2026-10-27
- **Decision:** Keep Evo 4's intended scope deliberately smallish and build only what serves its clearly defined primary user need.
- **Context / problem:** Prior projects risk expanding into ambitious systems before the exact daily-use outcome has been nailed down.
- **Options considered:** Start architecture/features immediately; combine all prior projects; or first define the desired everyday outcome and hard boundaries.
- **Rationale:** The user explicitly wants to nail down exactly what they are looking for, build only that, and end up with something useful in daily life.
- **Consequences:** Requirements discovery precedes architecture. Each proposed feature must be justified against the primary job. Explicit non-goals and a scope ceiling are required. Past interests and existing code are evidence, not automatic requirements.
- **Not yet specified:** The primary daily workflow, essential capabilities, and explicit non-goals.
- **Revisit when:** The user explicitly changes the intended outcome or evidence shows the scope boundary prevents the core job from working.
- **Related decisions:** D-001, D-002.

## D-004 — Product intent: persistent-memory chatbot and coding agent

- **Status:** Provisional
- **Date:** 2026-10-27
- **Decision / user-stated intent:** Evo 4 should combine a chatbot with persistent memory and a coding agent.
- **Examples given by the user:**
  - Use accumulated knowledge of the user to recommend movies they are likely to enjoy.
  - Work on code without repeatedly rereading the same files or needlessly rediscovering project context.
- **Context / problem:** The user wants an assistant that knows them over time and a coding agent that retains useful working knowledge instead of behaving as if every session starts from zero.
- **Current hypothesis:** Durable, retrievable knowledge may support both use cases, but the memory representation and whether the two use cases share mechanisms are not decided.
- **Scope guard:** This does not authorize a general AI workstation, broad autonomous agent platform, or every feature explored in earlier projects.
- **Unresolved:** Which use case sets the minimum viable product, the first concrete daily workflow, what should be remembered, how memory is corrected/forgotten, and how to avoid stale or incorrect project context.
- **Revisit when:** The user clarifies priority and a concrete workflow, or archaeology reveals evidence that changes the smallest viable approach.
- **Related decisions:** D-001, D-002, D-003.

## D-005 — Treat context loss and state-tracking as distinct user problems

- **Status:** Provisional
- **Date:** 2026-10-27
- **User-stated problems:** The user is frustrated by loss of context between sessions, finite context windows, and my unreliable tracking of a multi-turn Magic: The Gathering game.
- **Current interpretation:** Evo 4 should aim for reliable continuity, not simply accumulate a large memory store. The relevant problems may require different mechanisms: durable cross-session memory, context selection/compaction, and explicit state tracking with validation.
- **Technical constraint:** Memory does not eliminate a model's native context-window limit. The product can instead externalize information and restore relevant context when needed.
- **Rationale:** These failures directly undermine the desired experience of an assistant that knows the user, retains project understanding, and can reliably continue multi-step work.
- **Scope guard:** This is a problem statement, not a commitment to implement all three mechanisms in the first release.
- **Unresolved:** Which failure is most costly in daily use, what workflow best demonstrates it, and what correctness standard is necessary.
- **Revisit when:** The user prioritizes the first workflow or evidence from prior projects identifies a smaller solution.
- **Related decisions:** D-003, D-004.

## D-006 — Treat continuity as one unified product goal

- **Status:** Active
- **Date:** 2026-10-27
- **Decision:** The user chose option D: persistent personal memory, coding continuity, and reliable ongoing state are inseparable parts of the desired Evo 4 experience.
- **Context / problem:** The user does not want three disconnected tools or a narrow memory feature that leaves the broader continuity problem unsolved.
- **Rationale:** The desired assistant should know the user over time, continue coding work without needless rediscovery, and maintain reliable state during multi-turn activities.
- **Consequences:** Requirements discovery should seek a coherent end-to-end continuity experience. A unified product goal does not dictate one memory schema, one storage system, or a large first release; distinct information types may require distinct handling and validation.
- **Scope guard:** Find the smallest workflow that demonstrates this continuity before committing to architecture or expanding features.
- **Unresolved:** The concrete first workflow, measurable definition of success, and explicit non-goals.
- **Related decisions:** D-003, D-004, D-005.


## D-007 — Maintain a compact persistent starting context

- **Status:** Active
- **Date:** 2026-10-27
- **Decision / user-stated minimum:** At the start of any request, Evo 4 should be oriented by compressed knowledge of itself and its capabilities, plus the basics of the user's projects and interests.
- **Intended outcome:** Evo 4 can begin a broad range of requests with useful baseline context rather than repeatedly asking the user to reintroduce themselves or re-explain basic project context.
- **Current product interpretation:** Maintain a compact persistent starting context that serves as a launchpad, then retrieve deeper task-specific records as needed. The compact context is not the entire memory archive.
- **Candidate information categories:** (1) self-knowledge about purpose, tools, models, capabilities, limitations, and what is currently available/verified; (2) compressed user interests/preferences and project goals/status/decisions; (3) pointers to authoritative detail and request-specific retrieval.
- **Rationale:** This is the minimum continuity foundation that connects personalized assistance and coding work without loading the entire history into every request.
- **Trust constraint:** Distinguish configured, currently available, and verified capabilities; do not treat aspirational or stale capability claims as facts. Summaries should point to deeper records and remain correctable.
- **Scope guard:** This does not prescribe a storage architecture, imply that every record should be loaded for every request, or authorize broad autonomous-agent scope.
- **Acceptance criteria still to define:** What the context must contain; how it is refreshed/corrected; and observable tests across personal-interest, project/coding, and evolving-state requests.
- **Related decisions:** D-003, D-004, D-006.


## D-008 — The persistent starting context must be updatable

- **Status:** Active
- **Date:** 2026-10-27
- **Decision / user-stated requirement:** The persistent starting context must be updatable; it cannot be a static profile maintained manually by the user.
- **Consequences:** Evo 4 should be able to incorporate useful new information about the user, projects, goals, decisions, and its own capabilities into durable records and refresh the compact starting context as those records change.
- **Reliability constraint:** Distinguish explicit statements and verified observations from inferred preferences or uncertain interpretations. New information should not automatically become an authoritative fact merely because the model inferred it.
- **Conflict-handling direction:** Reconcile conflicts rather than blindly overwrite. Honor clear revised decisions while retaining useful history; surface ambiguity when the correct interpretation is uncertain.
- **Unresolved:** Which updates happen automatically versus require confirmation; how users inspect, correct, or withdraw information; and how to detect stale or conflicting records.
- **Related decisions:** D-001, D-006, D-007.


## D-009 — Evidence-led behavior; validate outputs before claiming correctness

- **Status:** Active
- **Date:** 2026-10-27
- **User-stated requirement:** Evo 4 should be scientific: never guess an output; review and validate it.
- **Operational interpretation:** Do not present guesses as established facts or outputs as validated unless appropriate checks actually occurred. Distinguish observations, user statements, sourced facts, inferences, hypotheses, and unknowns.
- **Consequences:** Important claims and memories should retain provenance; generated outputs should be checked against suitable criteria; failures, incomplete checks, and uncertainty must be disclosed; corrections should preserve a useful history.
- **Validation is output-specific:** Code may require tests, diff review, and execution; factual answers may require reliable sources; calculations may need independent recomputation; structured ongoing state may need invariant/rule checks. Do not claim a test or check ran if it did not.
- **Practical limitation:** Absolute prevention of internal guessing and infallible verification cannot be guaranteed. The enforceable product standard is to prevent unsupported assumptions from being silently promoted to facts and to make validation status and limitations inspectable.
- **Unresolved:** Evidence thresholds by output type; required automated checks; confirmation boundaries; and a proportionate workflow that preserves daily usability.
- **Related decisions:** D-001, D-003, D-007, D-008.


## D-010 — Keep real-time conversation available during background work

- **Status:** Active
- **Date:** 2026-10-27
- **User-stated hard requirement:** The user must be able to talk to Evo 4 in real time, with a subagent able to answer regardless of what else Evo 4 is doing.
- **Rationale:** Conversation is expected to be a major source of persistent memory and must not be blocked by long-running coding or research tasks.
- **Consequences:** Treat interactive conversation as a first-class workload. Background tasks must not monopolize all response capacity; investigate reserved/independently schedulable inference, prioritization, task-status visibility, and interruption/control semantics.
- **Architecture caution:** A subagent abstraction alone does not guarantee responsiveness if the underlying model slots, GPU, or inference services are saturated. Define and test a latency/availability target under realistic load.
- **Memory consequence:** Conversation-derived preferences, decisions, corrections, and requirements should be captured for durable memory without making live interaction wait for background memory processing. Preserve provenance and apply D-009's evidence/validation rules.
- **Scope guard:** Start by proving that conversation remains responsive during one meaningful background task; do not assume a general multi-agent platform is required.
- **Unresolved:** Exact latency target; what the conversational agent can control versus merely advise; resource-isolation strategy; and behavior under total inference-capacity exhaustion.
- **Related decisions:** D-003, D-006, D-007, D-009.


### D-010 clarification — Interruption with reliable resumption

- **Date:** 2026-10-27
- **Status:** Active; this clarification narrows the implementation requirement, not the user-facing goal.
- **User clarification:** It is acceptable to interrupt ongoing work, get an answer, and have Evo 4 return to where it was.
- **Refined requirement:** Work must be interruptible at safe points; the assistant answers the user, then resumes the original task from a durable checkpoint with progress and task intent intact.
- **Required state:** At minimum, track completed work, current step/checkpoint, relevant artifacts/changes, remaining work, and validation status.
- **Correctness constraint:** Check whether the interruption or external changes invalidated prior assumptions or checks; revalidate affected work before proceeding when needed. Do not depend on a vague model-generated recollection of the prior task.
- **Implementation flexibility:** A permanently separate conversational agent is optional if the interruption/resumption experience is reliable. Subagent support alone is not the requirement.
- **Unresolved:** Latency target, handling of operations that cannot be paused safely, and the checkpoint granularity needed for robust recovery.

## Decision template

### D-XXX — Short decision title

- **Status:** Provisional
- **Date:** YYYY-MM-DD
- **Decision:**
- **Context / problem:**
- **Options considered:**
- **Rationale:**
- **Evidence:**
- **Trade-offs / consequences:**
- **Revisit when:**
- **Related decisions:**


## D-011 — Product identity sharpened: replace ChatGPT + coding agent, integration-first

- **Status:** Active (user-stated, 2026-10-27)
- **Decision / user-stated intent:** Evo 4 must replace ChatGPT for (1) conversational collaboration, (2) movie/game recommendations, (3) project design/decision-making, and (4) coding-agent work. The user is pragmatic about form: "it might just end up being opencode + a memory plugin + some mcps and that would be fine as long as it does what I need."
- **Context / problem:** D-004/D-006 already named the two use cases; this entry adds the implementation stance — integration of existing, proven tools is acceptable and preferred over a greenfield platform. This is the scope ceiling's first concrete expression: no new platform unless an existing tool demonstrably fails a must-have.
- **Consequences:** The default hypothesis is "opencode + opencode-mem (or Nemoxiom-derived memory) + MCPs," not a new application. Any proposal to build new infrastructure must justify itself against a demonstrated gap in that stack. This also means the "replace ChatGPT" bar is about *behavior* (it knows me, it resumes work, it recommends well), not about cloning ChatGPT's web UI.
- **Unresolved:** Whether the opencode TUI surface is acceptable as the chat surface long-term (vs. a web UI like Odysseus/Open WebUI), and which specific capability gaps in the current stack are the actual blockers.
- **Related decisions:** D-003, D-004, D-006, D-007.


## D-012 — "Already there": Evo 4 is harden + close gaps, not replace

- **Status:** Active (user-stated, 2026-10-27)
- **Decision / user-stated:** The user reports they are "already there" — this assistant is already their first stop when free AI runs out. The current stack (opencode + memory plugin + MCPs) already satisfies the "replace ChatGPT" bar for daily use.
- **Consequences:** Evo 4 is NOT a greenfield replacement for a working setup. It is (a) hardening what already works so it doesn't break (quota, context loss, stale state), and (b) closing the specific gaps that still frustrate. Scope ceiling tightens: anything that doesn't address a real, current frustration is out of scope.
- **Unresolved:** Which 2-3 frustrations are the actual blockers worth fixing in v1 vs. leaving alone.
- **Related decisions:** D-003, D-011.


## D-013 — Near-term priority: local model as usable fallback; context-as-1B is long-term

- **Status:** Active (user-stated, 2026-10-27)
- **Decision / user-stated:** Two-tier priority. (1) Near-term: make the local setup (llama.cpp + 27B model) work much faster/better so that when free-tier AI runs out, the user can fall back to the local model for basics. (2) Long-term: context constraints should be software-solved — a 100k-context system should behave like a 1B-context system. The long-term ambition is already captured in docs/MEMORY-ARCHITECTURE.md; do not let it scope-creep into v1.
- **Consequences:** v1 success is measured by "local fallback is usable for basics," not by eliminating context limits. The context-as-1B goal is explicitly deferred to a later phase. This also means VRAM management (Omega/cyberdeck patterns) and inference speed are first-class v1 concerns, not polish.
- **Unresolved:** What "basics" means concretely (which tasks the local model must handle) and what speed/quality threshold counts as "usable."
- **Related decisions:** D-003, D-011, D-012.
