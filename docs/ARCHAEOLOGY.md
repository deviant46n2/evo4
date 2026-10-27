# Prior-Art Archaeology Index

Track each earlier project as evidence, not as an automatic source of requirements. Findings should cite repository paths, commits, tests, or concrete behavior whenever possible.

## Evidence levels

- **Intent:** README, design docs, issues, plans, or comments describe the goal.
- **Implemented:** Code exists that appears to implement the capability.
- **Tested:** Tests exercise the relevant behavior; record what they do and do not establish.
- **Verified:** Behavior has been directly run or otherwise confirmed in a relevant environment.
- **Unknown:** Evidence is missing, contradictory, or has not yet been inspected.

Do not describe a project-level capability as verified merely because its README claims it.

## Project review queue

| Project | Initial relevance hypothesis | Status |
|---|---|---|
| [evo](https://github.com/deviant46n2/evo) | Early goals, architecture, autonomy boundaries, and lessons from the first iteration | Initial documentary reconnaissance; code/test audit pending |
| [evo-3](https://github.com/deviant46n2/evo-3) | Experiment workflow, model improvement without weight training, memory, evaluation, and practical constraints | Initial documentary reconnaissance; code/test audit pending |
| [Nemoxiom](https://github.com/deviant46n2/Nemoxiom) | Trustworthy continuity, provenance, archive-first state, and inspectable memory | Initial documentary reconnaissance; code/test audit pending |
| [omega](https://github.com/deviant46n2/omega) | AI workstation/runtime integration and local/online model workflows | Repository discovered; content/path review pending |
| [cyberdeck](https://github.com/deviant46n2/cyberdeck) | Integrated operator experience, existing-tool integration, and interface boundaries | Initial documentary reconnaissance; code/test audit pending |

These are initial hypotheses based on project context; they are not findings about the current repository contents.

## Per-project report template

### Project name

- **Repository / revision reviewed:**
- **Original goal (intent evidence):**
- **What is implemented:**
- **What tests cover:**
- **What was directly verified:**
- **What appears unfinished or broken:**
- **Useful components or patterns:**
- **Failure modes / lessons:**
- **Dependencies and constraints:**
- **Potential relevance to Evo 4:**
- **Evidence links (paths, commits, tests):**
- **Confidence / unknowns:**


## Initial reconnaissance — 2026-10-27

**Scope of this pass:** Read selected README and design/experiment documents from the most obviously relevant repositories. This is documentary reconnaissance, not a full code review or fresh execution of tests. Statements below are attributed to repository documentation until code/tests are inspected and behavior is rerun.

### NEMOXIOM — strongest direct overlap with continuity and evidence discipline

- **Intent evidence:** `Nemoxiom/README.md`, `docs/THESIS.md`, `docs/FEASIBILITY.md`, `docs/EXPERIMENT.md`.
- **Documented design:** Append-only hash-chained archive, versioned working state, bounded context assembly, retrieval tools, provenance-linked claims, staged onboarding, discrepancy/audit signals, structured handoffs, recovery briefs, and a derived epistemic knowledge store.
- **Important honesty boundary:** The thesis explicitly says hash chaining protects against archive mutation, not false claims at write time; it disclaims production readiness and multi-agent coordination.
- **Documented experimental evidence:** `docs/EXPERIMENT.md` records an onboarding-v2 run as valid, with 26/31 quiz answers versus a 1/31 baseline, 28 knowledge records (26 marked verified, 2 unknown gaps), 28/28 verification pass, and no false-verified literal in that run. The document also calls out a small n=1 ceiling and a missed test-runner detail. These are recorded experiment results, not independently rerun in this reconnaissance.
- **Potential relevance:** High. Directly aligned with persistent context, provenance, explicit unknowns, reviewable state, and bounded context. Likely the first project to inspect deeply.
- **Unknown until code/test review:** Whether these guarantees hold across failure/restart, whether all important writes are provenance-safe, actual quality beyond the reported single-repo experiment, and what integration cost/limitations are.

### EVO 3 — strongest documented overlap with long-running work and observability

- **Intent/implementation claims:** `evo-3/README.md` describes a persistent loop, headless OpenCode runner, cockpit, event log, pause/resume/stop controls, memory viewer, and structured experiment records. It says the cockpit renders recorded events instead of recomputing state from several files.
- **Relevant caution:** `OVERNIGHT.md` explicitly marks an earlier run plan superseded and its frozen benchmark numbers stale; it says not to launch from that document. This is useful evidence of why plans and artifacts need explicit freshness/validity status.
- **Potential relevance:** High for task lifecycle, checkpoints/resume, event streams, cockpit state, and practical orchestration.
- **Unknown until code/test review:** Actual interruption semantics, whether resume recovers safely at each phase, event-log recovery behavior, and which tests cover the stated controls.

### EVO — strongest documented overlap with experimental integrity and authority boundaries

- **Intent/architecture evidence:** `evo/README.md`, `docs/PHILOSOPHY.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`.
- **Documented design:** Lab-owned immutable objective and resource authority; separate authorized/actual/requested resources; hash-chained evidence database; held-out evaluation separation; sandboxing; capability claims that start proposed and require lab-side verification; evaluation distinct from adoption; rollback and human controls.
- **Potential relevance:** High for evidence integrity, capability-status honesty, validation authority, and separating model claims from trusted checks.
- **Scope warning:** EVO's recursive self-improvement laboratory is a different product goal. Its machinery should only be reused if a small, concrete component directly serves Evo 4; do not inherit the lab/platform scope.
- **Unknown until code/test review:** Enforcement coverage, failure modes, security boundaries, and which claims have automated tests versus documentation only.

### Cyberdeck — integration-first principle and model/runtime awareness

- **Intent/design evidence:** `cyberdeck/README.md`, `DECISIONS.md`.
- **Documented principles:** Integrate existing tools through adapters before rebuilding them; CLI-first and testable APIs; model inventory/VRAM-fit awareness; backup before overwriting files; explicit separation of committed milestones from parked ideas.
- **Potential relevance:** Useful as a design lesson for keeping Evo 4 small and making self-knowledge grounded in actual tool/runtime status.
- **Scope warning:** Cyberdeck is a local model fleet manager/orchestration environment, not itself a continuity assistant.
- **Unknown until code/test review:** Which runtime-fit and adapter behaviors are tested and reliable enough to reuse.

### AIHands — objective computer-use verification and human takeover

- **Intent evidence:** `aihands/README.md`.
- **Documented principles:** Observe → act → observe → verify; model-agnostic computer-use interface; event stream; human takeover.
- **Potential relevance:** Strong conceptual match for Evo 4's evidence-first action verification and interruption principles.
- **Evidence limit:** Only the README was inspected in this pass. No implementation or tests have yet been reviewed; treat all capability claims as unverified.

### Omega — not yet reviewed

- The repository is present in the account inventory, but attempted README and architecture paths returned 404 in this pass. This is a retrieval/path issue, not evidence that the project has no relevant implementation. Inspect repository contents/branches before drawing conclusions.

### Preliminary ranking for deeper inspection

1. **NEMOXIOM** — memory, provenance, state, bounded context, staged onboarding, recovery.
2. **EVO 3** — resumable long-running work, lifecycle events, cockpit, experiment logging.
3. **EVO** — validation authority, resource boundaries, capability verification, evidence integrity.
4. **AIHands** — objective verification and human interruption/takeover.
5. **Cyberdeck** — scope discipline and integration-first architecture.
6. **Omega and remaining repositories** — discover contents and relevance rather than infer from names.

This is a review order, not a reuse decision. No implementation has been selected for Evo 4 at this stage.

## Cross-project synthesis

Do not fill this section with guesses. Add findings only after reviewing the projects.

### Repeated goals

_To be established from evidence._

### Repeated failure modes

_To be established from evidence._

### Reusable implementation

_To be established from code and tests._

### Ideas to retire or avoid

_To be established from evidence and user discussion._

### Questions for the user

_Add only questions whose answers materially affect design direction._
