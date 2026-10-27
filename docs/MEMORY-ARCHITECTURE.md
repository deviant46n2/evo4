# Evo 4 Long-Term Memory Architecture

**Status:** Design direction agreed 2026-10-27. Not implemented or validated.

## Goal

Support both near-perfect historical recall and deep integrated understanding over a potentially enormous accumulated history. Prioritize accuracy over latency and inference cost; multiple retrieval and verification passes are acceptable. A 100k-token context window is a bounded working/reasoning space, not total memory capacity. The goal is reliable access to and reasoning over a huge evidence corpus, not literal all-at-once context.

## Non-negotiable invariant

> Derived memory must not silently overwrite its evidence; an answer is not historically verified merely because retrieval returned a plausible result; and task completion requires evidence appropriate to the acceptance criteria.

## Separate four logical responsibilities

1. **Evidence archive — authoritative history.** Preserve original conversation turns, tool outputs, files/artifacts, code changes, explicit corrections, timestamps, and stable source IDs. Prefer append-first event capture. Integrity checks can detect some later modification but cannot prove source content was true when recorded.
2. **Claim/event ledger — recorded assertions.** Store claims and state transitions with evidence links, claim type (user-stated, tool-observed, inferred, unresolved), recorded time, applicable/valid time where meaningful, status, and correction/supersession links. Distinguish “the user explicitly said X” from “Evo infers X.”
3. **Understanding layer — derived interpretation.** Maintain project models, relationships, explanations, preferences, patterns, and dependencies. These are revisable interpretations linked to supporting claims/events, not replacements for the source record.
4. **Rebuildable retrieval indexes.** Support exact/lexical search, semantic search, structured metadata and time filters, entity aliases, topic maps, and relationship traversal. Indexes should be regenerable from durable source records.

These are logical responsibilities, not a requirement to start with four database products. Begin with the smallest durable implementation and add components only when evaluation demonstrates a need.

## Retrieval is evidence gathering, not top-k answer generation

For each nontrivial historical or synthesis question:

1. Classify the question: exact recall, current/historical state, cross-session synthesis, causal explanation, recommendation, or mixed.
2. Define evidence obligations: required subquestions, relevant source types/time ranges, and what would constitute sufficient support.
3. Search useful routes independently: exact text/IDs, semantic similarity, structured filters, chronology, and relationships. Keep route results distinguishable during reconciliation.
4. Expand hits into original passages and surrounding context; follow links to related decisions, corrections, artifacts, test outcomes, and later events.
5. Reconcile chronology and conflicts. Separate valid time (when a fact applied) from recorded time (when Evo learned/recorded it). Identify current, superseded, disputed, and unknown information.
6. Audit coverage against the original evidence obligations; search again for gaps, counterevidence, near-duplicates, and unsupported premises.
7. Answer with traceability and calibrated certainty. If evidence remains insufficient or resource limits are reached, state the gap rather than claiming completeness.

The model's own judgment that it has “enough evidence” is not sufficient by itself. Use explicit coverage criteria and independent checks where practical. Evaluate search relevance, source support, and final answer correctness separately.

## Durable task state and interruption recovery

Represent active work as versioned state containing: objective and acceptance criteria; verified progress and artifact/test references; attempted but unverified operations; unfinished work/blockers; decisions and constraints; next concrete action; and resume instructions.

Explicitly distinguish intended, attempted, and verified. “Tests requested” is not “tests passed”; “patch applied” is not “bug fixed.”

On interruption, persist the last safe state and in-flight operation status, including what may have partially completed. On resume, inspect actual repository/tool state rather than blindly trusting a checkpoint, reconcile intervening changes, and continue from the first unverified step—or ask if the next action is unsafe or ambiguous. Checkpoints aid resumption; event history enables reconstruction and audit.

## Context assembly

Treat the context window as a task-specific budget, not a memory store. Allocate space adaptively among operating rules, task/acceptance criteria, relevant user/project state, primary evidence, contradiction/counterevidence analysis, and a safety margin. Any percentage allocation is a hypothesis to benchmark, not a universal optimum.

Use hierarchical navigation (corpus/project/topic maps → event/claim records → original passages/artifacts). Summaries are navigation aids and compressed interpretations; retrieve originals when exact wording, chronology, qualifications, or disputed facts matter. Retrieval must be able to fetch more evidence after initial context assembly.

## Evaluation gates

Maintain a fixed adversarial regression set covering:

- Exact historical recall with correct source/span and date.
- Cross-session synthesis where evidence is spread across distant sessions.
- Temporal queries before and after corrections or superseding decisions.
- Contradictory sources, false premises, near-duplicates, and stale summaries.
- User facts vs project facts; explicit statements vs inference.
- Interrupt/restart/replay recovery without silent loss or duplicate capture.
- Task resumption against real artifacts and test outputs.
- Evidence coverage, unsupported-claim rate, false certainty, and appropriate uncertainty/abstention.
- Archive scale, retrieval latency, resource consumption, and external-provider calls.

Do not rely on hand-picked demo questions or a single aggregate retrieval score. Retrieval recall can be high while synthesis is wrong. Track retrieval and answer quality separately. “Near-perfect” is a measured objective with explicit failure reporting, not a guarantee.

## Implementation sequence

1. Prove durable capture, stable IDs, source links, timestamps, and restart/idempotency behavior.
2. Add an inspectable claim/event ledger and versioned active task state.
3. Implement exact search and structured/time filtering first; add embeddings and graph traversal only where measured results justify them.
4. Add iterative retrieval, evidence expansion, contradiction handling, and coverage checks.
5. Run the fixed regression suite after meaningful changes; prioritize accuracy over latency while measuring cost.
6. Scale complexity only in response to demonstrated failure modes.

## Relationship to MemSearch

MemSearch remains the provisional first coding-session memory candidate, not the complete Evo 4 architecture. Its Markdown-backed source of truth and documented OpenCode capture/recovery behavior are promising but must pass the existing adoption gate in `docs/ARCHAEOLOGY.md`. Do not assume this architecture exists merely because MemSearch is installed. Full ChatGPT-history ingestion, source-linked cross-source claims, explicit temporal correction semantics, and evidence-sufficiency verification remain unproven until tested.

**Evidence status:** This file records design direction agreed in discussion on 2026-10-27. It is not implementation evidence, a security review, or a benchmark result.
