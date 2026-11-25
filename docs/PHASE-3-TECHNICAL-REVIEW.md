# Phase 3 Technical Review — GPT-6 Engineering Challenge

**Status:** Independent contract challenge completed; P3.1 implementation authorized by the user on 2026-11-24. This does not authorize P3.2 or live dispatch.
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
2. **P3-R1 — accepted at the contract-design level after independent challenge.** Section 4 requires connection-time IP pinning while preserving original-host `Host`, TLS SNI, and certificate verification; rejects mixed permitted/prohibited DNS answer sets; revalidates every retry; disables implicit proxy discovery, unsafe pooling, and unvalidated alternate-address fallback; and requires fresh resolution for every new connection. IPv4-mapped IPv6 and zone identifiers are explicitly normalized/rejected. Redirects remain disabled by default. Acceptance tests must observe the actual peer address and exercise these transport traps.
3. **P3-R2 — accepted at the contract-design level after independent challenge.** Section 8 separates transport reachability, model advertisement, and completion verification. Dispatch requires an explicit operator-initiated bounded completion probe for the exact model/interface. The probe passes endpoint, compliance, provider-budget, and single-flight admission but expressly does not require prior availability. It charges a conservative minimum probe cost; malformed/empty 2xx completion data fails verification; evidence expires after the initial 60-second window and is invalidated by endpoint, model, adapter/interface, transport/security, compliance, and allowlist changes. No implicit first-request fallback is permitted.
4. **P3-R3 — accepted at the contract-design level after independent challenge.** Section 9 defines durable lease states and transactional transitions, rejects TTL-only recovery, keeps `recovery_pending` blocking, and distinguishes evidence-confirmed idleness from operator-acknowledged uncertain recovery. Uncertain acknowledgement is restricted to a privileged local-operator path outside the participant API, with an explicit duplicate-work warning and auditable reason/authority/evidence. The two terminal outcomes remain distinct in history and diagnostics. Provider-side idleness is explicitly unprovable automatically where no reliable status mechanism exists.
5. **P3-R4 — remains open and is not a blocker to approval of the P3.1 contract.** Resolve adapter-specific local versus remote resource requirements, required telemetry dimensions, freshness, and operator reserves before finalizing P3.5 admission details.
6. The user explicitly authorized P3.1 implementation on 2026-11-24. This authorization is limited to P3.1; it does not authorize P3.2 runtime routing or live Registry-bound dispatch.
7. **Independent challenge completed and contract approved.** The challenge found the revised R1–R3 designs sound with the implementation traps and clarifications incorporated into Sections 4, 8, 9, and the required acceptance tests. P3.1 implementation is authorized; R4 remains open for P3.5 admission design.

No application code, database schema, API behavior, provider calls, or services were changed as part of this review.

## P3.1 implementation acceptance

**Disposition: ACCEPTED on 2026-11-24/25.** The P3.1 contract and security foundations are implemented on `agent-plan-verification-hardening-v1`, current checkpoint `0b3f283879900c7bb73f40a2aceb7199fd4d4dde`.

Acceptance evidence:
- Independent local verification at `d3e0e320883de8f7f2769b19d9edac742f29d66e`: `python -m compileall -q src tests` passed; the full unittest suite passed (810 tests, zero failures/errors/skips).
- Independent source review found no concrete code defects. The only finding was trailing whitespace in this document's companion P3.1 proposal.
- The whitespace-only documentation correction is present in the current checkpoint. Independent detached-worktree `git diff --check fc656fcad9d964b3ca5dc4033745c861d30f4ae0..HEAD` passed with exit 0 and no findings.
- The candidate branch currently points to the exact checkpoint above. The user's original checkout remains on `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072`; the verification report confirms its status and all 32 pre-existing worktrees were preserved.

Acceptance is deliberately limited to P3.1's executable configuration contract, participant contracts, configuration validation, provider endpoint/secret/approval foundations, and associated tests/documentation. It does **not** mean live Registry-bound dispatch exists or is enabled. The pinned transport is not wired into the legacy TOML provider path; a later Registry adapter must consume the secured transport. No P3.2 runtime factory/routing, P3.5 admission/lease service, provider invocation, or merge into `local-demo-ready-v1` is authorized by this acceptance.

P3-R4 remains open and must be resolved before finalizing P3.5 admission. The Phase 2 acceptance gate also remains open. Proceeding to P3.2 requires separate explicit user authorization.

