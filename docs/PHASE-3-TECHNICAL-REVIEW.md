# Phase 3 Technical Review — GPT-6 Engineering Challenge

**Status:** Planning review only. This document does not authorize application-code changes.
**Reviewed:** `docs/PHASE-3-TECHNICAL-PLAN.md`, `docs/PHASE-3.1-CONTRACT-PROPOSAL.md`, and the current Phase 2/3 statements in `ROADMAP.md`.
**Review standard:** Challenge correctness, operability, security, and testability before implementation. The roadmap remains the authority for sequence and acceptance.

## Overall assessment

The Phase 3 direction is coherent and appropriately narrow: immutable Registry configuration must determine the complete workspace-bound assistant runtime; legacy TOML behavior remains separate for non-Registry callers; fake adapters precede live dispatch; and authorization/admission precede any live invocation.

The plans are not yet implementation-ready for P3.1 acceptance. The following issues need explicit resolution in the canonical proposal before implementation authorization.

## Blocking findings

### P3-R1 — Provider destination validation must bind validation to the actual connection

**Severity: High — security boundary**

The proposal requires validating DNS-resolved destinations and revalidating redirects. A preflight DNS lookup followed by an ordinary HTTP client connection can still create a time-of-check/time-of-use gap: the client may resolve the hostname again and connect to a different address after validation.

**Required resolution:**
- Specify how the adapter guarantees that the address actually connected to is one of the validated addresses.
- Prefer connection-time address pinning to a vetted IP while preserving the original hostname for TLS certificate validation and SNI; alternatively use a transport with an equivalent enforceable guarantee.
- Apply the same rule to every redirect hop and connection retry.
- Define behavior for multiple A/AAAA answers, mixed permitted/prohibited answers, DNS changes, proxies, and environment-configured proxy variables. The safest initial policy is to reject ambiguous or mixed destination sets and disable implicit proxy routing unless explicitly operator-configured and separately reviewed.
- Tests must observe the actual peer address used by the transport, not merely mock the preliminary resolver.

A check that only validates a DNS answer before the HTTP library independently connects does not close SSRF/rebinding risk.

### P3-R2 — Availability preflight is underspecified for OpenAI-compatible endpoints

**Severity: High — operational blocker**

The proposal correctly distinguishes endpoint reachability from model availability and says unknown availability denies dispatch. It also acknowledges that some compatible endpoints do not expose model listing. However, it does not define a universal or adapter-specific preflight contract that can establish the configured model is usable without silently performing an unbudgeted real invocation.

**Required resolution:**
- Define a versioned adapter preflight operation and its exact evidence semantics.
- Distinguish transport reachable, model identifier advertised, and model completion capability verified. A model-list response does not prove a completion will succeed.
- For endpoints without a supported non-generative probe, keep availability unknown and require an explicit, auditable operator action or a separately admitted probe invocation with a strict deadline and budget. Do not quietly treat the first user request as a health check.
- State which state is sufficient for dispatch and how long that observation remains fresh.
- Test endpoints with model listing, without model listing, unreachable endpoints, and endpoints advertising a model that rejects completion.

Do not make a non-standard assumption that every OpenAI-compatible endpoint implements `/models`.

### P3-R3 — Abandoned single-flight lease recovery needs an executable operator procedure

**Severity: High — availability and duplicate-execution risk**

The plan intentionally refuses to release a lease solely because a TTL elapsed, since provider-side work may continue after the client process disappears. That is conservative and correct. But “endpoint idleness is established or the operator explicitly acknowledges recovery” is not yet an operational contract.

**Required resolution:**
- Define durable lease states, including at least active, abandoned, recovery-pending, recovered-by-evidence, and operator-acknowledged-uncertain.
- Specify the evidence that can establish idleness for local inference and remote providers. If the provider offers no reliable request-status/cancellation API, state that idleness cannot be proven automatically.
- Define the operator recovery action, its confirmation text, required reason, recorded authority source, timestamp, previous owner/invocation, and evidence. It must make clear that acknowledging recovery may permit duplicate provider-side work or overlapping compute.
- Ensure recovery is an explicit privileged local-operator action, never an automatic TTL cleanup or participant-controlled operation.
- Test process crash at each lease lifecycle boundary, restart recovery, stale heartbeat, duplicate acquisition, and operator acknowledgement. The lease must remain blocking until a valid recovery transition occurs.

Do not claim that releasing Evo's local lease cancels or terminates provider-side work.

## Important clarification

### P3-R4 — Resource admission must distinguish local and remote participant requirements

**Severity: Medium — correctness and usability**

The plan requires protecting interactive reserves and failing closed when required capacity is unknown. It does not yet define the resource dimensions required by each adapter or distinguish resources consumed by a local inference endpoint from resources consumed by a remote provider.

**Required resolution:**
- Have each code-controlled adapter declare bounded resource requirements and whether inference is local, remote, or otherwise externally hosted.
- Define which telemetry dimensions are required for each invocation. A remote API call should not be denied because local GPU VRAM is unknown if that invocation does not consume local inference capacity; local tool execution or a local model should have the relevant CPU/RAM/VRAM requirements.
- Define operator-owned reserve thresholds and telemetry freshness per required dimension.
- Unknown required capacity must still fail closed; irrelevant capacity must not become a false prerequisite.
- Tests must show both local and remote admission decisions, stale telemetry, missing dimensions, and protected interactive reserves.

This preserves the fail-closed principle without turning unrelated telemetry into an accidental global outage.

## Phase 2 dependency

The Phase 3 plan correctly says Phase 2 must not be treated as complete merely because the isolation foundations exist. Keep the Phase 2 acceptance gate open until CLI/API equivalence, instruction trust/precedence, adversarial checkout paths, and task/plan scope continuity through approval, execution, cancellation, restart recovery, and resumption have evidence.

The current test files provide meaningful coverage for scope persistence, retrieval isolation, project instructions, API scope checks, and workspace execution. Their existence alone does not establish that the full Phase 2 gate has passed; local test execution and remaining cross-path review are still required.

## Decisions and disposition

1. Retain the core Phase 3 architecture: exact pinned revision, complete assistant-runtime binding across all workspace entrypoints, no global fallback for Registry-bound workspaces, inert adapters before live dispatch, and explicit authorization/admission.
2. Resolve P3-R1 through P3-R3 before declaring P3.1 contract review complete.
3. Resolve P3-R4 before finalizing P3.5 admission implementation details.
4. Keep all code changes and service/runtime activation behind the existing explicit authorization boundary.
5. After these edits, obtain an independent challenge and reconcile it against this review before authorizing P3.1 implementation.

No application code, database schema, API behavior, provider calls, or services were changed as part of this review.
