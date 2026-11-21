# Evo learning and memory: current implementation

This document distinguishes implemented behavior from future design goals. The current system is intentionally evidence-preserving and user-directed; it is not autonomous self-training.

## Implemented

### Persistent memories
- SQLite records include category, tags, source, confidence, timestamps, status, and access counts.
- FTS5 is used when available. The LIKE fallback ranks matches by content, tags, and category relevance before confidence and recency.
- Automatic capture is currently a small set of first-person heuristics that create tentative candidates. Explicit `remember that ...` statements are stored directly.
- Candidates remain outside normal retrieval until accepted.

### Historical relationships
- A user can supersede an active memory. The old record becomes `superseded`, the replacement becomes active, and a relation links the two.
- A user can explicitly mark two records as supporting or contradicting one another.
- Related history is injected into assistant context when either record or its older wording is relevant. Contradictions are surfaced, not automatically resolved.
- Superseded records are retained; they are not silently deleted or presented as current facts.

### Experiential learning
- Coding-agent runs and tool events are stored in SQLite.
- After successful file writes, the coding agent reports whether a recognized verification command ran after the latest write and exited with code zero.
- This is a command-pattern heuristic, not semantic proof that the code is correct. A run may be complete but unverified.
- Users can inspect a run and record success, partial success, or failure.
- Users can optionally author a reusable lesson linked to that run. The lesson is retrieved later by trigger/lesson text and retains `user-run-feedback` provenance.
- Run summaries aggregate status, verification signals, review coverage, feedback outcomes, and tool-call counts.

### Retrieval evaluation
- `evo memory evaluate` seeds an isolated in-memory database from a versioned synthetic fixture.
- It reports hit rate@k, mean recall@k, and mean reciprocal rank.
- It can force FTS5 or the LIKE fallback.
- It does not touch the user's live database and does not measure recall over real personal memories.

## Important limits

- No semantic embedding retrieval or cross-encoder reranking.
- No general automatic fact extraction, memory consolidation, deduplication, or contradiction detection.
- No automatic adjudication of whether an agent task actually succeeded.
- No automatic promotion of model-generated lessons into trusted knowledge.
- No claim of near-perfect recall.
- History and context limits are character-based, not exact tokenizer budgets.
- The synthetic benchmark is a small regression set; a broader held-out evaluation is still needed.

## Next evidence-driven steps

1. Add a user-curated, held-out memory evaluation set with known expected records and difficult paraphrases.
2. Compare lexical, hybrid, and semantic retrieval against that set before adding embedding infrastructure.
3. Evaluate memory precision as well as recall; irrelevant memories injected into context can hurt.
4. Add candidate extraction for explicit corrections and outcomes, but keep tentative candidates separate from trusted lessons.
5. Add deduplication and contradiction-review workflows that preserve original records and provenance.
6. Compare coding-agent task success, intervention count, verification quality, latency, and resource use across repeated real-model tasks.

Do not treat any future step as implemented until it has tests and a reproducible evaluation.
