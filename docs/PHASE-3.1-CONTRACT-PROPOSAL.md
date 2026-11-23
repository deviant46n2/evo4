# Phase 3.1 — Executable Configuration and Participant Contract Proposal

**Status: proposed for user and independent review; no implementation authorization implied.**  
**Parent plan:** `docs/PHASE-3-TECHNICAL-PLAN.md`  
**Authority:** `ROADMAP.md` governs phase order and acceptance.

## 1. Purpose and boundary

P3.1 freezes the smallest executable configuration and participant contract needed to prove Registry-driven runtime binding in P3.2. It must not become a general orchestration framework.

The critical invariant is:

> For registered-workspace execution, the exact immutable AI Configuration revision resolved from the authorized workspace determines the participant/provider that is invoked. If that binding is invalid or unavailable, execution fails explicitly. It never falls back to the global TOML assistant.

The existing TOML-backed assistant remains supported as a separate legacy path for callers that do not supply a Registry-bound workspace.

## 2. Configuration schema proposal

### 2.1 Versioning

- Existing `schema_version: 1` definitions remain readable, listable, and editable.
- Schema 1 is **not executable by default**. The current generic JSON validator is not evidence that a component is runtime-valid.
- Introduce `schema_version: 2` for executable typed components.
- Schema 2 components must declare a recognized component type, component schema version, adapter ID, adapter contract version, and typed settings.
- Unknown component types, component versions, adapter IDs, adapter versions, settings, or required capabilities are rejected. There is no permissive "best effort" interpretation.
- Any schema-1 migration must be explicit, produce a new immutable revision, pass schema-2 validation, and preserve the original revision unchanged.

### 2.2 Component envelope

Each executable component uses a common envelope:

```json
{
  "type": "model",
  "component_version": 1,
  "adapter": {
    "id": "openai_compatible_chat",
    "version": 1
  },
  "settings": {},
  "secret_refs": {}
}
```

The exact top-level `components` organization should preserve stable component keys, but keys are identifiers—not executable class names or provider roles. Adapter IDs resolve only through a code-controlled registry. Configuration data cannot import modules, name Python classes, or load arbitrary code.

### 2.3 Initial executable component types

P3.1 should authorize only these initial types:

1. **`model`** — text-generation participant through the existing OpenAI-compatible chat-completions transport. Settings are limited to the endpoint, model identifier, bounded timeout, and supported generation limits. Tool-call generation may be represented as a capability, but does not grant tool execution authority.
2. **`deterministic_verifier`** — bounded, deterministic validation participant. Its accepted input/output contract and verification function must be explicit and narrow. It must not execute arbitrary commands or gain filesystem/network authority merely by being registered.

The existing coding-agent runtime is not automatically a third executable component. It may be considered later if its tool-use and approval semantics can be represented without recursive provider dispatch or bypassing existing controls.

## 3. Secret-reference contract

- Initial supported reference form: `env:VARIABLE_NAME`.
- The variable name must match a strict environment-variable identifier grammar.
- Resolution is performed only at the adapter boundary, never while serializing or displaying a configuration definition.
- The resolver must enforce an explicit allowlist of environment variable names supplied by application/operator configuration. A configuration cannot read arbitrary process environment variables.
- Missing, empty, malformed, or non-allowlisted references fail closed before dispatch.
- Resolved secret values are transient and must never appear in definitions, participant descriptors, invocation envelopes, logs, exception text, events, telemetry, or API responses.
- No arbitrary secret stores, shell expansion, file paths, URL-embedded credentials, or implicit environment lookups are supported in this initial version.

## 4. Adapter and participant contracts

### 4.1 Adapter responsibilities

A code-registered adapter owns provider-specific configuration validation, secret resolution, endpoint interaction, and normalization. It does not decide project scope, task permissions, user approval, or whether a participant is trusted.

Minimum adapter operations:

- validate and bind a typed component definition;
- report adapter identity/version and supported component contract versions;
- construct an immutable participant instance;
- report bounded availability/health observations;
- invoke a validated request and emit normalized events plus one terminal result.

### 4.2 Participant identity

Use two identities:

- **Integration identity:** stable identity for the configured provider/service integration, independent of a particular configuration revision.
- **Participant instance identity:** immutable identity derived from the integration plus the exact configuration revision and component key/version.

A participant instance captures adapter identity/version, capabilities, endpoint/model identity (without credentials), configuration ID/revision, limits, and compliance reference. Availability observations may change; the participant's bound configuration and identity do not mutate in place.

Capabilities describe interface support, not trust or authorization. Registration does not grant permission to execute.

## 5. Invocation envelope and outcomes

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

## 6. Availability, authorization, and compliance

These are independent dimensions and must not be collapsed:

- **Availability:** `available`, `unavailable`, `unknown`, `disabled`.
- **Authorization:** invocation-specific `authorized` or `denied`, with policy reason and provenance.
- **Compliance:** `approved`, `restricted`, `suspended`, `unknown`, with integration/interface/use review provenance.

A health check does not establish compliance. Capabilities, availability, successful history, or Registry membership do not grant authorization. Unknown or stale required compliance status blocks dispatch.

## 7. Cancellation, timeout, and resource admission

- Cancellation is cooperative at safe boundaries and bounded by the provider request timeout in the initial transport. The API must not promise immediate interruption of an in-flight blocking request.
- The terminal result must state whether cancellation was observed before dispatch, between stream events, or only after the provider returned/timed out.
- Do not use advisory workload assessment as a dispatch gate.
- P3.5 must use an atomic participant dispatch lease/reservation, or a demonstrably serialized single-flight policy, to prevent concurrent overcommit.
- Unknown required capacity, provider quota, or usage limits fail closed. Unreported token/cost usage is represented as unknown, never fabricated.
- The initial mechanism is not a general-purpose scheduler and does not claim OS-level resource isolation.

## 8. Runtime binding sequence

P3.2 must implement this exact order:

1. Validate the requested workspace and caller authority.
2. Resolve the active workspace/project/checkout relationship.
3. Resolve the active AI Configuration relationship.
4. Load the exact immutable configuration revision.
5. Validate schema version and typed component contract.
6. Resolve the component's adapter ID/version through the code-controlled registry.
7. Resolve allowlisted secret references.
8. Validate endpoint/model availability and required compliance status.
9. Construct the immutable participant instance with exact provenance.
10. Authorize and admit the invocation before calling the adapter.

Any failure stops the sequence with an actionable error. No fallback to global TOML, another configuration revision, adapter, endpoint, model, or policy is allowed for a Registry-bound workspace.

## 9. Required P3.1/P3.2 tests

- Schema-1 definitions remain readable/editable but cannot execute by default.
- Schema-2 valid model and verifier components validate.
- Unknown component, component version, adapter, adapter version, or setting is rejected.
- Secret references reject malformed, missing, empty, and non-allowlisted variables; resolved values are redacted from all observable surfaces.
- Exact immutable workspace revision determines provider/model/settings and effective configuration behavior.
- Two different revisions produce the corresponding different participant bindings.
- Archived/stale revision, inactive workspace, mismatched project/workspace, and invalid relationship are rejected.
- Unavailable endpoint and unknown availability are distinct outcomes.
- No Registry-bound failure falls back to the global TOML assistant.
- Legacy non-Registry callers continue to use the existing TOML-backed assistant path.

## 10. Decisions requested

Approval is requested for these architectural constraints, not for implementation:

1. Schema 1 remains readable but non-executable by default; schema 2 is required for runnable typed components.
2. The initial secret resolver supports allowlisted environment-variable references only.
3. Registry-bound runtime binding has no global TOML fallback; legacy TOML behavior remains separate for non-Registry callers.
4. The default second production participant is a bounded deterministic verifier, not a second model.
5. If Phase 4 requires independent model judgment, two independently addressable model endpoints are required.
6. Cancellation is described as cooperative/bounded until transport-level cancellation is actually implemented and tested.
7. Participant identity uses stable integration identity plus immutable revision-specific participant instance identity.

No application code, migrations, API behavior, or services should change until the user explicitly approves the contract and authorizes implementation.
