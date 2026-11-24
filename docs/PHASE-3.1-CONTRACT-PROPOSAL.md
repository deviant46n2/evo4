# Phase 3.1 — Executable Configuration and Participant Contract Proposal

**Status: proposed for user and independent review; no implementation authorization implied.**  
**Parent plan:** `docs/PHASE-3-TECHNICAL-PLAN.md`  
**Authority:** `ROADMAP.md` governs phase order and acceptance.

## 1. Purpose and boundary

P3.1 freezes the smallest executable configuration and participant contract needed to prove Registry-driven runtime binding in P3.2. It must not become a general orchestration framework.

The critical invariant is:

> For registered-workspace execution, the exact immutable AI Configuration revision resolved from the authorized workspace determines the participant/provider that is invoked. If that binding is invalid or unavailable, execution fails explicitly. It never falls back to the global TOML assistant.

The existing TOML-backed assistant remains supported as a separate legacy path for callers that do not supply a Registry-bound workspace. Every workspace-bound entrypoint—chat turns, agent-plan proposal generation, and coding-agent/approved-plan execution—must use the same revision-derived assistant runtime; binding only the final coding-agent run is insufficient.

## 2. Configuration schema proposal

### 2.1 Versioning

- Existing `schema_version: 1` definitions remain readable, listable, and editable.
- Schema 1 is **not executable by default**. The current generic JSON validator is not evidence that a component is runtime-valid.
- Introduce `schema_version: 2` for executable typed components.
- Schema 2 components must declare a recognized component type, component schema version, adapter ID, adapter contract version, and typed settings.
- Unknown component types, component versions, adapter IDs, adapter versions, settings, or required capabilities are rejected. There is no permissive "best effort" interpretation.
- Any schema-1 migration must be explicit, produce a new immutable revision, pass schema-2 validation, and preserve the original revision unchanged.
- Schema 2 has a strict top-level shape: `schema_version`, `components`, `entrypoints`, and optional non-executable `extensions`. Schema 1 retains its existing top-level shape.

### 2.2 Component envelope

Each executable component uses a common envelope:

```json
{
  "schema_version": 2,
  "components": {
    "primary_model": {
      "type": "model",
      "component_version": 1,
      "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
      "settings": {
        "endpoint": "http://127.0.0.1:18997/v1",
        "model": "configured-model",
        "timeout_seconds": 120
      },
      "secret_refs": {"api_key": "env:EVO_LOCAL_API_KEY"}
    },
    "assistant": {
      "type": "assistant_runtime",
      "component_version": 1,
      "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
      "settings": {
        "model_component": "primary_model",
        "persona_prompt": "Be concise and evidence-driven.",
        "max_output_tokens": 2048,
        "temperature": 0.2,
        "context_window_tokens": 49152,
        "history_messages": 16,
        "max_history_chars": 40000,
        "memory_limit": 8
      }
    },
    "command_policy": {
      "type": "command_policy",
      "component_version": 1,
      "adapter": {"id": "evo_command_policy", "contract_version": 1},
      "settings": {"allowed_commands": [["pytest"]]}
    }
  },
  "entrypoints": {"assistant": "assistant"}
}
```

This is a shape proposal; exact required/optional fields, bounds, and adapter contracts must be frozen in P3.1. The top-level `components` object retains stable component keys. A key identifies a component within the configuration; it is not an executable class name or provider role. The `entrypoints` map selects a named component for a logical use; it cannot select arbitrary code.

- Initial component types are `model`, `assistant_runtime`, `command_policy`, and `deterministic_verifier`.
- `assistant_runtime` references a model component by key and owns generation/context behavior currently read from global TOML: persona prompt, output-token limit, temperature, context window, history limits, and memory retrieval limit. Registry-bound execution must not silently inherit these execution settings from global TOML.
- The persona prompt is user-authored behavior guidance, not trusted platform policy. It must be represented as untrusted configuration content and cannot override code-owned safety policy, scope, permissions, approvals, or tool boundaries.
- `command_policy` owns project-level command prefixes and can only narrow the operator's global TOML command ceiling. The global ceiling remains operator-owned; project configuration can never expand it. The typed schema must preserve the existing fail-closed intersection semantics.
- `component_version` versions the typed component's data contract.
- `adapter.contract_version` selects a supported adapter contract, not an arbitrary installed package version. The adapter implementation/build version is code-owned and recorded at bind time.
- Configuration may declare required capabilities, but may not assert the capabilities it possesses. The adapter derives provided capabilities from its implementation and validated settings.
- Adapter IDs resolve only through a code-controlled registry. Configuration data cannot import modules, name Python classes, or load arbitrary code.
- Unknown fields are rejected except inside explicitly namespaced, versioned extension points. Do not make arbitrary `extensions` executable.

### 2.3 Initial executable component types

P3.1 should authorize only these initial types:

1. **`model`** — text-generation participant through the existing OpenAI-compatible chat-completions transport. Settings are limited to endpoint, model identifier, bounded timeout, and supported transport options. Tool-call generation may be represented as an interface capability, but does not grant tool execution authority.
2. **`assistant_runtime`** — code-owned composition component that binds one model component and its generation/context settings. It is not a provider and cannot create arbitrary tools or authority.
3. **`command_policy`** — typed project command-prefix policy. It narrows the operator's global allowlist and preserves explicit per-action approval. It does not grant OS sandboxing.
4. **`deterministic_verifier`** — bounded structured-output/evidence-contract verifier. It validates declared output shape, required fields, and evidence-reference structure. It does not make semantic correctness judgments or execute arbitrary tools.

The existing CodingAgent remains a code-owned execution runtime, not a user-configurable executable component. It may consume a workspace-bound assistant runtime and typed command policy only after its tool-use and approval semantics are preserved; it is not a second independent model.

## 3. Secret-reference contract

- Initial supported reference form: `env:VARIABLE_NAME`.
- The variable name must match a strict environment-variable identifier grammar.
- The allowlist is operator-owned application configuration, not part of an AI Configuration definition. Proposed TOML shape: `[secrets] allowed_env_vars = ["EVO_LOCAL_API_KEY", "EXAMPLE_CLOUD_API_KEY"]`. The list contains names only, never secret values. An absent/empty allowlist means no Registry secret references are permitted.
- Resolution is performed only at the adapter boundary, after the exact workspace revision and adapter have been validated, and never while serializing or displaying a definition.
- The resolver reads only an explicitly allowlisted name. Missing, empty, malformed, or non-allowlisted references fail closed before any network request.
- Resolved values are transient. They must never appear in definitions, participant descriptors, invocation envelopes, logs, exception text, events, telemetry, API responses, or content hashes. Do not include request headers in diagnostic output.
- Provider errors must be normalized and redacted before persistence or exposure; do not persist raw HTTP response bodies by default.
- No arbitrary secret stores, shell expansion, file paths, URL-embedded credentials, or implicit environment lookups are supported in this initial version.

## 4. Provider endpoint security

The endpoint is security-sensitive configuration because it determines where prompts, retrieved context, and credentials are sent.

- Permit loopback HTTP for local inference by default. Require HTTPS for non-loopback origins.
- Non-loopback origins must match an exact operator-configured origin allowlist; no wildcard host patterns. The allowlist is separate from the component definition and is controlled by the operator.
- Reject URL user-info, embedded credentials, fragments, unexpected query strings, unsupported schemes, and malformed ports. Normalize and compare scheme/host/port as an origin.
- Validate resolved destination addresses against the configured endpoint policy. Permit loopback destinations only for the fixed local-inference policy; reject link-local and metadata-service destinations. Private-network destinations require exact operator approval. Revalidate redirects and DNS resolution so a permitted hostname cannot redirect or resolve into a prohibited destination.
- The exact-origin allowlist is operator-owned application configuration, for example `[security] allowed_provider_origins = ["https://api.example.com"]`. Local loopback origins may be allowed by the adapter's fixed local policy; other origins require an exact operator entry.
- Redirects to a different origin are rejected. Same-origin redirects, if supported, must be bounded and revalidated.
- Do not forward authorization headers across origins. Do not permit arbitrary headers, proxy overrides, or caller-controlled redirect behavior through component settings.
- Tests must cover disallowed scheme/origin, embedded credentials, redirects, private/link-local targets, and secret non-disclosure.

This is a provider destination policy, not a claim that endpoint allowlisting makes a remote provider compliant. Provider/interface/use compliance remains a separate approval decision.

## 5. Adapter and participant contracts

### 5.1 Adapter responsibilities

A code-registered adapter owns provider-specific configuration validation, secret resolution, endpoint interaction, and normalization. It does not decide project scope, task permissions, user approval, or whether a participant is trusted.

Minimum adapter operations:

- validate and bind a typed component definition;
- report adapter identity/version and supported component contract versions;
- construct an immutable participant instance;
- report bounded availability/health observations;
- invoke a validated request and emit normalized events plus one terminal result.

### 5.2 Participant identity

Use two identities:

- **Integration identity:** stable identity for the configured provider/service integration, independent of a particular configuration revision.
- **Participant instance identity:** immutable identity derived from the integration plus the exact configuration revision and component key/version.

A participant instance captures adapter identity/version, capabilities, endpoint/model identity (without credentials), configuration ID/revision, limits, and compliance reference. Availability observations may change; the participant's bound configuration and identity do not mutate in place.

Capabilities describe interface support, not trust or authorization. Registration does not grant permission to execute.

## 6. Caller authority and deployment trust boundary

The current Evo API is a local, single-user application boundary. It restricts request hostnames to loopback and limits browser origins, but it does not authenticate individual users or provide a multi-user principal/role system. P3 must not invent an authenticated `user_id` or claim that loopback host validation is strong authentication.

For the initial deployment:
- Treat the caller as the local operator only within the existing local-process trust assumption.
- Preserve the loopback-only API boundary and explicit per-action approval for consequential coding-agent tools.
- Record the authority source as the local single-user API boundary, not as a verified identity.
- Do not expose the API on a LAN or public interface as part of Phase 3.
- Any remote or multi-user deployment is blocked until a separate authentication, session, CSRF, and authorization design is implemented and reviewed.

## 7. Invocation envelope and outcomes

A bounded invocation envelope must identify:

- invocation and parent task/assignment IDs;
- participant instance and adapter identity/version;
- exact configuration ID/revision and component key/version;
- project/workspace scope and authorized execution context;
- objective, task-scoped role, bounded input, and provenance-labelled context references;
- required output contract and acceptance criteria;
- effective permissions and approval requirements;
- deadline, cancellation signal, retry policy, and remaining budgets;
- correlation/provenance metadata.

The initial normalized terminal outcome set should distinguish at least:

- `succeeded`
- `malformed_output`
- `unavailable`
- `denied`
- `rate_limited`
- `timed_out`
- `cancelled`
- `budget_exhausted`
- `provider_failed`

Partial output is retained only as partial evidence and never converted into success. Error details are bounded and redacted.

## 8. Availability, authorization, and compliance

These are independent dimensions and must not be collapsed:

- **Availability:** `available`, `unavailable`, `unknown`, `disabled`. A configured endpoint is not automatically available; a successful health probe is only a time-bounded observation.
- **Authorization:** invocation-specific `authorized` or `denied`, with policy reason and provenance.
- **Compliance:** `local_only`, `approved`, `restricted`, `suspended`, `unknown`, with integration/interface/use review provenance. `local_only` is an explicit operator classification, not inferred from a loopback address.

A model-list endpoint is a best-effort discovery signal, not proof that a particular model will accept a completion request. Conversely, an endpoint that does not implement model listing is not automatically unavailable; its availability is unknown unless another supported probe establishes it. For the initial release, unknown availability denies dispatch. An adapter may define a documented, bounded probe that establishes availability; there is no implicit first-request fallback. Unknown availability cannot be overridden by a participant, task, or configuration definition.

A health check does not establish compliance. Capabilities, availability, successful history, endpoint allowlisting, or Registry membership do not grant authorization or compliance approval. Unknown or stale required compliance status blocks dispatch.

For the initial release, compliance approval is operator-owned and separate from the AI Configuration. A proposed TOML representation is:

```toml
[[provider_approvals]]
origin = "https://api.example.com"
adapter_id = "openai_compatible_chat"
uses = ["chat_completion"]
status = "approved"
reviewed_at = "2026-11-23"
terms_reference = "provider terms revision reviewed"
data_handling_reference = "provider data-handling policy reviewed"
```

- A local endpoint may be marked `local_only` only by explicit operator configuration; loopback addressing alone does not prove that a service keeps data local.
- A remote endpoint requires an explicit approval record keyed by exact origin, adapter/interface, and approved use. The record includes status, review timestamp, and non-secret references/versions for the applicable terms and data-handling review.
- Missing approval defaults to `unknown`; user-authored component definitions cannot approve themselves or expand approved uses.
- `restricted` and `suspended` block dispatch. Approval of one use (for example, text generation) does not automatically approve other uses or data classes.
- Evo does not automatically determine legal compliance or monitor provider policy changes in this phase. The operator attests to the reviewed terms/data-handling version; a known material change invalidates the approval until re-reviewed.

## 9. Cancellation, timeout, and resource admission

- Cancellation is cooperative at safe boundaries and bounded by the provider request timeout in the initial transport. The API must not promise immediate interruption of an in-flight blocking request.
- The terminal result must state whether cancellation was observed before dispatch, between stream events, or only after the provider returned/timed out.
- Do not use advisory workload assessment as a dispatch gate.
- For the first release, prefer a conservative global single-flight participant-dispatch policy: at most one provider-backed invocation is admitted at a time. This is intentionally throughput-limited and can be generalized only after measured need.
- Enforce single-flight with a durable SQLite lease in the same database file and transaction boundary as Registry workspace/configuration state. Acquire it with `BEGIN IMMEDIATE`, revalidate workspace/project/configuration status and the pinned revision in that transaction, then commit the lease before network dispatch. A process-local semaphore alone is insufficient across multiple processes.
- Lease records include invocation ID, owner/process identity, acquired/heartbeat timestamps, and terminal state. The lease is released on every observed terminal path. A process crash or lost owner marks the lease `abandoned`; do not automatically release it solely because a TTL elapsed, because provider-side work may continue after the client process disappears. New dispatch remains blocked until endpoint idleness is established or the operator explicitly acknowledges recovery. A provider deadline bounds normal live requests but does not prove remote server cancellation.
- This is a serialization gate, not proof of free VRAM or OS-level isolation. Required telemetry that is absent or stale remains unknown and blocks any policy that depends on it.
- Remote-provider request/token budgets must be explicit operator-configured limits. If a provider's quota is unknown and no conservative local limit is configured, fail closed. Usage not reported by the endpoint remains unknown, never fabricated.
- The initial mechanism is not a general-purpose scheduler and does not claim OS-level resource isolation.

## 10. Runtime binding sequence and revision semantics

P3.2 must implement this exact order:

1. Validate the requested workspace and caller authority.
2. Resolve the active workspace/project/checkout relationship.
3. Resolve the active AI Configuration relationship.
4. Load the exact immutable revision ID pinned by that workspace and verify that it belongs to the referenced configuration.
5. Validate schema version, typed component contracts, and the requested logical entrypoint.
6. Resolve the entrypoint to a component key and validate all component references, including the assistant-runtime-to-model reference.
7. Resolve each component's adapter ID/contract version through the code-controlled registry.
8. Resolve allowlisted secret references.
9. Apply endpoint destination policy and obtain the required availability/compliance decision.
10. Construct the immutable model participant and assistant runtime from the pinned revision, with exact provenance.
11. Atomically revalidate the workspace/configuration state and acquire dispatch admission before invoking the adapter.

**Pinned-revision rule:** advancing a configuration's `current_revision_id` does not make an older immutable revision stale and must not change a workspace's behavior. A workspace continues to use its pinned revision while the workspace, project, and configuration remain active and the pinned revision exists and belongs to that configuration. A missing revision, mismatched configuration/revision pair, archived configuration, archived workspace, or inactive project is invalid. Updating to a newer revision requires an explicit workspace change/rebind operation that records the new pinned revision and version.

No failure may fall back to global TOML, another revision, adapter, endpoint, model, or policy for a Registry-bound workspace.

## 11. Required P3.1/P3.2 tests

- Schema-1 definitions remain readable/editable but cannot execute by default.
- Migration preview is lossless and explicit; unknown schema-1 shapes are reported as requiring manual migration.
- Migration creates a new immutable schema-2 revision without changing the original schema-1 revision.
- A workspace remains pinned to schema 1 until explicit version-checked rebind; binding history records old/new revision and reason.
- Concurrent rebind attempts with stale expected versions fail safely; in-flight invocations retain their captured binding.
- Schema-2 valid model and verifier components validate.
- Unknown component, component version, adapter, adapter version, or setting is rejected.
- Secret references reject malformed, missing, empty, and non-allowlisted variables; resolved values are redacted from all observable surfaces.
- Exact immutable workspace revision determines provider/model, generation settings, context/memory/history budgets, persona guidance, and project command-policy behavior.
- Changing global TOML provider/model/generation values does not alter a Registry-bound workspace invocation, except for explicitly operator-owned ceilings and code-owned safety policy.
- The typed command-policy component preserves the existing global-ceiling intersection and per-action approval behavior.
- Two different revisions produce the corresponding different participant bindings.
- Missing revision, revision/configuration mismatch, archived configuration/workspace, inactive project, and mismatched workspace/project are rejected.
- Advancing the configuration's current revision does not invalidate a workspace pinned to an older still-existing revision; tests prove the old workspace continues using its pinned revision until explicitly rebound.
- Unavailable endpoint and unknown availability are distinct outcomes.
- No Registry-bound failure falls back to the global TOML assistant.
- Endpoint policy rejects disallowed origins, insecure non-loopback HTTP, embedded credentials, cross-origin redirects, and prohibited resolved addresses.
- Endpoint allowlisting without a matching operator compliance approval does not authorize remote dispatch; unknown, restricted, suspended, or stale approval states fail closed.
- Loopback endpoint classification does not automatically establish `local_only` compliance status.
- A configured but unprobeable endpoint remains `unknown`; initial dispatch is denied until a supported bounded probe establishes availability.
- Concurrent invocations cannot both acquire the initial global single-flight lease; crashed/ownerless leases become abandoned and block new dispatch until safe recovery is explicitly established.
- Workspace chat turns, agent-plan proposal generation, and coding-agent/approved-plan execution all use the exact same workspace-bound assistant runtime factory.
- Project-only/global callers without a registered workspace retain the legacy TOML-backed assistant path.
- Legacy non-Registry callers continue to use the existing TOML-backed assistant path.

## 12. Decisions requested

Approval is requested for these architectural constraints, not for implementation:

1. Schema 1 remains readable but non-executable by default; schema 2 is required for runnable typed components. Existing schema-1 workspaces require an explicit migration preview, new immutable schema-2 revision, and version-checked workspace rebind; no silent auto-migration.
2. The initial secret resolver supports allowlisted environment-variable references only.
3. Registry-bound runtime binding has no global TOML fallback; legacy TOML behavior remains separate for non-Registry callers.
4. The schema-2 assistant-runtime component binds model selection, persona guidance, generation parameters, context/memory/history budgets, and the logical assistant entrypoint to the same immutable revision. Operator safety policy remains code-owned.
5. The schema-2 command-policy component preserves the operator global command ceiling and can only narrow it.
6. Provider destinations require loopback HTTP or exact operator-allowlisted HTTPS origins, with redirect and resolved-address validation.
7. Provider compliance is separately operator-approved per exact origin, adapter/interface, and use; endpoint allowlisting or a successful health check is not compliance approval.
8. Unknown endpoint availability denies dispatch until a supported bounded probe establishes availability.
9. The default second production participant is a bounded deterministic structured-output/evidence-contract verifier. It validates declared output schemas, required fields, and evidence-reference shape; it does not make semantic correctness judgments, execute arbitrary tools, or replace an independent model challenger.
10. If Phase 4 requires independent model judgment, two independently addressable model endpoints are required.
11. Cancellation is described as cooperative/bounded until transport-level cancellation is actually implemented and tested.
12. Initial provider admission uses a durable global single-flight lease; this is deliberately conservative, not a predictive resource scheduler.
13. Participant identity uses stable integration identity plus immutable revision-specific participant instance identity.

No application code, migrations, API behavior, or services should change until the user explicitly approves the contract and authorizes implementation.
