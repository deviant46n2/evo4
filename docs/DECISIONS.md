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
