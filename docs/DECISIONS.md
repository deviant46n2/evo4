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
