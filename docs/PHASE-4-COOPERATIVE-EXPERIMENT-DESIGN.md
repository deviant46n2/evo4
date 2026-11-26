# Phase 4 — Cooperative Experiment Design (proposal)

**Status:** Proposed design; not implemented or accepted  
**Owner:** GPT-6, technical lead  
**User role:** Vision Officer / scope authority  
**Prerequisite:** Phase 3 formally accepted on 2026-11-25  
**Dispatch posture:** Existing global/workspace dispatch defaults remain unchanged; no live provider invocation is authorized by this document.

## 1. Purpose and falsifiable question

Phase 4 must determine whether Evo's coordination policy produces better task outcomes than a strong single-participant strategy under a comparable resource budget.

The established premise is that additional inference-time compute can improve some model outputs. Phase 4 does **not** attempt to prove that premise. It tests Evo's distinct contribution:

> Given a task, can Evo select, sequence, and combine distinct participants so that the resulting quality/cost/latency trade-off is better than the best available single-participant strategy?

The hypothesis is conditional, not universal. Cooperation may help some task classes and harm others. Evo must be able to record when collaboration adds no value or makes results worse.

## 2. Bounded first vertical slice

Use a small, fixed set of isolated software-maintenance tasks in a dedicated benchmark project. Each task must have:
- a frozen task statement and repository revision;
- explicit acceptance criteria;
- a reproducible test/build command set;
- a known starting state and isolated working copy;
- a task-level time and resource ceiling;
- no production credentials, external side effects, or destructive actions.

The first workflow is sequential and approval-first:

1. **Independent proposal:** Participant A receives the task and scoped repository context and produces a proposed patch or implementation plan.
2. **Independent challenge:** Distinct Participant B receives the original task and repository baseline, not A's private reasoning. B identifies omissions, counterexamples, and likely defects, and may propose an alternative. It must not silently inherit A's conclusions.
3. **Synthesis:** A receives B's structured critique and produces a final candidate. The handoff records exactly which critique items were accepted, rejected, or left unresolved, with reasons.
4. **Verification:** Run only the task's predeclared deterministic checks in the isolated checkout. Preserve command, exit code, bounded output, and artifact/revision identity.
5. **Adjudication:** Report task success only from the acceptance criteria and verification evidence. Model confidence or a participant's self-assessment is not proof. Human review resolves criteria that cannot be judged mechanically.

This first slice does not include unrestricted agent-to-agent chat, recursive delegation, autonomous tool permission expansion, parallel execution, self-modification, or autonomous benchmark creation.

## 3. Participant distinctness and availability

A genuine cooperation run requires at least two distinct model participants. Distinctness is established from the revision-pinned participant descriptors and integration/model identities, not from role prompts alone. Two prompts to the same model count as a role/revision experiment, not heterogeneous model cooperation.

A participant must be:
- declared in the exact immutable configuration revision;
- supported by a code-owned adapter and contract version;
- bound to the exact project/workspace/revision;
- separately covered by the provider approval record for its exact integration, origin, adapter, and supported invocation use. Legacy approvals without an integration_id remain valid only for the primary model participant; they must never be inherited by a secondary participant;
- admitted against current resource and provider budgets before invocation;
- available through an explicitly supported endpoint and compliant access method.

For this first slice, every model invocation is still an OpenAI-compatible `chat_completion` transport operation. Proposal, critique, and synthesis are task roles carried inside that operation; they are not new provider-approval use categories. The current approval vocabulary intentionally accepts only `chat_completion`. If a future adapter introduces a genuinely different provider operation, its approval-use vocabulary and validation must be extended explicitly before that operation can run.

If no compliant second model is available, Evo may implement and test orchestration with inert/fake adapters, but it must label live heterogeneous evaluation **blocked**, not passed. Paid cloud access is not a dependency. A free tier may be used only where its terms permit the intended use and data handling.

## 4. Experimental conditions

Run all conditions on the same frozen tasks and acceptance criteria. Randomize or counterbalance condition order where practical; preserve every run, including failures and incomplete outputs.

| Condition | Workflow | Question |
|---|---|---|
| A — Single baseline | Best designated single participant, one normal attempt | What does the baseline achieve? |
| B — Single with revision | Same participant gets a bounded independent review/revision opportunity | What does additional inference/revision compute achieve? |
| C — Independent cooperation | A proposal, B independent challenge, A synthesis | Does independent contribution plus synthesis help? |
| D — Challenge-focused cooperation | A proposal, B adversarial challenge, A synthesis and explicit disposition | Does structured challenge improve error detection or task success? |

Conditions C and D require distinct model participants. Conditions A and B should include the strongest eligible single-participant baseline, not an artificially weakened one.

### Budget matching and interpretation

No single scalar perfectly measures compute across different model architectures or local/cloud providers. Therefore:
- Define a pre-registered aggregate input-token ceiling, aggregate output-token ceiling, and wall-clock deadline for each scored run. Count every participant invocation, synthesis/revision pass, retry (currently prohibited), and coordination prompt against the same condition-level ceilings.
- Condition B must not receive a larger revision allowance than the combined proposal/challenge/synthesis allowance available to C or D. Where exact matching is impossible, record the mismatch and classify the comparison as observational; do not attribute an outcome difference to coordination.
- First compare within a fixed participant/runtime where possible, matching aggregate input/output token ceilings and task deadlines across B, C, and D.
- Record actual prompt/input tokens, output tokens, reported provider usage, wall time, time-to-first-token where available, retries, and per-invocation limits.
- For local inference, record GPU/VRAM and host RAM samples, runtime/model fingerprints, and elapsed time. Samples are approximate and may miss short peaks.
- For remote participants, record provider-reported usage and monetary charge when exposed; otherwise mark the value unknown rather than estimating it.
- Report quality-versus-cost and quality-versus-latency curves, not only one winner.
- Do not call cross-architecture token equality "equal compute." If a comparison cannot be matched credibly, label it resource-normalized/observational and avoid causal claims.

A collaboration result is especially compelling if it beats the single-participant revision condition at a comparable aggregate budget. If it only beats the one-shot baseline while consuming substantially more resources, the result demonstrates a benefit from spending more, not necessarily a coordination advantage.

## 5. Outcomes and metrics

### Primary outcome

**Task success rate** against predeclared acceptance criteria, supported by deterministic checks and blinded human adjudication where needed. A task with incomplete verification is not counted as a verified success.

### Secondary quality outcomes

- Test/build pass rate and regression count.
- Defects found before synthesis and defects remaining after synthesis.
- Acceptance-criteria coverage.
- Patch size and unnecessary change count.
- Human adjudication score using a fixed rubric.
- Unsupported claims, fabricated evidence, and unresolved disagreements.

### Resource and operational outcomes

- Aggregate and per-participant input/output tokens.
- Wall-clock duration and time-to-first-token.
- GPU/VRAM and host RAM observations for local work.
- Provider-reported cost/usage where available.
- Admission denials, budget exhaustion, timeouts, cancellations, retries, and incomplete runs.
- Coordination overhead: synthesis tokens/time and handoff volume.

Every metric must preserve its source and missingness. Unknown is not zero. A completed stream is not equivalent to a correct result.

## 6. Benchmark design and statistical discipline

Start with a small pilot to validate the workflow and identify instrumentation defects. Do not use pilot tasks to claim superiority if they are also used to tune prompts or orchestration policy.

For an evaluation set:
- Freeze task definitions, repository revisions, acceptance criteria, and test commands before scored runs.
- Include more than one task type and difficulty; avoid a benchmark consisting only of tasks that favor one participant.
- Use repeated runs where stochasticity matters. Record seeds when supported, while acknowledging that a requested seed does not prove backend determinism.
- Keep tuning/development tasks separate from held-out evaluation tasks.
- Blind human reviewers to condition where feasible.
- Report per-task outcomes, aggregate rates, uncertainty intervals, and all exclusions.
- Preserve failed, truncated, denied, cancelled, and incomplete runs. Never silently drop them from operational reporting.
- Do not claim statistical significance from a handful of pilot tasks. Choose sample size after pilot variance and practical effect size are observed.

A later, broader Phase 7 evaluation system may generalize this harness. Phase 4 should use the smallest reproducible protocol that can answer the first question.

## 7. Required Evo runtime capabilities

Phase 3 provides revision-pinned participant contracts and a bounded dispatch/admission boundary. The accepted runtime now supports a revision-pinned set of model participants alongside deterministic verifier components. This is participant binding infrastructure only; it does not provide a cooperative coordinator or authorize live provider dispatch.

The first implementation must add only what this vertical slice requires:

1. **Revision-pinned model participant set — implemented foundation.** Schema 2 assistant settings may declare up to eight additional model component keys through `additional_model_components`, in addition to the required primary `model_component`. Every reference must resolve to a typed model component in the same definition. Component references must be unique, and all declared participants must have distinct stable integration identities (adapter, normalized origin, model). Runtime binding derives participant IDs from the exact configuration/revision/component identity, creates a separate code-owned adapter binding for each model, and preserves secret-reference names only in provenance. No participant ID or integration ID is caller-authored. All declared model participants currently inherit the assistant runtime's shared generation controls (maximum output tokens, temperature, and context window); participant-specific overrides are deferred, so the configured context limit must be safe for every declared model.
2. **Generic per-participant invocation path.** Every model invocation must use the existing snapshot, authorization, provider approval, resource admission, budget reservation, atomic start, heartbeat, cancellation, and conservative settlement controls. No coordinator may call an adapter directly to bypass these controls.
3. **Selected-participant authorization, snapshot, and admission — implemented foundation.** The selected-participant implementation creates a trusted invocation runtime from the exact bound object, verifies its descriptor/adapter/bound-instance identity and full effective model configuration, and routes snapshots, envelope validation, approval, budgets, and local resource profiles through that selected runtime. The controller's authorization callback is code-owned and pinned to the adapter instance created by runtime construction; caller-supplied authorization is rejected. Non-primary participants require an exact integration-scoped provider approval; legacy unscoped approvals remain primary-only. Snapshots and provenance carry secret-reference names only, never resolved credential values. These checks remain within the existing atomic admission/lease lifecycle, with current workspace/revision revalidation and no alternate dispatch path. The first implementation foundation was independently validated at commit `68473de661f84fd1b2b683e9db8e791bb0a25cbd`; the schema/runtime multi-model binding extension is being added as a separate bounded slice.
4. **Typed, bounded handoffs — implemented foundation.** `evo_core.cooperative_handoffs` defines versioned proposal, critique, synthesis, and adjudication payload contracts; rejects unknown fields, duplicate item IDs, unsupported dispositions/severity/status values, malformed references, and oversized payloads; and records proposal/critique/synthesis handoffs in an immutable, hash-verified SQLite table. Persisted proposal/critique handoffs require a distinct target participant from the same pinned runtime; synthesis may be terminal with no model target. Records require a succeeded source invocation, an immutable normalized provider-output artifact captured by the dispatch boundary for the exact task role, a handoff payload that matches that output byte-for-byte after canonical validation, exact invocation snapshot/runtime revision agreement, bounded per-handoff token ceilings, and a future deadline no later than the source invocation deadline. These per-handoff ceilings are recorded constraints, not yet an aggregate experiment-wide token ledger. Context is represented by typed references, not copied raw repository content; trust labels are derived from source type and cannot be elevated by the caller. Common credential-like strings are rejected, but this is not a comprehensive secret scanner and must not be treated as one. Structured role invocations that complete successfully persist only their bounded, tool-free normalized output; ordinary assistant completions do not create these artifacts. Adjudication is validation-only in this slice; no adjudicator is executed. Handoffs are data, not instructions or authorization, and this module does not invoke participants or dispatch work. Adjudication payloads are validation-only; no adjudication is persisted or executed in this slice.
5. **Durable experiment/task record.** Persist experiment identity, frozen task/revision, condition, participant identities, invocation IDs, handoff references, budgets, verification evidence, adjudication, and terminal status. Preserve append-only lifecycle events or equivalent audit history.
6. **Sequential lifecycle and global lease.** The current provider admission implementation uses one global provider lease (`GLOBAL_PROVIDER_LEASE`), so provider invocations are serialized across integrations, not merely within an experiment. The first slice must remain strictly sequential and must not promise per-integration concurrency. Preserve the global lease and its conservative cancellation, timeout, restart, and unknown-settlement behavior. Per-integration leases or parallel provider execution are deferred until separately designed, tested, and accepted.
7. **Deterministic verification boundary.** Invoke only predeclared verification commands through the existing scoped command-policy boundary in the isolated checkout. The verifier's current JSON/evidence-shape checks do not prove code correctness and must not be described as doing so.
8. **Inspection.** Expose enough state to understand who ran, on which revision, under which budgets, what was handed off, what was verified, and what remains unknown. No broad Cyberdeck redesign is required.

The implementation must reuse existing contracts where they fit and explicitly version any new contract. It must not introduce a second, weaker dispatch path.

## 8. Safety, privacy, and operational boundaries

- Keep dispatch disabled by default globally and per workspace unless the operator explicitly enables it through existing controls.
- Do not run benchmark tasks against the user's live project or uncommitted working tree. Use a dedicated isolated benchmark project/checkout.
- Do not expose secrets to participants unless the task explicitly requires an approved secret and the policy permits it; the initial slice should require none.
- Keep provider credentials out of prompts, handoffs, logs, snapshots, and benchmark artifacts.
- Treat repository files, participant messages, tool output, and model-generated instructions as untrusted input.
- No participant can authorize another participant, grant permissions, change budgets, or alter the benchmark's acceptance criteria.
- Respect provider terms, data retention rules, rate limits, and data residency/handling requirements.
- No automatic retries after ambiguous provider settlement. No autonomous parallelism in the first slice.
- User approval is required before any task execution that modifies a checkout. The first implementation may generate proposals and isolated candidate changes, but must not merge or apply them to a user's working project.

## 9. Phase 4 acceptance gates

Phase 4 is not accepted merely because a multi-model demo runs. All of the following are required:

1. **Contract and security tests:** exact-revision binding; schema-level declaration of multiple model participants; distinct stable participant identities; duplicate/ambiguous identity rejection; selected-participant snapshot integrity and secret-reference-only provenance; code-owned authorization with no caller-supplied authorization path; per-integration approval/budget; non-primary stale/missing telemetry and missing-resource-profile fail-closed behavior; admission failure; cancellation; timeout; global-lease contention; lease loss; unknown settlement; and no direct adapter bypass.
2. **Isolation tests:** all task inputs, handoffs, outputs, artifacts, and verification commands remain within the benchmark project's authorized scope.
3. **Lifecycle tests:** interruption/restart cannot silently replay an invocation or claim completion; every terminal state and unknown state is inspectable.
4. **End-to-end test:** at least two distinct model participants complete the proposal/challenge/synthesis flow through Evo's own runtime, with deterministic verification evidence and a complete provenance record.
5. **Evaluation evidence:** all conditions A–D are run on the frozen pilot/evaluation tasks where eligible; missing conditions are explicitly reported.
6. **Independent review:** a separate reviewer inspects the exact target commit, tests, and evidence; GPT-6 reconciles findings and owns corrections.
7. **User acceptance:** the user explicitly accepts the phase after reviewing the evidence.

If a second compliant model is unavailable, gates 1–3 and inert end-to-end tests may be completed, but Phase 4's live cooperation/evaluation gate remains open.

## 10. Explicit non-goals

- Proving that more compute always improves model performance.
- Proving universal superiority of multi-agent systems.
- Training or fine-tuning foundation models.
- General-purpose autonomous multi-agent swarms or recursive delegation.
- Parallel model execution or speculative fan-out in the first slice.
- Automatic selection of providers based on unvalidated reliability scores.
- Autonomous changes to global policy, permissions, budgets, or evaluation criteria.
- Treating GPT-6/Kilo's human-mediated development workflow as an Evo runtime experiment.
- Replacing the accepted Phase 3 contracts or weakening their security boundaries.

## 11. Decision record

This document remains a technical proposal created after Phase 3 acceptance. The selected-participant foundation, schema/runtime participant-set binding, and typed handoff persistence are bounded implementation slices, not completion of the cooperative workflow. Neither this document nor those slices authorizes live provider calls, changes dispatch settings, starts a benchmark, or constitutes Phase 4 acceptance. Any implementation should be a separately reviewable bounded change, with tests and exact commit evidence.
