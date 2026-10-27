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
- **Next:** Clarify the most frustrating concrete failure in current coding-agent use, then define the smallest daily workflow that would solve it before reviewing prior projects for relevant evidence.

## Current next actions

- [ ] Clarify the most frustrating concrete coding-agent failure and the desired behavior instead.
- [ ] Define the smallest daily workflow that makes Evo 4 worth opening.
- [ ] Decide how the personal-memory and coding-agent use cases relate in the first usable version.
- [ ] Define explicit non-goals and a scope ceiling before drafting architecture.
- [ ] Inspect Evo and Evo 3 repository structure, implementation, tests, and history.
- [ ] Inspect Nemoxiom, Omega, Cyberdeck, and other potentially relevant projects.
- [ ] Record reusable components separately from ideas that only existed in plans.
- [ ] Identify recurring failure modes, scope drift, and verification gaps.
- [ ] Review the archaeology synthesis with the user before establishing core requirements.
