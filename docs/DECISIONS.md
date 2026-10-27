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
