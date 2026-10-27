# Evo 4 Working Notes

This is the durable notebook for the Evo 4 design process. Update it after each meaningful discussion or research pass, not just at the end of a milestone.

## Ground rules for preserving context

1. Capture decisions, constraints, rationale, rejected approaches, unresolved questions, and next actions.
2. Label the status of statements: **Decision**, **Current hypothesis**, **Open question**, **Rejected**, or **Verified finding**.
3. Link related entries in [the decision register](DECISIONS.md) and [the archaeology index](ARCHAEOLOGY.md).
4. Keep old decisions in the record when they change. Mark superseded decisions and link the replacement rather than silently rewriting history.
5. Separate what the user wants from what a repository currently implements.
6. Never turn an assumption into a requirement without checking it with the user or recording it explicitly as a hypothesis.
7. When new evidence contradicts a note, update the current summary and preserve the correction trail.

## Current project framing

**Status: Working hypothesis — confirm as discovery proceeds.**

Evo 4 starts with software archaeology and deliberate requirements discovery, using the user's existing repositories and project history to identify durable goals, proven components, recurring failure modes, and lessons before committing to an architecture.

The purpose is not to automatically combine every old project or assume Evo 4 is simply Evo 3 with more features.

**Guiding constraint (user-stated):** Nail down exactly what the user wants, build only that, and intentionally keep the scope small enough that Evo 4 becomes a tool they actually use daily. Daily usefulness and scope discipline outrank architectural ambition or feature count.

**Current product intent (user-stated, details unresolved):** Evo 4 should be a persistent-memory chatbot and coding agent. It should learn enough about the user over time to personalize recommendations (for example, movies they are likely to enjoy) and should help write code without repeatedly rereading the same files or rediscovering established project context. The common thread may be durable, retrievable knowledge that supports both personal assistance and coding work; this is a hypothesis about the shared foundation, not yet an architecture decision.

## User constraints and preferences known so far

These are starting context, not a substitute for validating requirements during discovery.

- The user wants blunt, evidence-based critique rather than cheerleading.
- Important project decisions must not get lost across conversations or sessions.
- The design should distinguish intended capabilities from implemented and verified behavior.
- The user has a high bar for software quality and is wary of releasing insecure, vibe-coded software publicly; personal-use software is an acceptable outcome.
- Prior work has explored local and online models, agents, persistent memory, experimentation, and an integrated AI workstation. Treat this as prior-art context, not yet the final Evo 4 scope.
- **Scope constraint:** Intentionally smallish; prioritize an immediately useful daily tool over a sprawling platform.
- **Scope constraint:** Define the desired user outcome and explicit exclusions before choosing architecture or adding features.
- **Desired behavior:** Retain useful personal context over time and use it to personalize assistance rather than treating every chat as isolated.
- **Desired behavior:** In coding work, preserve useful project understanding and decisions so the agent does not keep re-reading the same files or repeating discovery work unnecessarily. The exact failure cases and acceptable trade-offs remain to be clarified.
- **Newly clarified pain points (user-stated):** Loss of context between sessions; frustration with context-window constraints during long interactions; and unreliable tracking of changing structured state during our Magic: The Gathering game.
- **Design implication (not an architecture decision):** These are distinct reliability problems: (1) continuity across sessions, (2) selecting and maintaining relevant information under finite active context, and (3) tracking exact evolving state. A generic memory store alone should not be assumed to solve all three.
- **Technical reality:** Evo 4 cannot remove the underlying model's context-window limit merely by adding memory. It may reduce the practical impact by preserving durable knowledge, retrieving relevant information, and keeping exact state in structured records with validation where appropriate.

## Session log

### 2026-10-27 — Notebook established

- **Decision:** Keep durable project notes in this repository throughout the design process.
- **Decision:** Maintain separate working notes, decision register, and prior-art archaeology index.
- **Decision:** Preserve rationale and decision history; mark superseded decisions rather than erasing them.
- **Open question:** What is Evo 4's primary job, and what must it deliberately *not* become?
- **Open question:** Which earlier projects and branches contain useful evidence, and which claims are actually implemented/tested?

### 2026-10-27 — Scope and daily-use constraint

- **User-stated goal:** Nail down exactly what Evo 4 is for and build only that.
- **User-stated constraint:** Keep the scope intentionally smallish so it becomes something the user can use daily.
- **Design implication:** Requirements discovery comes before architecture. Every candidate feature must justify itself against the primary daily-use job.
- **Not yet decided:** The exact daily workflow, priority between use cases, target interaction model, must-have capabilities, and explicit non-goals.

### 2026-10-27 — Initial product intent

- **User-stated product intent:** A persistent-memory chatbot and coding agent.
- **Personal-assistant example:** Recommend movies the user is likely to enjoy because it knows the user well enough.
- **Coding-agent pain point:** The agent should code without repeatedly rereading the same files (the user described having to reread a file many times) and should retain useful context about the codebase and prior work.
- **Current hypothesis:** Durable knowledge may be a shared foundation for both personal memory and coding context, but we have not decided whether they should share the same memory model or how to implement it.
- **Important boundary:** These are two stated use cases, not permission to expand immediately into a general AI operating system, autonomous multi-agent platform, or all-in-one workstation.
- **Open questions:** What makes memory genuinely useful and trustworthy? What exact coding-agent behavior is currently wasteful? Which of these should define the first minimum usable version?

### 2026-10-27 — Context continuity and state-tracking failures

- **User-stated pain:** Session-to-session context loss and context-window limits are major frustrations.
- **Concrete example:** The user points to my unreliable tracking of our Magic: The Gathering game as an example of failing to maintain state across a multi-turn activity.
- **Problem distinction:** Durable personal/project memory, active-context management, and exact tracking of changing structured state are related but separate requirements.
- **Constraint:** Do not promise to abolish context windows. The product goal is to reduce how often limits disrupt the user's work and to make continuation more reliable through externalized, retrievable knowledge and explicit state where useful.
- **User priority clarification:** The user chose **D — all three are inseparable**: persistent personal memory, coding continuity, and reliable state tracking are aspects of one desired continuity experience, not separate products.
- **Product-level interpretation:** The assistant should maintain continuity across people/preferences, projects/tasks, and evolving activity state. These may still need different underlying representations and validation rules; unified experience does not imply one undifferentiated memory store.
- **Scope caution:** Treat this as one product goal, not a requirement to implement every use case at full depth in the first release. The next task is to identify the smallest workflow that demonstrates continuity end to end.
- **Next:** Ask for the user's ideal continuity experience in a concrete situation, then define observable success criteria and exclusions.



### 2026-10-27 — Persistent starting context / compact orientation

- **User-stated minimum requirement:** At the start of any request, Evo 4 should have a compressed understanding of itself and its capabilities, plus the basics of the user's projects and interests.
- **Desired effect:** The assistant should already be oriented well enough to begin a broad range of requests without making the user reintroduce themselves, explain their general interests, or re-establish basic project context.
- **Current product hypothesis:** Use a compact, persistent **starting context** as a launchpad, then retrieve deeper, task-specific records when relevant. The launchpad is not the entire memory and should not try to contain every detail.
- **Candidate contents (not yet a finalized schema):**
  1. **Self-knowledge:** Evo 4's identity/purpose, available tools and model connections, known capabilities and limitations, and a distinction between capabilities that are configured, currently available, and actually verified.
  2. **User/project orientation:** Compressed interests and preferences; active projects and their goals/status; important decisions and constraints; pointers to authoritative detailed records.
  3. **Request-specific context:** Retrieve the details relevant to the current request instead of indiscriminately loading the full archive.
- **Trust requirement / design implication:** Self-knowledge must not become aspirational marketing or stale claims. It should represent capability status honestly and have a way to verify dynamic availability. Project summaries should point to deeper sources so compressed context does not become the sole source of truth.
- **Acceptance-test direction:** In a fresh conversation, Evo 4 should be able to begin a personal-interest request and a project request with appropriate orientation, then retrieve relevant detail without asking the user to repeat basic context. Exact tests and success thresholds remain open.
- **Scope guard:** This is a minimum continuity foundation, not yet permission to build a fully autonomous agent, ingest everything, or implement every past project idea.
- **Next discovery step:** Define what the starting context must reliably contain, how it stays current and correctable, and what behavior demonstrates that it is useful across different request types.


### 2026-10-27 — Starting context must be updatable

- **User-stated requirement:** The persistent starting context must be updatable; it should not be a static profile that the user has to maintain manually.
- **Design implication:** Evo 4 should be able to incorporate new information about the user's interests, projects, goals, decisions, and its own capabilities into the appropriate durable records, and refresh compressed summaries/pointers accordingly.
- **Reliability constraint:** Learning new information and committing a fact as authoritative are not always the same action. The system should distinguish explicit user statements and verified observations from inferred preferences or uncertain interpretations.
- **Conflict-handling requirement (proposed):** When new information conflicts with existing context, reconcile it explicitly. Respect a clear revised user decision while preserving decision history where useful; do not silently convert an uncertain inference into a confirmed fact.
- **Open questions:** Which updates can be automatic, which require confirmation, how the user inspects/corrects/withdraws a memory, and how the system handles stale or conflicting project/capability records.


### 2026-10-27 — Scientific, evidence-led behavior and validation

- **User-stated quality requirement:** Evo 4 should be scientific: never guess an output; review and validate it.
- **Interpretation to confirm through examples:** Treat evidence and validation as first-class parts of the system, not optional polish. Do not present an unverified output as correct or a guess as an established fact.
- **Evidence discipline:** Distinguish direct observations, explicit user statements, source-backed facts, inferences, hypotheses, and unknowns. Keep provenance for important claims and durable memories.
- **Validation discipline:** Before claiming an output is ready/correct, check it against suitable criteria. The validation method depends on the output: e.g. run tests and inspect diffs for code; check calculations independently; compare factual claims against reliable sources; reconcile state transitions against explicit game rules and recorded state.
- **Failure behavior:** If validation is unavailable, incomplete, fails, or is inconclusive, report that status plainly and identify what remains unverified. Do not invent a successful test, hide a failed check, or silently fill evidence gaps with assumptions.
- **Correction discipline:** Preserve enough provenance and change history to explain why important records or conclusions were revised.
- **Practical limitation:** No model can guarantee that it never internally generates a guess or that every validation method is infallible. The achievable requirement is that guesses are not silently promoted to facts and outputs are not represented as validated unless appropriate checks actually occurred. Validation itself should be reviewable and its limitations visible.
- **Open questions:** What evidence threshold applies to different output classes; which checks must be automated; when human confirmation is required; and how to keep verification proportionate so a small daily-use tool does not become unusably slow.


### 2026-10-27 — Real-time conversation while background work continues

- **User-stated hard requirement:** The user must be able to talk to Evo 4 in real time and have it spawn a subagent to answer regardless of what other work Evo 4 is doing.
- **User-stated rationale:** Conversation will be a major source of Evo 4's memory; it must not become unavailable or blocked behind long-running tasks.
- **Product requirement:** Interactive conversation must remain responsive while coding, research, or other background tasks run. A user question must not require waiting for the current task to finish.
- **Candidate behavior:** A conversational agent can answer, report task status, discuss a new request, and help redirect work while background workers continue independently. Access to shared context should not imply shared mutable execution state.
- **Engineering implication:** Merely supporting subagents is insufficient if all model/inference capacity can be saturated by background work. Explore reserved or independently schedulable interactive inference capacity, queue priorities, cancellation/interrupt semantics, and graceful degradation. Exact implementation remains undecided and must be evaluated against the user's hardware/cost constraints.
- **Memory implication:** Conversations are a primary source of durable information: explicit preferences, project decisions, corrections, requirements, and ongoing context. The system should capture candidate memories without blocking the live conversation, while preserving provenance and the evidence/validation standards in D-009.
- **Open questions:** What latency qualifies as real-time; whether the conversational agent may issue control actions or only recommend them; how to prioritize memory extraction; and how the system behaves when all inference resources are genuinely exhausted.
- **Scope guard:** This is a hard interaction requirement, not yet a commitment to a broad multi-agent platform. The smallest implementation that keeps chat responsive during one meaningful background task should be investigated first.


### 2026-10-27 — Clarification: interruption and safe resumption are acceptable

- **User clarification to D-010:** It is acceptable for the user to interrupt a running task, receive an answer, and then have Evo 4 return to the original work. A permanently separate conversational agent is not necessarily required if interruption/resumption works reliably.
- **Refined hard requirement:** The user can ask a question or issue an interruption while work is underway; Evo 4 responds promptly, then resumes the original task from a recoverable point without losing progress or silently changing the task.
- **State correctness requirement:** Resumption must use recorded task state (completed steps, current step/checkpoint, relevant files or artifacts changed, outstanding work, and validation status), not rely solely on the model reconstructing its activity from conversational memory.
- **Safety/consistency implication:** Before resuming, detect whether the interruption or external changes invalidated assumptions or prior checks. Revalidate affected work where necessary; do not blindly continue from a stale checkpoint.
- **Architecture flexibility:** A separate always-on conversational worker remains one possible implementation, but is not itself a requirement. Reliable interruption, response, and resumption is the user-facing requirement.
- **Still open:** Expected response latency; which operations can be safely paused; how to handle non-interruptible actions; and what progress/checkpoint detail is necessary for reliable recovery.

## Current next actions

- [ ] Specify the minimum persistent starting context: self-knowledge, compressed user/project orientation, and pointers to deeper records.
- [ ] Define responsive conversation during background work: latency target, worker visibility/control, inference-resource isolation, and degraded-mode behavior.
- [ ] Define how conversation-derived memories are captured and validated without blocking interactive replies.
- [ ] Define how starting context is updated, corrected, verified, and kept from going stale.
- [ ] Define acceptance tests across a personal-interest request, a coding/project request, and a task with evolving state.
- [ ] Identify the smallest daily workflow that demonstrates continuity across request types, plus explicit exclusions.
- [ ] Decide how the personal-memory and coding-agent use cases relate in the first usable version.
- [ ] Define explicit non-goals and a scope ceiling before drafting architecture.
- [ ] Inspect Evo and Evo 3 repository structure, implementation, tests, and history.
- [ ] Inspect Nemoxiom, Omega, Cyberdeck, and other potentially relevant projects.
- [ ] Record reusable components separately from ideas that only existed in plans.
- [ ] Identify recurring failure modes, scope drift, and verification gaps.
- [ ] Review the archaeology synthesis with the user before establishing core requirements.
