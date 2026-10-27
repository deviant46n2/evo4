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


## Expanded reconnaissance — 2026-10-27: AgentMemory and omitted project history

### AgentMemory is confirmed in EVO 3 history, but integration status changed over time

- **Direct repository evidence:** [EVO 3 commit 58d0abf](https://github.com/deviant46n2/evo-3/commit/58d0abfa1b0e45d0bec7f190d6684015667a2f65) describes initial AgentMemory MCP wiring and memory-inspection scripts. [Commit 72b2431](https://github.com/deviant46n2/evo-3/commit/72b24319c916605e68e65fba1efe1342b0f48ebb) describes a cockpit memory tab with counts, recent memories, ranked search, and viewer link; it explicitly says the viewer's CSP prevents embedding, so the UI uses a link and server-side health instead.
- [Commit a727149](https://github.com/deviant46n2/evo-3/commit/a72714987c88b13137ffbb637212d4e98c70ef17) describes driver-side durable memory: revision-scoped records, idempotency ledger, prior-memory recall, best-effort failure behavior, and unit tests against a fake daemon. [Commit 175759b](https://github.com/deviant46n2/evo-3/commit/175759b230497778f754aeb28b919dd96297afbb) adds a live end-to-end proof exercising write, retrieval, contradictory results, and cleanup against the real daemon.
- **Important contradictory / later-state evidence:** [Commit 9fb5955](https://github.com/deviant46n2/evo-3/commit/9fb5955051ba08df27ef7eb9b2d81ca578456f73) explicitly says AgentMemory was not actually wired into the runtime despite the daemon being healthy. [Commit 87bfdd6](https://github.com/deviant46n2/evo-3/commit/87bfdd68ffa68e3d68ccd58e1bb450bf98528b2a) notes unresolved runtime/memory activation issues at that point. Later [commit 0c12176](https://github.com/deviant46n2/evo-3/commit/0c12176f1bb985c811c75f3e506a0c676a82c7fb) records inventory of live AgentMemory counts and other checks. These commit descriptions are evidence of project history, not a fresh checkout/test run in this session.
- **Lesson:** Never summarize “AgentMemory integrated” as a timeless binary. The record must be revision- and path-specific: configured, service healthy, MCP reachable, runtime actually invoking it, memory persisted, recall effective, and end-to-end behavior tested are distinct statuses.
- **Current follow-up:** Inspect the current EVO 3 HEAD, the named commits' diffs/tests, and the exact NEMOXIOM end-of-development timeline. Search commit messages and branches in addition to default-branch code search.

### Broader account inventory and review omissions

A GitHub repository inventory returned 16 repositories owned by the user: Astro-Delve, Dashboi, ModCanvas, cyberdeck, hydria, hydria-fork, aihands, omega, combatfactorygame, openhuman-dash, evo, minemind, Nemoxiom, evo-3, Mediarium, evo4. The current review queue had omitted **openhuman-dash, hydria, hydria-fork, minemind, Dashboi, ModCanvas, Astro-Delve, Mediarium, and combatfactorygame**. This inventory alone does not establish relevance; inspect repository metadata/README/branches and use prior conversation context to triage before deciding a project is irrelevant.

### Recovered conversation-level candidates (not yet proof of the exact forgotten choice)

- **OpenViking:** On 2026-10-14 the user explicitly considered it for persistent memory alongside OpenCode or Pi. Earlier, OpenViking, Mem0, and Letta appeared in memory/context-engine discussions.
- **AgentMemory:** On 2026-10-15 the user discussed reusing its web UI and memory integration in EVO 3. This is the strongest currently evidenced candidate for a memory foundation, but the exact “abandon NEMOXIOM and use this instead” decision has not yet been found.
- **Odysseus / Open WebUI / LibreChat:** On 2026-10-27 these were compared as broader self-hosted AI workspace starting points; Odysseus was recommended as a cockpit. This appears to be a later, broader workspace decision and must not be conflated with the earlier memory-foundation choice.
- **Hindsight:** Part of the 2026-10-27 Odysseus setup/testing plan; exact intended role relative to AgentMemory/OpenViking remains unresolved.
- **OpenHands:** Previously mentioned as an agent UI to reuse; relevance is primarily agent/interface precedent, not confirmed memory foundation.
- **OpenCode and Pi:** On 2026-10-14 a clean break from EVO was discussed using one as the coding-agent runtime and OpenViking for memory.
- **Omega runtime alternatives:** On 2026-10-24 the user considered Local LLM Foundry, Llama GUI, and llama.cpp Server Manager instead of rebuilding runtime management. Adjacent prior-art thread, not necessarily related to NEMOXIOM's abandonment.

### Search coverage failure recorded

A previous attempt searched a small set of exact terms in default-branch indexed files for NEMOXIOM and EVO 3, then treated the absence of results as a weak signal. It did not inspect commit history broadly, all branches, all user-owned repositories, or the conversation interval surrounding the decision. The query set was too narrow and the search boundary was not made visible. Do not call that a comprehensive search.

## External memory-software landscape rescan (2026-10-27)

This is a first-pass source/README sweep, not a runtime audit. Feature claims below are project documentation unless explicitly noted. The current goal is a single continuity layer across user preferences, conversations, project decisions, coding sessions, active task state, evidence/provenance, corrections, and resumable handoffs.

### Highest-priority candidates

1. **AgentMemory — https://github.com/rohitg00/agentmemory**
   - Current README now describes a much broader system than the version discussed in EVO 3 on 2026-10-15: native hooks/plugins for many coding agents, one shared store, local file-backed persistence, inspect/edit/export/forget viewer, hybrid BM25/vector/graph retrieval, session history, project profiles, lessons, handoffs, audit, version chains, provenance verification, action tracking (dependencies/frontier/next action), checkpoints, and multi-agent coordination tools. It also supports OpenAI-compatible local endpoints such as llama.cpp and local embeddings.
   - Repo README currently claims 54 MCP tools, 12 hooks, 4,000+ passing tests, 95.2% retrieval R@5 and zero external DB services; these are upstream claims, not independently reproduced here.
   - Strongest fit for the *coding-agent continuity* half. Remaining fit questions: how well it stores broad personal/non-coding conversation context; whether all required sources (ChatGPT history, arbitrary documents, repos, branch/commit history) are ingested reliably; whether evidence/source lineage is exposed in useful end-user workflows; whether task/action state remains coherent under corrections and interruptions; and whether its many features are robust in our actual OpenCode/llama.cpp setup.
   - Important operational caveat: the repository documents separate keyless BM25 mode vs optional local embeddings and optional LLM-backed compression. These are distinct configurations. Verify live runtime/capture/retrieval, not just service health or MCP visibility.
   - Changelog states recent work on persistent inbox/offline spooling, force-kill recovery, default API auth, bounded provenance/audit/index storage, and release gates. This is promising reliability work but should be checked against the exact version installed.
   - Evidence: README https://github.com/rohitg00/agentmemory; changelog https://github.com/rohitg00/agentmemory/blob/main/CHANGELOG.md; local model configuration is documented in README.

2. **MemSearch — https://github.com/zilliztech/memsearch**
   - Newly surfaced, unusually close competitor for coding continuity. Markdown files are the source of truth, with Milvus used as a rebuildable search index. It supports OpenCode, Codex, Claude Code, OpenClaw, and DeepSeek Harness; automatic session capture, progressive retrieval from search to expanded note to transcript, hybrid dense/BM25 retrieval, and optional skills distilled from repeated workflows.
   - Optional maintenance creates a durable `.memsearch/PROJECT.md` for active threads/decisions/risks/next steps and `.memsearch/USER.md` for preferences/working style/goals. These tasks are off by default. Pending work resume is explicitly advertised for OpenCode.
   - Stronger than AgentMemory on the simplicity and inspectability of Markdown-first memory and the explicit user/project summary split. Potentially weaker on structured graph/provenance/audit and action lifecycle. Milvus/index and summarization provider configuration add moving parts; validate local/offline defaults and exact model calls.
   - Evidence: https://github.com/zilliztech/memsearch and https://github.com/zilliztech/memsearch/blob/main/docs/home/configuration.md.

3. **TencentDB Agent Memory — https://github.com/TencentCloud/TencentDB-Agent-Memory**
   - Newly surfaced, broader “memory hub” design with four reusable assets: raw chat/conversation (L0), extracted facts/preferences/events (L1), project/scenario context (L2), and stable user/team profile (L3). Also builds Wiki and CodeGraph assets from documents and source code, and provides a shared hub/proxy with user/team/agent/visibility access controls.
   - Conceptually very close to a cross-project continuity layer and potentially a way to combine conversations, profile, skills, docs, and code understanding. It is a larger service stack (Memory Core, Memory Hub, Proxy; current docs require Node >=22.16 and two sets of LLM parameters). MongoDB backend is described as experimental. Not yet established as suitable for one local user, local OpenAI-compatible inference, or arbitrary personal-chat imports.
   - Evidence: https://github.com/TencentCloud/TencentDB-Agent-Memory and its README/API docs.

4. **OpenViking — https://github.com/volcengine/OpenViking**
   - Context database with an inspectable virtual filesystem for resources, memories, and skills; directory summaries at multiple levels; scoped retrieval; committed sessions archived as readable/editable Markdown; optional compilation into Wiki, graph, or report.
   - Strong candidate for transparent organization of *all* context (not only extracted memory facts). It is a context database/framework rather than a ready-to-use unified personal assistant. Need check runtime footprint, local model/provider requirements, capture adapters, and whether temporal conflicts/provenance are first-class.
   - Evidence: https://github.com/volcengine/OpenViking.

5. **Hindsight — https://github.com/vectorize-io/hindsight**
   - Memory engine focused on learning/reflecting rather than simple retrieval, with retain/recall/reflect operations, observations, mental models/knowledge pages, memory banks, coding-agent integrations, MCP, and local/OpenAI-compatible LLM provider support. The project reports strong LongMemEval results; upstream benchmark claims should be independently checked and may depend on model/config.
   - Good candidate for evolving beliefs, relationships, and learning from history. More infrastructure and operational weight than a simple local store; does not by itself provide the full chat/coding cockpit or durable task-execution harness.
   - Evidence: https://github.com/vectorize-io/hindsight.

### Specialized candidates / components, not complete solutions

- **Graphiti — https://github.com/getzep/graphiti**: temporal context-graph framework with validity windows, raw episodes as provenance, and hybrid semantic/keyword/graph retrieval. Particularly relevant to source-linked history and “what was true when?” It explicitly requires building the surrounding service, ingestion, access control, and operations.
- **Mem0 — https://github.com/mem0ai/mem0**: broad personalization memory and entity/time-aware retrieval; promising for user preferences, but less obviously a coding-session/task-state system. README states some headline benchmarks are from its managed platform, not identical OSS performance.
- **Always On Memory Agent — https://github.com/Shubhamsaboo/always-on-memory-agent** (also documented in GoogleCloudPlatform/generative-ai sample): simple MIT reference using SQLite, a file/API inbox, periodic LLM consolidation, query API and Streamlit dashboard, including source-cited answers. It is small and conceptually interesting, but documented as a sample tied to Google ADK/Gemini, not a proven shared cross-agent memory platform; no strong evidence yet for lifecycle/audit/temporal guarantees.
- **Letta — https://github.com/letta-ai/letta-code**: full stateful agent runtime with memory, but greater runtime/framework commitment. Evaluate as an integrated assistant/agent alternative rather than a drop-in memory database.

### Initial fit matrix (hypotheses, not test results)

| Requirement | AgentMemory | MemSearch | TencentDB Agent Memory | OpenViking | Hindsight | Graphiti |
|---|---|---|---|---|---|---|
| Cross-coding-agent capture | Strong documented support | Strong documented support | Proxy/adapters for selected agents | Needs adapter/runtime check | Coding-agent integrations | Must build adapters |
| Personal profile + project state | Profile/project tools exist; test quality | Explicit USER.md + PROJECT.md | Explicit L3 profile + L2 scenario | Filesystem can organize both | Memory banks/mental models | Build schema/logic |
| Inspect/edit durable source | Live viewer/version chains | Markdown source of truth | Hub UI/assets; verify raw edit/history | Filesystem/Markdown inspection | UI/API; verify source editing | Graph + source episodes |
| Provenance/temporal corrections | Audit/version chains/graph verification advertised | Raw journals/transcripts + git-tracked notes | Raw L0 + layered memories; exact temporal semantics need testing | Session archives; temporal conflict handling unclear | Observations/reflect; verify provenance semantics | Strong explicit temporal provenance model |
| Task state/handoff | Actions, dependencies, frontier, next action, checkpoints | PROJECT.md, pending-work resume, handoff | Task/asset concepts, needs runtime validation | Session commits/context organization | Not a full execution harness | Not a full execution harness |
| Local model viability | Explicit OpenAI-compatible local endpoint | Provider-specific behavior needs test | LLM config/local endpoint compatibility unresolved | Check docs/runtime | Explicit local OpenAI-compatible providers | LLM/embedder configurable |
| Ready-to-use personal+coding assistant | Memory component, not whole assistant | Coding memory component | Memory hub, not full assistant | Context DB, not full assistant | Memory component | Framework component |

### Research decision

Do not choose based on README claims, star counts, or one leaderboard. Run the same small acceptance suite against AgentMemory and MemSearch first, then add TencentDB/OpenViking/Hindsight only where the first two fail or where a specific architectural advantage justifies the cost. The test suite should cover: (1) exact prior decision + date + source; (2) conflicting old/new preferences without erasing history; (3) current project/task state and next action after interruption; (4) user fact vs project fact isolation; (5) correction/forgetting; (6) local-only operation and resource use; (7) cross-agent capture and recall; (8) answer cites original evidence rather than only generated summaries.

Coverage boundary: this pass used public web search and GitHub repository/README/documentation inspection on 2026-10-27. It did not clone or execute candidates, independently reproduce benchmark claims, exhaust GitHub search, inspect every issue/PR/branch, or validate the full implementation. Treat this as a ranked shortlist, not proof that no other project exists.

### Additional adjacent discovery: OpenHuman

**OpenHuman — https://github.com/tinyhumansai/openhuman** is an early-beta desktop app plus Rust agent harness, advertised as a lightweight, efficient coding-agent runtime. AgentMemory now lists OpenHuman as a native Memory-trait backend, so this is a concrete integration path worth evaluating if Evo 4 eventually needs both a memory layer and a different agent runtime. It is not itself evidence of a general-purpose personal-chat memory solution, and its early-beta status means stability, platform support, and fit with our existing OpenCode/llama.cpp setup must be tested before considering adoption.


## Deep comparison and provisional selection — 2026-10-27

Scope: read current public READMEs/docs and inspect selected implementation files for AgentMemory, MemSearch, and TencentDB Agent Memory. This is still static inspection; none of the three was cloned, executed, or benchmarked in this pass.

### Provisional choice: MemSearch as the first foundation to adopt

Given the user's limited appetite for multi-system benchmarking, choose **MemSearch as the single first candidate to try**, not as a claim that it is universally superior. Its Markdown-first source of truth, progressive retrieval from summary to original transcript, explicit USER.md/PROJECT.md split, and documented OpenCode capture/recovery protocol best balance Evo 4's inspectability, continuity, and implementation burden. Its code/docs describe durable pending-turn handling, settled-turn checks, append/index recovery, and replay of missed capture work. See https://github.com/zilliztech/memsearch and https://github.com/zilliztech/memsearch/blob/main/docs/platforms/opencode/how-it-works.md.

### Comparative evidence

- **AgentMemory — broadest ready-made coding-memory feature set.** Static inspection of `src/state/schema.ts`, `src/index.ts`, `src/functions/actions.ts`, and `src/functions/remember.ts` shows distinct state scopes for sessions/observations, summaries, profiles, graph data, audit, actions/dependencies, checkpoints, capture inbox/events, and other subsystems. `actions.ts` creates actions with status/priority/project, source observation/memory IDs and dependency edges; it records an audit event. `remember.ts` validates inputs, normalizes project attribution, uses source observation IDs, and attempts near-duplicate detection. This is meaningful implementation evidence for structured task state and provenance links, not proof of end-to-end reliability. Architecture depends on iii-engine/iii-sdk and is substantially larger/more coupled than a Markdown journal. Current README's tool/test/benchmark counts are upstream claims and were not reproduced. URLs: https://github.com/rohitg00/agentmemory/blob/main/src/functions/actions.ts ; https://github.com/rohitg00/agentmemory/blob/main/src/functions/remember.ts ; https://github.com/rohitg00/agentmemory/blob/main/src/state/schema.ts.
- **MemSearch — strongest inspectability/recovery balance.** Markdown is the canonical memory and Milvus is a derived index. The OpenCode integration docs describe reading persisted host session tables, requiring settled assistant/tool turns, storing pending capture before inference, tracking append offsets/hashes, fsync, and recovering partial writes/indexing failures. It uses session anchors to link memory notes to original conversations and has a replay/recovery scan. The Python package does depend on Milvus Lite/PyMilvus and an embedding provider; local/offline behavior and actual model/provider calls still require verification. URLs: https://github.com/zilliztech/memsearch/blob/main/docs/platforms/opencode/how-it-works.md ; https://github.com/zilliztech/memsearch/blob/main/src/memsearch/store.py ; https://github.com/zilliztech/memsearch/blob/main/pyproject.toml.
- **TencentDB Agent Memory — richest explicit layered context model, heavier operational stack.** README and INSTALL.md describe L0 raw conversation, L1 extracted atoms, L2 scenario/project context, L3 stable profile; also skills, Wiki, CodeGraph, hub/proxy, and access scoping. Recommended install runs Memory Core + Memory Hub + Proxy, configures two LLM groups, and currently marks MongoDB storage experimental while SQLite is default. Strong conceptual fit for cross-domain profile/project memory but more infrastructure than needed for a first single-user trial. URLs: https://github.com/TencentCloud/TencentDB-Agent-Memory ; https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/main/INSTALL.md.

### Why not select AgentMemory first?

AgentMemory's richer action/audit/governance surface is attractive and may ultimately be a better choice if Evo 4's primary unmet need is structured work-state management. However, the user's EVO 3 history records that daemon health/MCP availability did not prove actual runtime integration. AgentMemory is also a large system built on an engine abstraction, increasing the potential debugging surface. This does not mean it is broken; it means the prior integration lesson and the user's limited appetite for extensive benchmarking should count in the choice.

### Non-negotiable limitation

None of these three has been established here as a reliable importer of the user's full ChatGPT history or as a complete personal assistant. MemSearch is primarily coding-agent memory. Its USER.md is a useful profile note, not a complete provenance-aware personal knowledge system. Evo 4 may still need a small, separate continuity contract for cross-source ingestion, source-linked claims, explicit corrections/temporal validity, and task state. Do not fork or rebuild the entire memory engine before trying the selected system.

### Minimal adoption gate (one system, not a 3–5-way benchmark)

1. Install MemSearch into a disposable/test OpenCode profile with a local-compatible configuration.
2. Capture a real session, restart/interrupt capture, and confirm the pending turn is recovered once without duplicate summary.
3. Ask for a known past decision and verify retrieval reaches the original transcript.
4. Correct a profile/project note and confirm the edit persists and is used in a new session.
5. Measure idle CPU/RAM/disk and confirm whether summarization/embeddings call any external service.
6. Explicitly test ChatGPT-history ingestion separately. If unsupported, record that as a boundary; do not pretend coding-session capture solves it.

If the first two gates fail, reconsider AgentMemory next. Avoid adding TencentDB unless Evo 4 specifically needs its multi-layer knowledge hub and accepts the service stack.

Evidence boundary: code/docs inspected through public GitHub on 2026-10-27. No code was executed, security audit performed, or benchmarks reproduced.

## Deep review #1 — NEMOXIOM code/test audit (2026-10-27, verified)

**Method:** Cloned `deviant46n2/Nemoxiom` to `~/Projects/Nemoxiom`, installed deps, executed the unit suite with `node --test 'tests/unit/*.test.ts'` — a fresh run, not a doc claim.

**Verified evidence:**
- 449 unit tests, 448 pass, 1 fail: `tests/unit/p3-audit.test.ts:78` reads a live experiment artifact from `/tmp/opencode/p3a-transcript.txt` that no longer exists. Entropy/refutable fixture baked into the suite — the test is correct in intent but unreproducible from a clean checkout. (Defect class: external-state dependency, matches the "verified vs not-reproducible" lesson we already logged.)
- HANDOFF.md claims Tier-1 442/442; growth to 449 since then is consistent with recorded history, count drifted but suite stayed green.
- **Monster finding:** NEMOXIOM is not graveyard. The running memory stack powering the user's current assistant (cap­ture plugin, fresh-memory-loop, opencode-mem) is built out of this repository's code. `sprint/archive-hardening` is on the remote (an earlier note in memory said "nothing pushed" — stale as of 2026-10-27). The highest-value prior art for Evo 4's continuity layer is the project that was assumed least-likely-relevant because it was "superseded."

**Failure mode / lesson for Evo 4:**
1. Our graveyard taxonomy was wrong at the "intent" level: Nemoxiom was recorded as abandoned; code+test evidence shows it is the live substrate. This is exactly the "claims drift from verified behavior" failure the notebook exists to catch.
2. One test defects (external /tmp fixture); cheap to fix in Evo 4 style: recon-dependent fixture must be generated by a prior test, never read from a global path.

**Evo 4 relevance (provisional, still assistant-level):**
- OCR-level modules are directly reusable primitives: `nemoxiom/archive.ts` (append-first hash-chained archive), `assemble.ts` (bounded context assembly), `capture.ts` (ordinary-work capture), `handoff.ts`, `recover.ts`, `ops.ts`. These map 1:1 onto MEMORY-ARCHITECTURE's Layer 1 (evidence archive) and Layer 4 (rebuildable indexes).
- Learning gap remains: Nemoxiom does capture/retrieval/provenance but does not close the "experience → lesson → behavior change → verify" loop. That is Evo 4's actual increment, not a new memory store.

**Next check (not done yet):** run the e2e persistence suite + read `nemoxiom/capture.ts` and `archive.ts` to record which guarantees are enforced vs merely assumed.

**Confidence/unknowns:** Suite executed this session on this machine = high confidence for the 448/449 number only. Behavioral claims (hash-chain integrity under concurrent writes etc.) are covered by tests but not separately audited — treat as "covered by tests," not "independently verified."
