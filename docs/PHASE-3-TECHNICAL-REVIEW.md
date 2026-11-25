# Phase 3 Technical Review — GPT-6 Engineering Challenge

**Status (2026-11-25):** P3.1 and P3.3 accepted; P3.2 implementation complete and independently validated (843 tests), with formal phase acceptance pending; P3.4 implementation in progress. No live Registry-bound dispatch is enabled.
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

## Phase 2 dependency and acceptance

Phase 2 was formally accepted on 2026-11-24 at candidate revision `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31`; the authoritative evidence and exact acceptance scope are recorded in `ROADMAP.md`. The final independent detached-worktree regression check verified that exact SHA: compileall passed, all 824 tests passed with zero failures/errors/skips, and `git diff --check d11cb1de0b39d8a0367cb4d7098782da4354b006..HEAD` passed. The original checkout and 32 pre-existing worktrees were preserved.

The user approved a clarification to the Phase 2 resumption criterion: Phase 2 requires scope/history continuity through interruption and restart recovery, not automatic replay. Unfinished work is marked interrupted; automatic resumption/replay remains disabled because external side effects may have completed immediately before a crash. Continuing requires a new task with fresh scope validation. Durable pause/resume remains a later Phase 5 orchestration capability. This explicit limitation is not an outstanding Phase 2 blocker.

The review of CLI/API boundaries, instruction trust/precedence, adversarial checkout paths, command-policy intersection, task/plan scope, cancellation/recovery, and cross-project isolation is reconciled in the roadmap. Phase 2 is accepted; its acceptance does not enable Phase 3 live dispatch.

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

P3-R4 remains open and must be resolved before finalizing P3.5 admission. Phase 2 is accepted. P3.2 implementation and independent validation are complete; formal phase acceptance remains pending. P3.3 adapter work is underway within the documented sequence. P3.5 dispatch remains disabled until authorization, admission, and R4 are resolved.



## P3.2 runtime binding and invocation-snapshot validation

**Implementation disposition:** complete; independent validation PASS WITH FINDINGS at candidate 7c50ff666b7cd684cf21f373a82badc3dad5627c. Formal phase acceptance remains pending.

Validation evidence supplied from the exact detached candidate:
- python -m compileall -q src tests: exit 0.
- python -m unittest discover -s tests -v: 843 tests, 0 failures, 0 errors, 0 skips.
- Focused runtime, workspace-boundary, snapshot, and orchestration tests: 100 tests passed, including the assistant invocation-ID persistence regression.
- Original checkout remained local-demo-ready-v1 at a8ab59324caceab5b6fb2e5c674276c5ba96d072; status was unchanged and all 32 pre-existing worktrees were preserved.
- The sole finding was trailing whitespace at line 3 of the technical plan, introduced by the candidate's status update. It was removed in documentation-only commit 11b173d7d7405c80f1ec6c5acb9087b5e1382646, whose parent is the validated candidate. No application code or tests changed in that cleanup.

P3.2 source and API-boundary review found no remaining implementation blocker: workspace chat, plan proposal, plan execution, and coding-agent entrypoints record typed invocation snapshots; worker continuity verifies the exact pinned runtime and fails closed on revision drift; assistant turns retain the invocation ID on both messages. Snapshot attempts do not prove execution and do not authorize dispatch. No live provider dispatch is enabled.

The 843-test report applies to 7c50ff...; it is not a claim that tests were rerun after the documentation-only whitespace cleanup. The current P3.3 validation will rerun the full suite and diff check against the cumulative candidate.

## P3.3 OpenAI-compatible participant adapter — accepted

Candidate implementation checkpoint: 62af30df3678c730a15968ed41614ce1bef038bf (the validation target; later documentation-only commits may follow).

The adapter now constructs a Registry-bound OpenAI-compatible provider through PinnedProviderTransport, with no dispatch authorizer installed by runtime construction. The raw provider handle is kept inside the adapter rather than exposed on the bound participant, and the adapter's dispatch configuration is immutable after construction. Registry runtime construction no longer accepts an injectable provider factory, so the assistant remains backed by the non-network-capable disabled provider until P3.5. The adapter separates transport/model-list evidence from completion verification, requires an injected authorization callback for completion probes and invocation, binds invocation identity to workspace/project/configuration revision/component provenance, and constrains generation settings and request timeout to the pinned runtime. Provider responses and model-list entries are size-bounded and strictly parsed; HTTP header CRLF validation and provider-worker start ordering were corrected after the first independent validation found defects; regression coverage was added; provider errors are normalized to terminal participant outcomes; streamed content passes through the existing secret redactor. Cooperative cancellation suppresses late event forwarding and preserves provider outcomes completed before cancellation was observed, while the blocking HTTP request itself remains bounded by timeout rather than forcibly interrupted. The adapter protocol now declares transient resolved-secret/runtime-setting inputs and the cancellation signal.

P3.3 was subsequently accepted on 2026-11-25 at exact candidate 30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1. See the formal acceptance record below for independent validation evidence. No external provider calls or live Registry dispatch occurred. P3.5 remains the first milestone permitted to enable live dispatch.

## Phase 2 formal acceptance record

**ACCEPTED — 2026-11-24.** The user approved the clarification that Phase 2 resumption means preserving scope and history across interruption/restart, while automatic replay remains disabled and continuation requires a newly scope-validated task. Exact regression target: `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31`. Validation: 824/824 tests passed; compileall and diff-check clean. See `ROADMAP.md` for the full acceptance record. This does not authorize live Registry-bound provider dispatch.


## P3.3 OpenAI-compatible participant adapter — formal acceptance

**ACCEPTED — 2026-11-25.** Exact candidate: `30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1`; parent `9227983befe938b9bd605acd9f54400861869def`; cumulative validation base `6c12cf467cde61166be74e1e501e58de1c8decf6`.

Independent detached-worktree evidence: compileall passed; focused tests passed (148); full suite passed (863 tests, zero failures/errors/skips); cumulative diff-check passed with exit 0. The original checkout remained at `local-demo-ready-v1` / `a8ab59324caceab5b6fb2e5c674276c5ba96d072`, with identical status and 32 worktrees restored.

The validation specifically exercised actual CR/LF header injection, ordinary JSON content type, worker start-before-yield ordering, pre-cancelled no-dispatch behavior, cancellation suppression of late events, bounded request timeout, and complete provenance fixtures. Security checks found Registry transport pinning and origin/DNS/TLS/redirect/proxy restrictions intact; bounded response handling and strict parsing intact; no secret leakage; no provider factory injection; no runtime-construction network request; and no API/worker route to live dispatch. No external provider calls were made.

The first corrective validation had exposed two implementation defects and incomplete test fixtures; these were corrected. A subsequent test-literal defect and trailing whitespace were also corrected. The exact final candidate passed all validation with no findings.

This acceptance is only for P3.3. P3.2 formal acceptance remains a separate disposition. P3-R4 remains open. P3.5 dispatch remains disabled; no merge into `local-demo-ready-v1` is authorized.


## P3.4 deterministic verifier — formal acceptance

**ACCEPTED — 2026-11-25.** Exact candidate: `ad04198b95708df58aae1ff07e0b38380671b574`; P3.4 base `30cc9e8cc68cfb0f519c8e5515d33fe935df6ff1`; cumulative validation base `6c12cf467cde61166be74e1e501e58de1c8decf6`.

Independent detached-worktree validation of the exact SHA: compileall exit 0; 14 deterministic-verifier tests passed; 21 participant-contract/runtime-binding tests passed; full unittest suite 877/877 passed with zero failures, errors, or skips; diff-check against both P3.4 and cumulative bases exited 0. The final correction was explicitly checked: `probe_completion()` returns `model_advertised=None` while retaining `transport_reachable=True` and `completion_verified=True` for the local deterministic self-test.

Review confirmed that the verifier is a distinct local-only deterministic participant, bounded to 1 MiB input/output and at most 128 valid evidence references. It validates structure and reference shape only; it does not resolve references, establish artifact existence, prove factual claims, execute shell/arbitrary tools, access the network, or consume secrets. Runtime binding is exact-revision-specific and optional for configurations without a verifier. The production runtime installs no invocation authorizer; invocation fails closed without authorization. No API/worker route can invoke either participant before P3.5. No tests were weakened or removed.

The original checkout remained `local-demo-ready-v1` at `a8ab59324caceab5b6fb2e5c674276c5ba96d072` with identical status, and all 32 pre-existing worktrees were preserved. No live provider calls or dispatch occurred.

Acceptance is limited to P3.4. P3.2 formal acceptance remains pending; P3-R4 remains open and must be resolved before finalizing P3.5 admission; P3.5 remains the first milestone permitted to enable live dispatch. No merge into `local-demo-ready-v1` is authorized.


## P3-R4 resource-admission contract — proposed for independent challenge

**Independent challenge: PASS WITH FINDINGS.** The architecture is accepted in principle, with the high/medium findings incorporated into the contract. The timestamp correction is implemented in the candidate telemetry sampler and requires local regression validation before P3-R4 is formally closed. No P3.5 admission or dispatch is implemented. The current `assess_workload()` and workload scheduler are advisory and use generic GPU assumptions, so neither can be reused unchanged as the participant dispatch gate.

The revised design in Section 6.1 of `docs/PHASE-3-TECHNICAL-PLAN.md` makes locality code-derived: loopback OpenAI-compatible endpoints are local to this host; non-loopback endpoints (including LAN addresses) are remote for this host's inference-resource accounting. Remote calls require host CPU/RAM for Evo's bounded client work and provider-side quota/compliance gates, but never local GPU telemetry. CPU-only local endpoints likewise do not require NVIDIA metrics. GPU/mixed local endpoints require fresh VRAM and temperature telemetry. The deterministic verifier has a small code-owned CPU/RAM declaration.

For local model endpoints, the proposal requires an operator-owned resource profile selected by reference, with explicit CPU/GPU/mixed mode and bounded CPU/RAM/VRAM estimates. Missing profiles/estimates remain unknown and fail closed; no model-name heuristics or invented memory estimates. The profile distinguishes persistent/preloaded incremental demand from cold-load peak demand, and persistent residency is explicitly an operator assertion. Common defaults preserve existing 2 GiB RAM and 1 GiB VRAM reserves, 90% RAM pressure and 85°C GPU ceiling, and add a 1-core CPU reserve. A 10-second freshness window applies to the completion timestamp; the sampler now records completion time and monotonic collection duration. CPU utilization at or above 90% is an additional defer signal when available; first-sample absence skips only this secondary check. Interactive priority does not bypass reserves. Telemetry remains a best-effort snapshot and cannot lock resources against unrelated desktop processes. The plan now documents fixed-reserve scaling limitations, load-average I/O-wait behavior, operator residency-attestation risk, NVIDIA-only telemetry support, configurable thermal/pressure thresholds, `os.cpu_count()` unknown behavior, and the separate advisory scheduler semantics.

**Review questions for independent challenge:**
1. Is static loopback the correct and sufficiently conservative definition of same-host inference? Are LAN endpoints correctly treated as remote for this host?
2. Are the participant-specific dimensions and fixed remote/verifier estimates defensible, bounded, and clearly separated from provider-side budgets?
3. Does the operator-owned local model profile adequately handle CPU/GPU/mixed modes and cold-load versus persistent incremental memory without pretending residency is proven?
4. Are 10-second sample freshness, CPU headroom from logical cores minus 1-minute load average, and the proposed reserves/pressure limits appropriate? Identify telemetry limitations or safer alternatives.
5. Does the decision logic fail closed on missing/stale required dimensions without blocking remote or CPU-only workloads on irrelevant NVIDIA telemetry?
6. Are interactive reserve semantics correct for the local-first desktop goal, and is the race with unrelated processes honestly bounded?
7. Is the boundary with the existing advisory workload scheduler and P3.5's durable single-flight lease clear and safe?
8. What changes are needed to schema/adapter versioning so old schema-2 local endpoints remain readable but cannot dispatch without a resource profile?

Do not edit files, implement code, change branches/worktrees, enable dispatch, or call providers. Return concrete findings with severity, exact source/doc references, recommended corrections, and PASS / PASS WITH FINDINGS / FAIL for the design.


### P3-R4 independent challenge disposition

**Validator verdict: PASS WITH FINDINGS.** GPT-6 reviewed all 22 findings and incorporated the high/medium corrections and documented the acceptable limitations.

| Finding | Disposition |
|---|---|
| 1. Timestamp precedes collection | Corrected in `monitor.py`: completion timestamp after all probes; monotonic collection duration included. Regression tests added; local execution still required. |
| 2. CPU utilization omitted from decision matrix | Corrected: available utilization >=90% defers; first-sample absence skips only this secondary signal. |
| 3. Fixed reserves scale unevenly | Accepted limitation; explicitly documented as conservative starting defaults, operator-configurable. |
| 4. Load average includes I/O wait | Accepted limitation; documented, with utilization pressure signal as a complementary check. |
| 5. Fixed GPU thermal threshold | Accepted limitation; configurable, not claimed universal. |
| 6. Persistent residency is unverifiable | Explicit OOM consequence warning added; cold-load profile required when uncertain. |
| 7. NVIDIA-only GPU telemetry | Explicitly documented; unsupported GPU/mixed workloads fail closed. |
| 8. Missing no-verifier automated test | Remains a coverage improvement; not a P3-R4 admission blocker. |
| 9. `os.cpu_count()` may be None | Explicitly documented as unknown/fail closed. |
| 10. Profile adapter version unspecified | Clarified: local profile requires adapter contract v2 and `resource_profile_id`; v1 local definitions remain readable but non-dispatchable; remote v1 remains valid. |
| 11. Advisory scheduler interactive bypass differs | Explicitly documented as separate behavior; P3-R4 does not retroactively alter it. |
| 12. Timestamp format | Corrected to UTC `Z` suffix in the sampler. |
| 13–22. Locality, fixed estimates, attestation, fail-closed matrix, interactive priority, external races, lease boundary, compatibility, security, and operational constraints | Accepted as designed/documented limitations. |

The accepted decision matrix is: all participants require fresh completion-timestamped RAM and CPU/load telemetry; optional CPU utilization >=90% defers when available; NVIDIA telemetry is required only for local GPU/mixed participants; all required missing/stale/invalid dimensions produce unknown/deny; known reserve/pressure violations defer; interactive priority only changes ordering. Remote services and CPU-only local endpoints must not depend on NVIDIA telemetry.

**Remaining gate:** run the focused telemetry tests and full suite against the exact candidate commit containing the sampler correction. Until that evidence is returned, P3-R4 remains conditionally resolved at the design level, not formally accepted as an implemented freshness prerequisite. This does not authorize P3.5 implementation or live dispatch.
