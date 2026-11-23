# Phase 3 Technical Plan — Participant Contracts and Runtime Integration

**Status: proposed technical plan; implementation not started.**  
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
| AI Configurations | `src/evo_core/ai_configurations.py` stores validated JSON definitions and immutable revisions. The top-level schema is `schema_version`, `components`, and optional `extensions`. | Component payloads are not resolved to installed adapters or executable participant instances. |
| Registry | `src/evo_core/platform_registry.py` and `src/evo_core/workspaces.py` persist configurations, revisions, projects, checkouts, and workspace relationships. | Workspace resolution validates the relationship and returns the configuration/revision, but does not produce a runtime composition. |
| Provider | `src/evo_core/provider.py` implements `OpenAICompatibleProvider` with model listing and streamed chat completions. | No Evo-owned provider-neutral invocation contract, adapter registry, or participant identity layer. |
| Configuration loading | `src/evo_core/config.py` loads the active assistant provider profile from TOML and environment-backed credentials. | This legacy application-level provider selection is separate from Registry AI Configuration execution. |
| Assistant | `src/evo_core/assistant.py` constructs or accepts a provider and uses it for chat. | No configuration-revision-driven provider construction or general participant dispatch. |
| Coding agent | `src/evo_core/coding_agent.py` uses the assistant's provider and existing approval-gated tool boundary. | The coding agent is not yet a separately registered runtime participant with its own versioned contract and explicit binding. |
| Resource intelligence | `evo_experiments.intelligence.assess_workload` and hardware APIs provide advisory admission based on telemetry and estimates. | Admission is not a mandatory gate in participant dispatch; provider quotas and per-invocation token/rate budgets are not integrated. |
| Scheduler | Existing workload queue/reservations and managed execution cover bounded external/command workloads. | This is not a participant scheduler and must not be repurposed as one without an explicit design. |
| Compliance | Provider access uses configured endpoints and credential references/environment variables. | No structured, versioned integration compliance status that can gate use. |
| Persistence | Agent runs, tool events, plans, and experiment records already preserve useful execution history. | No common participant invocation record capturing the exact participant, adapter, configuration revision, effective policy, admission decision, and outcome. |

Important distinction: the current assistant provider profile and Registry AI Configurations are two separate configuration paths. Phase 3 must make the Registry configuration executable without accidentally breaking the existing CLI/chat path. Migration or replacement of the legacy path is not a prerequisite unless implementation proves it necessary.

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

A binding must fail clearly when a component type is unknown, an adapter is unavailable, a required setting/secret is missing, a referenced model is unavailable, or a contract version is unsupported. No silent fallback to the application default provider, another model, a different policy, or a newer configuration revision.

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

**Second adapter boundary:**
- A separate adapter for the existing approval-gated coding-agent runtime, if source review confirms it can be wrapped without creating recursive provider dispatch or bypassing its current safety controls.
- If it cannot be cleanly separated in Phase 3, define the contract and register it as unsupported/unavailable until the boundary is refactored. Do not fake an independent implementation by registering two names for the same provider object.

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

Resource estimates are not guarantees or OS isolation. The existing hardware admission endpoint is advisory and does not reserve capacity. Phase 3 must either introduce a small atomic reservation/lease suitable for one bounded dispatch or explicitly serialize and constrain initial dispatch so concurrent requests cannot each consume the same reported headroom. Do not claim safe admission by merely calling the existing advisory endpoint.

For the local-first deployment, do not invent token/cost estimates when the endpoint does not report usage. Track configured maximums and actual usage when returned; label unavailable measurements as unknown. Provider quotas must be configured explicitly and enforced conservatively. The first version need not implement sophisticated forecasting or dynamic model loading.

## 7. Security, isolation, and failure requirements

- Resolve the exact workspace and configuration revision at dispatch time; reject stale, archived, missing, or mismatched bindings.
- Preserve Phase 2 project/workspace isolation. Context assembly and tools receive only the authorized scope.
- Treat configuration content, retrieved context, participant messages, repository files, and tool output as untrusted input.
- Never let configuration or participant output expand global command policy, filesystem access, network access, secrets access, or approval authority.
- Keep credentials in approved secret handling; redact them from errors, events, and telemetry.
- Enforce timeouts, bounded input/output sizes, cancellation checks, and finite retries.
- Unknown adapter, availability, compliance, resource capacity, or authorization fails closed for execution.
- Do not silently substitute another provider, model, adapter, configuration revision, or permission set.
- Provider integrations must use documented, supported interfaces and comply with current terms, licensing, API permissions, automation restrictions, and data-handling requirements.
- Preserve the current approval-gated coding-agent behavior; registration in the participant system does not bypass per-action approvals.

## 8. Implementation sequence

The following order minimizes speculative framework work.

### P3.1 — Contract and schema freeze
- Define typed component schemas and versioning rules.
- Define adapter, participant, invocation-envelope, event, and result contracts.
- Define identity/lifecycle/availability/compliance/authorization distinctions.
- Specify compatibility and migration behavior for existing configuration definitions.
- Add architecture decision records for any decisions that materially constrain future adapters.

**Exit:** contracts are documented, schema-validated, and independently reviewed before runtime code is introduced.

### P3.2 — Adapter registry and configuration binding
- Add a code-controlled adapter registry.
- Resolve exact immutable configuration revisions.
- Validate component references/settings and secret references.
- Construct immutable participant instances with explicit capabilities, provenance, and limits.
- Return actionable errors for unsupported/missing components; no fallback.

**Exit:** deterministic tests prove valid binding, invalid binding, missing adapter, unavailable endpoint, bad secret reference, and stale revision behavior.

### P3.3 — First provider participant
- Wrap/reuse the existing OpenAI-compatible transport behind the new adapter boundary.
- Preserve current assistant/CLI compatibility.
- Normalize streaming, usage, errors, timeout, cancellation, and malformed responses.
- Record adapter/config/provider/model provenance without exposing credentials.

**Exit:** existing chat/provider tests still pass, and the same endpoint can be invoked through a Registry-bound participant with equivalent observable behavior.

### P3.4 — Second participant boundary
- Integrate the existing coding-agent runtime behind a distinct adapter if safe and non-recursive.
- Preserve registered workspace validation, project command-policy intersection, per-action approval, and tool-event provenance.
- Otherwise document the exact blocker and leave the adapter explicitly unsupported; do not weaken boundaries to meet a count.

**Exit:** two genuinely distinct adapter implementations can be bound and exercised with deterministic tests, or the unresolved boundary is explicitly escalated before Phase 4 planning.

### P3.5 — Invocation authorization, budgets, and minimal admission
- Add a single dispatch boundary that resolves task/workspace scope and effective permissions.
- Add per-invocation deadlines, output/token limits, provider quota checks, and minimal resource admission.
- Serialize or reserve admission atomically to avoid concurrent overcommit.
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
- [ ] Tests cover malformed output, unavailable participants, timeout, cancellation, rate limiting, budget exhaustion, stale revisions, unauthorized scope, and secret redaction.
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

## 11. Open decisions to resolve during P3.1

These are intentionally deferred until the contract review, not assumed:

1. Exact typed component schema shape and whether current opaque component objects need a migration.
2. Whether participant identity is persistent Registry data, derived per immutable configuration revision, or a hybrid (stable integration identity plus revision-specific instance identity).
3. Exact credential-reference resolver and supported secret stores.
4. Whether the coding-agent runtime can be wrapped as a distinct adapter without recursion or authority leakage.
5. The minimal atomic reservation mechanism for dispatch against shared local resources.
6. Initial provider quota dimensions and how unknown usage is represented.
7. Which two production-capable participant implementations will be used for the first real cooperative benchmark.

Resolve these using source inspection, threat modeling, and the smallest demonstrable use case. Do not turn them into an open-ended product-discovery exercise.

---

**Implementation boundary:** This plan is ready for technical review. Phase 3 code changes should begin only after the plan and P3.1 contract proposal are explicitly authorized.
