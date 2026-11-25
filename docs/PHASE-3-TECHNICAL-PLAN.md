# Phase 3 Technical Plan — Participant Contracts and Runtime Integration

**Status: P3.1 accepted; P3.2 implementation complete and independently validated (843 tests), with explicit phase acceptance pending. P3.3 OpenAI-compatible participant adapter implementation is in progress.** The current P3.3 candidate binds the Registry runtime to the pinned transport and keeps completion probes/invocation disabled without a code-supplied authorization gate. P3.5 live dispatch remains gated.
**Authority:** `ROADMAP.md` remains the sole authority for phase order and acceptance. This document decomposes Phase 3 into an implementation-ready sequence. It does not authorize implementation beyond the planning/documentation work explicitly requested.

## 1. Objective

Make Evo's versioned AI Configurations executable through explicit, replaceable runtime adapters and a common participant contract.

At the end of Phase 3, Evo should be able to:

1. Resolve an exact immutable configuration revision associated with an authorized workspace.
2. Resolve each executable component to a known, versioned adapter without silently substituting another component or model.
3. Represent the resulting participants using common identity, capability, availability, compliance, and provenance contracts.
4. Construct a bounded, task-scoped invocation with explicit input/output contracts, context references, permissions, deadlines, and budgets.
5. Authorize and admit that invocation before dispatch, including conservative local resource checks and provider-specific limits.
6. Invoke the participant through its adapter and retain enough provenance to explain exactly what ran and under which configuration, adapter, policy, and resource decision.

This is the foundation for Phase 4. It is not yet a general multi-agent orchestrator, autonomous task engine, or full distributed scheduler.

## 2. Source-backed current-state assessment

The following observations are from the current implementation on `agent-lifecycle-reconciliation-v1`.

| Area | Existing implementation | Phase 3 gap |
|---|---|---|
| AI Configurations | `src/evo_core/ai_configurations.py` stores validated JSON definitions and immutable revisions. The top-level shape is `schema_version`, `components`, and optional `extensions`. Validation is deliberately generic: component names and object payloads are checked, but component-specific schemas are not enforced. Existing tests use illustrative `model` and `agents` objects. | Component payloads are not resolved to installed adapters or executable participant instances. P3.1 must define typed component schemas and a compatibility/migration strategy without assuming existing opaque definitions already satisfy them. |
| Registry/workspaces | `src/evo_core/platform_registry.py` and `src/evo_core/workspaces.py` persist configurations, immutable revisions, projects, checkouts, and workspace relationships. `resolve_executable_workspace` checks active relationships and the registered checkout path, and returns the exact configuration revision. | Workspace resolution validates and returns the binding; it does not produce a runtime composition. The existing boundary is a foundation to call, not a replacement for dispatch authorization. |
| Provider/config loading | `src/evo_core/provider.py` implements `OpenAICompatibleProvider` with model listing and streamed chat completions. `src/evo_core/config.py` loads the active assistant provider profile from TOML and environment-backed credentials. | The TOML-selected application provider and Registry AI Configuration are separate paths. Phase 3 must introduce Registry-driven binding without casually replacing or breaking the legacy CLI/chat path. |
| Assistant | `src/evo_core/assistant.py` constructs or accepts one provider and uses it for chat/context generation. | No configuration-revision-driven provider construction or general participant dispatch. |
| Actual workspace execution | The API resolves the registered workspace and exact configuration revision; it uses that revision for effective project command-prefix policy. However, `run_agent` constructs `CodingAgent(assistant, ...)`, and that assistant's provider was created from the global TOML-selected `EvoConfig`. The workspace's model/provider component is not currently used to construct the execution provider. | This is the central Phase 3 integration gap: a workspace can name an immutable AI Configuration revision without the runtime actually executing that configuration. Phase 3 must bind the exact workspace revision into the provider/participant runtime, while retaining the legacy default path for callers that do not use Registry-bound workspaces. |
| Workspace-scoped chat and plan proposals | Workspace-scoped chat turns call the global `assistant.turn`; agent-plan proposals call `orchestration.propose_with_model(assistant.provider, ...)` with global TOML generation settings. | Binding only `run_agent` would leave two other workspace-bound entrypoints executing the global provider. Phase 3 must route workspace chat, plan proposal, and coding-agent execution through the same pinned-revision runtime factory. Project-only/global callers without a registered workspace may retain the legacy path. |
| Coding agent | `src/evo_core/coding_agent.py` is a tool-using loop over the assistant's same provider, with workspace controls and per-action approval. | It is a distinct runtime behavior, but not an independent model/provider implementation. It must not be counted as a second independent model participant merely because it wraps the same provider. A coding-agent adapter is useful only if it creates a genuinely distinct runtime contract without recursive dispatch or bypassing current approvals. |
| Resource intelligence | `evo_experiments.intelligence.assess_workload` and hardware APIs provide advisory admission based on telemetry and estimates; the hardware scheduler records reservations for separately managed workloads. | The admission endpoint is advisory and does not reserve capacity; the existing scheduler is not a participant scheduler. Neither is a mandatory atomic gate in participant dispatch. Provider quotas and per-invocation token/rate budgets are not integrated. |
| Scheduler | Existing workload queue/reservations and managed execution cover bounded external/command workloads. | This is not a participant scheduler and must not be repurposed as one without an explicit design. |
| Compliance | Provider access uses configured endpoints and credential references/environment variables. | No structured, versioned integration compliance status that can gate use. |
| Persistence | Agent runs, tool events, plans, and experiment records already preserve useful execution history. | No common participant invocation record capturing the exact participant, adapter, configuration revision, effective policy, admission decision, and outcome. |

Important distinction: the current assistant provider profile and Registry AI Configurations are two separate configuration paths. Phase 3 must make the Registry configuration executable without accidentally breaking the existing CLI/chat path. Migration or replacement of the legacy path is not a prerequisite unless implementation proves it necessary.

**Phase 2 dependency status:** Phase 2 was formally accepted on 2026-11-24 at candidate revision `b0d21835ead18825cd0ebb6fe7a95d32d4df5c31`; see `ROADMAP.md` for the full evidence and scope. Its restart semantics are intentionally interruption-only: unfinished tasks retain scope/history and become interrupted; automatic replay/resumption remains disabled, and continuation requires a new task with fresh scope validation. Durable pause/resume is deferred to Phase 5. Phase 3 must continue to call the existing workspace resolver and preserve all accepted isolation boundaries. Phase 2 acceptance does not authorize live dispatch.

**Participant-count caveat:** two configuration instances that point to the same endpoint/model are not two independent participants for cooperation testing. Likewise, the current CodingAgent wraps the assistant's provider; it is not an independent model implementation. Phase 3 must demonstrate two genuinely distinct participant implementations or runtime kinds through the common contract, and Phase 4 must identify exactly which independent participants are contributing. A fake test adapter does not satisfy production acceptance. A second adapter may be a distinct non-model runtime (for example, a deterministic verifier) if it has a real bounded contract and useful contribution. If the chosen Phase 4 cooperation pattern requires two independent model judgments, that requires two independently addressable model participants and must be tested as such.


### Source-review findings that shape P3.1

The deeper source review adds several concrete constraints to the design:

1. **The configuration schema is currently intentionally opaque.** `validate_definition` enforces the top-level version, JSON compatibility, object-shaped components, sensitive-key rejection, and syntactic secret-reference fields. It does not validate component-specific fields, adapter IDs, model settings, or supported capability versions. The tests' `model` and `agents` objects are examples, not a production executable schema. P3.1 must introduce explicit component schemas and decide whether schema version 1 is extended compatibly or a new schema version is required. Do not treat generic JSON acceptance as runtime validity.
2. **Workspace binding is not runtime binding.** `resolve_executable_workspace` returns the exact immutable configuration revision, and current agent execution uses its command-policy portion. The model/provider execution path still comes from the global TOML-loaded `EvoConfig`. This mismatch is the primary defect Phase 3 must correct: the exact workspace-bound configuration must determine the participant runtime actually invoked.
3. **Secret references are only syntactically checked today.** The Registry validator rejects raw sensitive keys and validates non-empty `secret_ref` / `secret_refs` strings, but no Registry secret resolver is evidenced in this path. The existing TOML provider loader supports environment-variable-backed API keys. P3.1 must specify the initial supported resolver explicitly; it must not imply that arbitrary secret reference strings are already resolvable.
4. **The existing hardware admission endpoint cannot serve as the dispatch gate unchanged.** It returns advisory allow/defer/unknown decisions and does not reserve capacity. The workload scheduler reserves its own queue entries but is not integrated with participant invocations. A dispatch implementation must prevent two concurrent requests from both spending the same observed headroom, through a narrowly scoped atomic reservation/serialization mechanism or a deliberately single-flight initial policy.
5. **Cancellation is currently cooperative and bounded by provider behavior.** The OpenAI-compatible streaming transport has a request timeout but no explicit cancellation token in its `chat` method. The coding agent checks cancellation at its own safe boundaries. The adapter contract should define cancellation observation and terminal status honestly; Phase 3 must not promise immediate interruption of a blocking provider request unless the transport is changed and tested.
6. **Workspace revisions are explicitly pinned, not floating.** Existing workspace tests accept an older revision and verify that the pinned revision remains unchanged after a newer configuration revision is created. Runtime binding must preserve that behavior. "Stale" means missing/mismatched revision or inactive relationship, not merely a revision that is no longer current.
7. **The local API is not a multi-user identity system.** The current middleware checks loopback hostnames and CORS origins but does not authenticate an individual user. Phase 3 must preserve the local single-user assumption and must not describe it as authenticated user identity or expose it remotely.
8. **Workspace-bound assistant behavior is broader than provider selection.** `EvoAssistant` reads system/persona prompt, temperature, output token limit, context window, memory limit, history count, and history character budget from `EvoConfig`. These must be supplied by the workspace-bound assistant-runtime component (with code-owned safety policy kept separate), not silently inherited from global TOML.

These findings do not change the phase order. They make the configuration-to-runtime gap, assistant-runtime composition, secret-resolution gap, and non-atomic admission gap explicit so the first implementation slice addresses real boundaries rather than building a parallel abstraction beside them.

## 3. Architectural decisions

### 3.1 Keep the platform contracts provider-neutral

Evo owns the contracts. Provider-specific request formats, authentication, streaming quirks, and error translation stay inside adapters.

A participant is an invokable or explicitly human-mediated source of work. The participant contract should not assume that every participant is a language model or exposes chat completions.

Minimum participant descriptor:

- Stable `participant_id` and participant type.
- Human-readable name and implementation/version identity.
- Adapter identifier and adapter version.
- Declared capabilities and supported input/output contract versions.
- Execution location (local process, local endpoint, remote service, or human-mediated).
- Availability state and last-observed time, separate from authorization.
- Resource requirements/limits and supported budget dimensions.
- Compliance integration reference and current review status.
- Provenance: configuration ID/revision and component identity that produced the instance.

Capability declarations describe supported interfaces; they do not prove quality or reliability. Trust/reliability evidence is not a permission.

### 3.2 Separate definition, binding, instance, and invocation

Use four distinct concepts:

1. **Configuration definition:** immutable user-authored description of the desired AI system.
2. **Runtime binding:** resolution of a configuration component to a supported adapter and its validated, non-secret settings.
3. **Participant instance:** the concrete runtime target produced by that binding, with identity, capabilities, availability, limits, and provenance.
4. **Invocation:** one authorized attempt to use a participant for a bounded task or assignment.

Do not store live credentials in configuration definitions, participant descriptions, context envelopes, logs, or collaboration messages. Resolve approved secret references at the adapter boundary.

A binding must fail clearly when a component type is unknown, an adapter is unavailable, a required setting/secret is missing, a referenced model is unavailable, or a contract version is unsupported. No silent fallback to the application default provider, another model, a different policy, or a newer configuration revision. A workspace's pinned immutable revision remains valid when the configuration's current revision advances; it is invalid only when the pinned revision is missing/mismatched or its workspace/project/configuration relationship is no longer active.

### 3.3 Use typed capabilities, not arbitrary executable configuration

Configuration components should declare a component type and version and reference an adapter-supported schema. The adapter registry is code-controlled; configuration data cannot import Python modules, name arbitrary classes, or execute arbitrary code.

For the initial contract, capability declarations should be finite and inspectable, for example:

- text generation / structured response;
- tool-call generation (not tool execution authority);
- code-agent task execution through the existing approval boundary;
- deterministic validation or other explicitly registered tool capabilities.

A participant may declare multiple capabilities. Assignment role is task-scoped and selected separately; it is not permanently attached to participant identity.

### 3.4 Keep authorization outside capability and trust

Before every invocation, resolve effective authority from the current task, participant, project/workspace, and policy. A participant's capabilities, availability, historical success, or configuration membership must never grant execution permission.

Child assignments can only narrow parent permissions and remaining budgets. Project command policy continues to be intersected with global command policy. The existing workspace execution boundary remains authoritative for filesystem and command operations.

### 3.5 Explicit availability and compliance

Use explicit states rather than booleans that collapse distinct conditions:

- availability: available, unavailable, unknown, disabled;
- authorization: authorized or denied for this invocation, with reason;
- compliance: approved, restricted, suspended, unknown, with review provenance.

An endpoint responding to a health check does not prove compliance. A registered integration with unknown or stale compliance status must not be used for a dispatch requiring that approval. Compliance review is per integration/interface/use, not inferred from provider brand alone.

## 4. Proposed contract boundaries

The exact Python names and persistence representation should be selected during implementation design, but the following boundaries are required.

### A. Adapter contract

An adapter should expose:

- a stable adapter ID and adapter contract version;
- a validation/binding operation for a typed component definition;
- capability and resource-limit description;
- an availability/health probe with bounded timeout;
- an invocation method accepting a validated request envelope;
- normalized streaming events and a normalized terminal result;
- normalized errors that distinguish unavailable, denied, rate-limited, timed-out, malformed, cancelled, and provider-failed outcomes.

Adapters must not decide task permissions, project scope, or user approval. They execute only after the platform dispatch boundary authorizes the invocation.

### B. Participant contract

A participant instance should be immutable for the lifetime of an invocation and reference the exact adapter and configuration revision from which it was built. Refreshing endpoint availability may update a separate observation; it must not silently mutate the participant's identity or configuration.

### C. Invocation envelope

Every invocation should carry:

- invocation ID and parent task/assignment reference;
- participant ID and exact configuration ID/revision;
- objective and task-scoped role;
- project/workspace scope and authorized execution context;
- bounded input and referenced context with provenance/trust labels;
- required output contract and acceptance criteria;
- effective permissions and approval requirements;
- deadline, cancellation signal, and retry policy;
- remaining resource/provider budgets;
- correlation/provenance metadata.

The participant's output is untrusted data until checked against its output schema and the relevant acceptance criteria. Participant output must not be interpreted as privileged instructions.

### D. Result and event contract

Persist normalized lifecycle events and terminal results with author, participant, adapter, configuration revision, timestamps, status, bounded error details, usage/cost metrics when available, and evidence references. Preserve partial output as partial evidence; never report a timeout, malformed result, cancellation, or provider error as success.

Do not duplicate the existing detailed coding-agent tool-event store. The common invocation record should reference existing run IDs and event records where possible.

## 5. Initial adapter scope

Implement only the smallest useful set needed to prove the contracts.

**Initial supported production adapter:**
- OpenAI-compatible chat-completions endpoint, reusing and hardening the existing `OpenAICompatibleProvider` transport where practical.
- Support text generation first; tool-call output can be represented as a capability, but tool execution remains behind existing Evo-owned approval and command boundaries.

**Second production participant boundary:**
- Prefer a bounded deterministic verifier/tool participant as the second production runtime kind. It must perform a real, useful verification function under the common contract; it is not a model and must be identified honestly as such.
- The existing CodingAgent may be exposed as a distinct tool-using runtime only if it can be wrapped without recursive provider dispatch or bypassing its current workspace and per-action approval controls. Because it wraps the same underlying assistant provider, it does not count as an independent model judgment source.
- If the Phase 4 cooperation pattern requires independent model judgment (for example, an independent model challenger), bind two independently addressable model endpoints and test them as separate participants. A deterministic verifier complements but does not replace that requirement.
- Do not count aliases, duplicate endpoint/model configurations, renamed wrappers around the same call path, or test fakes as independent production participants.

**Test adapters:**
- Deterministic fake participants for unit/integration tests, including success, malformed output, timeout, cancellation, unavailable, and budget exhaustion.
- These are test fixtures, not evidence of real-model quality.

Do not implement every future participant category now. Human participants, remote agent frameworks, arbitrary external tools, distributed workers, and multiple provider-specific SDKs remain extensibility targets until a validated use case requires them.

## 6. Resource admission and provider budgets

Phase 3 requires a minimal mandatory dispatch gate, not the Phase 5 general scheduler.

Before dispatch:

1. Validate the requested resource budget and provider budget.
2. Obtain current telemetry with explicit freshness/unknown status.
3. Estimate the invocation conservatively from declared requirements and configured limits.
4. Protect existing interactive-use reserves.
5. Check per-integration rate/token/concurrency limits and any configured spend ceiling.
6. Reject or defer if a required estimate, telemetry field, quota, or compliance status is unknown.
7. Record the decision and reason before invoking the adapter.

Resource estimates are not guarantees or OS isolation. The existing hardware admission endpoint is advisory and does not reserve capacity. For the first runtime, prefer one global single-flight provider dispatch across Evo instances rather than pretending to have a predictive scheduler. Acquire a durable lease with SQLite `BEGIN IMMEDIATE` in the Registry database transaction boundary, revalidating the workspace/project/configuration and pinned revision in the same transaction. A process-local semaphore is insufficient for multi-process correctness. Bound the lease by the provider deadline or renew it, release it on all terminal paths, and recover abandoned leases conservatively without allowing overlapping live invocations.

For the local-first deployment, do not invent token/cost estimates when the endpoint does not report usage. Track configured maximums and actual usage when returned; label unavailable measurements as unknown. Remote-provider request/token budgets must be operator-configured and enforced conservatively; if quota is unknown and no conservative local limit is configured, fail closed. The first version need not implement sophisticated forecasting or dynamic model loading.

## 7. Security, isolation, and failure requirements

- Resolve the exact workspace-pinned configuration revision at dispatch time. Reject missing/mismatched revisions and archived/inactive workspace, project, or configuration relationships. Do not reject an older pinned revision merely because the configuration's current revision has advanced.
- The initial deployment remains local and single-user. The current loopback-host/CORS boundary is not individual-user authentication. Do not claim a verified user identity; record the local single-user authority assumption. Do not expose the API remotely or add multi-user behavior without a separate authentication/session/CSRF/authorization design.
- Preserve Phase 2 project/workspace isolation. Context assembly and tools receive only the authorized scope.
- Treat configuration content, retrieved context, participant messages, repository files, and tool output as untrusted input.
- Never let configuration or participant output expand global command policy, filesystem access, network access, secrets access, or approval authority.
- Keep credentials in approved secret handling; redact them from errors, events, and telemetry. The initial resolver accepts only environment-variable references whose names are explicitly allowlisted in operator-owned configuration; absent allowlist means deny.
- Provider endpoint origins are security-sensitive: allow loopback HTTP for local inference; require HTTPS and exact operator allowlisting for non-loopback origins. Reject embedded credentials, prohibited resolved destinations, and cross-origin redirects; revalidate same-origin redirects and never forward authorization across origins.
- Provider compliance approval is separate from endpoint allowlisting and health. The operator must approve each exact origin, adapter/interface, and intended use with review provenance; unknown, restricted, suspended, or stale approval blocks dispatch. Loopback addressing alone does not prove data stays local.
- Enforce timeouts, bounded input/output sizes, cancellation checks, and finite retries.
- Unknown adapter, availability, compliance, resource capacity, or authorization fails closed for execution.
- Do not silently substitute another provider, model, adapter, configuration revision, or permission set.
- Provider integrations must use documented, supported interfaces and comply with current terms, licensing, API permissions, automation restrictions, and data-handling requirements.
- Preserve the current approval-gated coding-agent behavior; registration in the participant system does not bypass per-action approvals.

## 8. Implementation sequence

The following order minimizes speculative framework work.

### P3.1 — Executable configuration contract (prerequisite)
- Freeze the minimum typed component schema, adapter ID/version fields, and component contract versions.
- Keep schema-version 1 definitions readable and editable for compatibility, but treat them as non-executable by default. Existing schema-1 workspaces require an explicit migration preview, a new immutable schema-2 revision, and a version-checked workspace rebind; never auto-migrate or execute schema 1 through an implicit compatibility bridge.
- Define migration rules that preserve the original revision, report unknown/ambiguous fields, and require manual reconstruction when a lossless mapping is not provable.
- Require schema 2 for runnable components; reject unknown component types, adapter IDs, component versions, and unsupported settings with actionable errors.
- Define adapter, participant, invocation-envelope, event, and result contracts, including explicit availability, authorization, and compliance states.
- Define schema-2 `assistant_runtime` composition so provider/model, generation parameters, context/memory/history budgets, and persona guidance all come from the pinned revision; define typed `command_policy` that preserves the operator global ceiling.
- Define the logical assistant entrypoint and explicit component-key references; no "first model" or implicit component selection.
- Specify the initial secret-reference grammar and environment-variable-backed resolver only, with an operator-owned environment-name allowlist. Missing, malformed, or disallowed references fail closed; credentials are never persisted in definitions or emitted in errors, events, or telemetry.
- Freeze provider endpoint destination policy: loopback HTTP for local inference; exact operator allowlisting plus HTTPS for non-loopback origins; reject embedded credentials, prohibited resolved addresses, and cross-origin redirects.
- Define operator-owned compliance approvals per exact origin, adapter/interface, and use, with review provenance separate from endpoint allowlisting.
- Define explicit schema-1 migration preview and version-checked workspace rebind; preserve old immutable revisions and never auto-migrate.
- Define bounded/cooperative cancellation semantics consistent with the current provider transport; do not promise interruption of an in-flight blocking request unless implemented and tested.
- Reconcile the Phase 2 roadmap status and acceptance evidence before Phase 3 runtime implementation proceeds.

**Exit:** the executable schema and compatibility policy are documented, validated, and independently reviewed. Existing schema-1 examples cannot accidentally become runnable.

### P3.2 — Registry-driven runtime binding (critical path)
- Make the first runtime slice a concrete factory that takes the resolved workspace binding and exact immutable AI Configuration revision and constructs the complete assistant runtime actually used by the invocation, not just a replacement provider.
- Route every registered-workspace entrypoint through this factory: workspace-scoped chat turns, agent-plan proposal generation, and CodingAgent/approved-plan execution. Keep the legacy global assistant path only for calls without a registered workspace binding.
- Add explicit, version-checked workspace configuration rebind with append-only binding history. Rebind creates no revision and changes no in-flight invocation; it only changes which already-existing immutable revision future invocations resolve.
- Persist a secret-safe immutable runtime snapshot for each caller-assigned invocation ID. The snapshot records exact workspace/version/configuration revision, revision hash, checkout, participant and adapter identity, effective runtime settings, command policy, invocation kind, and provenance; it excludes resolved credential values. Snapshot creation revalidates the workspace binding inside the same SQLite write transaction, and snapshot rows are append-only with integrity hashes. Snapshot persistence does not itself authorize dispatch or prove execution.
- Consume snapshots at every workspace invocation boundary: workspace chat, plan proposal, plan execution, and coding-agent start. Use distinct invocation IDs for proposal and execution; retain the proposal ID on the plan, the execution ID plus proposal ID in the run metadata, and the chat invocation ID in both turn messages. Coding-agent workers must verify the stored snapshot's invocation kind, workspace/version/revision identity, and full non-secret runtime payload before proceeding; a rebind or runtime drift fails closed rather than silently changing the run's revision.
- Record the snapshot before the existing dispatch gate so a valid but currently disabled workspace request leaves an auditable binding attempt. Such a snapshot is not an executed invocation, is not a lifecycle record, and does not enable dispatch. Rejected scope/configuration requests must not create snapshots. P3.5 remains responsible for durable admission decisions and invocation lifecycle state. Runs created before invocation-snapshot integration have no invocation reference and therefore fail closed if a worker attempts to process them; they are not silently rebound or resumed. Recovery requires a new task with a fresh workspace binding and snapshot. This is an intentional compatibility boundary, not automatic migration of in-flight work.
- Binding order is fixed: authorized workspace → active configuration relationship → exact workspace-pinned immutable revision → schema/entrypoint validation → explicit logical-entrypoint-to-component resolution → assistant-runtime/model-reference validation → code-controlled adapter registry → resolved secret references → immutable participant and assistant-runtime instances.
- A newer configuration current revision does not invalidate an older revision pinned by a workspace. Reject missing/mismatched revisions and inactive/archived relationships, not merely revisions that are no longer current.
- The selected revision must determine provider/model, generation settings, context/memory/history budgets, persona guidance, and project command policy. Operator-owned global command ceilings and code-owned safety policy remain outside user configuration and cannot be overridden. Record exact provenance in the participant and invocation.
- Do not fall back to the global TOML provider when a registered workspace binding is missing, invalid, stale, or unsupported. Preserve the existing global TOML assistant path only for callers that do not use a Registry-bound workspace.
- Resolve endpoint/model availability explicitly; distinguish unavailable from unknown and do not substitute another model.
- Add deterministic binding tests proving that two revisions with different provider/model/generation/context/policy settings produce the corresponding distinct runtime behavior across workspace chat, plan proposal, and coding-agent execution. These tests must use fake/inert adapters and prove runtime construction/routing without making live provider dispatch available before P3.5. Changing global TOML provider/model/generation values must not change Registry-bound behavior except operator ceilings and code-owned safety policy. Also test invalid component/entrypoint/reference, missing adapter, bad secret, unavailable endpoint, missing/mismatched revision, archived relationship, and workspace/configuration mismatch. Prove that a workspace pinned to an older still-existing revision continues to use it after a newer revision is created.

**Exit:** end-to-end tests with inert/fake adapters prove that the exact immutable workspace configuration revision—not global TOML—determines provider/model, assistant generation/context behavior, and project command policy for workspace chat, plan proposal, and coding-agent execution. No live participant dispatch is enabled by this milestone. This is the Phase 3 prerequisite; contract scaffolding or binding only one entrypoint does not pass.

### P3.3 — First provider participant
- Wrap/reuse the existing OpenAI-compatible transport behind the new adapter boundary.
- Preserve the global TOML assistant path for non-Registry callers. The direct `evo chat` and `evo code` CLI modes are explicitly privileged local-only operations, require an acknowledgement flag, and are not represented as Registry-scoped API equivalents. Any future Registry-aware CLI mode must reuse the same runtime-binding and authorization boundary.
- Normalize streaming, usage, errors, timeout, cancellation, and malformed responses.
- Record adapter/config/provider/model provenance without exposing credentials.

**Exit:** existing chat/provider tests still pass; the adapter can be constructed and contract-tested through a Registry-bound participant with equivalent normalized behavior. Live Registry-bound provider dispatch remains disabled until P3.5 supplies the mandatory authorization, budget, and atomic-admission gate.

### P3.4 — Second production participant implementation
- Implement a bounded deterministic verifier/tool participant as the default second production runtime kind, unless source investigation shows a more useful safe runtime.
- Give it a real input/output contract, explicit limits, deterministic behavior, and evidence-bearing results. It must not gain authority to execute arbitrary tools or expand permissions.
- Keep the CodingAgent option separate: it may qualify as a distinct runtime kind only if its tool-use and approval behavior are genuinely represented through the participant contract; it never counts as an independent model.
- If the Phase 4 pattern requires independent model judgment, add and test two independently addressable model endpoints as separate participants.
- If no second production runtime can be integrated safely, report the blocker and seek an explicit Phase 3/4 acceptance revision rather than weakening boundaries.

**Exit:** two genuinely distinct production participant implementations can be bound and contract-tested through the common contract, with deterministic tests and documented contributions. Live dispatch of either participant remains gated on P3.5. If Phase 4 requires independent model judgment, the two-model-endpoint requirement is separately met.

### P3.5 — Invocation authorization, budgets, and minimal admission
- This is the first milestone that may enable live participant dispatch. Until its gate is complete, P3.2–P3.4 may construct, inspect, and test participants with inert/fake adapters, but must not expose a live Registry-bound invocation path.
- Add a single dispatch boundary that resolves task/workspace scope and effective permissions.
- Add per-invocation deadlines, output/token limits, provider quota checks, and minimal resource admission.
- Use a conservative global single-flight provider-dispatch lease initially, acquired atomically with SQLite `BEGIN IMMEDIATE` in the Registry database transaction boundary. A process-local semaphore is not sufficient for multi-process correctness. The transaction revalidates active workspace/project/configuration state and the exact pinned revision before acquiring the lease.
- Bound live leases by the provider deadline and heartbeat them; release them on observed terminal paths. If the owner process disappears or a lease becomes uncertain, mark it abandoned and block new dispatch until endpoint idleness is established or the operator explicitly acknowledges recovery. Do not auto-release solely on TTL because provider-side work may outlive the client process.
- Persist invocation state and link existing run/event IDs.
- Test denied, deferred, unknown, expired, cancelled, rate-limited, and failed outcomes.

**Exit:** no adapter can be invoked without an auditable authorization and admission decision; concurrent dispatch cannot bypass configured local/provider limits.

### P3.6 — API and configuration integration
- Expose read-only participant/binding/availability inspection first.
- Add explicit, permission-checked invocation only when the backend boundary is complete.
- Keep UI changes minimal: make binding and availability errors inspectable; do not start the full Cyberdeck redesign.
- Ensure backend APIs, not frontend state, enforce authorization.

**Exit:** API tests prove equivalent enforcement and no secret leakage; frontend can inspect real participant/configuration status without inventing runtime state.

### P3.7 — Independent review and Phase 3 acceptance
- Run migration tests, full Python suite, compile checks, frontend build, and diff checks.
- Run deterministic adapter contract tests and end-to-end local endpoint smoke tests where the target endpoint is available.
- Have an independent reviewer challenge adapter boundaries, secret handling, stale configuration behavior, resource admission, and project isolation.
- Record exactly which live provider tests were run and which were not.

**Exit:** all Phase 3 roadmap acceptance criteria are evidenced and accepted. Only then begin Phase 4 cooperative execution.

## 9. Phase 3 acceptance checklist

- [ ] At least two genuinely distinct participant implementations satisfy the common versioned contract.
- [ ] Exact immutable AI Configuration revisions resolve to supported runtime adapters.
- [ ] Participant identity, capabilities, availability, compliance, provenance, and authorization are distinct and inspectable.
- [ ] Unknown/unsupported components fail explicitly; no silent provider/model/policy fallback.
- [ ] Invocation envelopes carry bounded objective, scope, context provenance, output contract, permissions, deadline, and budgets.
- [ ] Existing workspace isolation and command approval boundaries remain intact.
- [ ] Minimal resource admission and provider budgets are mandatory before dispatch.
- [ ] Unknown required capacity/quota/compliance fails closed or is surfaced for explicit authorized override where policy permits.
- [ ] Invocation records preserve exact configuration revision, adapter version, provider/model identity, effective policy, admission decision, usage, and outcome.
- [ ] Tests cover malformed output, unavailable participants, timeout, cancellation, rate limiting, budget exhaustion, missing/mismatched revisions, continued validity of older pinned revisions, unauthorized scope, and secret redaction.
- [ ] Independent review and required repository validation are recorded.

## 10. Explicit exclusions

Phase 3 does not implement:

- the full multi-agent task/assignment/handoff state machine;
- durable parallel orchestration, worktree management, general retries, or checkpointed resume;
- unrestricted tool execution or autonomous coding;
- model training, fine-tuning, or a new inference engine;
- arbitrary plugin/module loading from configuration;
- automatic provider/model substitution or failover;
- automatic trust-score-based permission grants;
- a general distributed scheduler or speculative resource forecasting;
- full Cyberdeck UI or wholesale product redesign;
- automatic provider policy acceptance or terms-of-service bypasses.

These remain governed by later roadmap phases or separate explicit decisions.

## 11. Decisions and bounded implementation choices

The following choices constrain P3.1 and should not be reopened without new source evidence or an explicit user decision:

1. **Schema compatibility:** schema-version 1 remains readable/editable but is non-executable by default. Runnable typed components require the next schema version and explicit component type/version plus adapter ID/version. Any schema-1 migration must be explicit, validated, and auditable.
2. **Secret resolution:** the initial resolver supports environment-variable references only, with strict syntax, required-variable checks, and redaction. Other secret stores are out of scope until separately designed and approved.
3. **Runtime binding:** registered-workspace execution has no global TOML fallback. The global TOML assistant remains a separate legacy path only for non-Registry callers.
4. **Cancellation:** cancellation is cooperative at safe boundaries and bounded by provider request timeout. Terminal status and partial evidence must be accurate; immediate in-flight cancellation is not promised by the current transport.
5. **Second participant:** default to a bounded deterministic verifier/tool participant. It is not an independent model. If Phase 4 requires independent model judgment, require two independently addressable model endpoints.
6. **Admission:** do not use the advisory assess_workload function as a dispatch gate. P3.5 must use a durable atomic global single-flight lease initially; process-local semaphores are insufficient. Unknown required capacity/quota fails closed. An abandoned lease blocks new dispatch until safe recovery is established; it is not automatically freed merely because a TTL elapsed.
7. **Participant identity:** use stable integration identity plus immutable revision-specific participant instance identity unless implementation evidence shows that this complicates correctness.
8. **Pinned revisions:** a workspace remains bound to its exact immutable revision even after a newer configuration revision is created. "Stale" means missing/mismatched revision or inactive/archived relationship—not simply "not current."
9. **Endpoint security:** loopback HTTP is permitted for local inference; non-loopback origins require HTTPS and exact operator allowlisting. Reject embedded credentials and cross-origin redirects; validate resolved destinations against the same policy.
10. **Secret allowlist:** environment variable names are allowlisted in operator-owned application configuration; the AI Configuration definition cannot expand that allowlist.
11. **Initial admission:** prefer one global in-flight provider dispatch across Evo instances using a durable SQLite lease. This intentionally conservative single-flight policy is the initial atomic gate, not a general scheduler.

The precise Python names and persistence details remain implementation choices, but these invariants are not optional. Keep the implementation minimal and evidence-driven.

---

**Implementation boundary:** P3.1 contract foundations are accepted and P3.2 implementation is authorized. Continue only within the documented phase sequence. Do not enable live dispatch before P3.5 authorization/admission, and resolve P3-R4 before finalizing P3.5 admission.
