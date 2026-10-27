# Evo 4 Working Notes

This is the durable notebook for the Evo 4 design process. Update it after each meaningful discussion or research pass, not just at the end of a milestone.

## Ground rules for preserving context

1. Capture decisions, constraints, rationale, rejected approaches, unresolved questions, and next actions.
2. Label the status of statements: **Decision**, **Current hypothesis**, **Open question**, **Rejected**, or **Verified finding**.
3. Link related entries in [the decision register](DECISIONS.md) and [the archaeology index](ARCHAEOLOGY.md).
4. Keep old decisions in the record when they change. Mark them superseded and link the replacement rather than silently rewriting history.
5. Separate what the user wants from what a repository currently implements.
6. Never turn an assumption into a requirement without checking it with the user or recording it explicitly as a hypothesis.
7. When new evidence contradicts a note, update the current summary and preserve the correction trail.

## Current project framing

**Status: Working hypothesis — confirm as discovery proceeds.**

Evo 4 starts with software archaeology and design, using the user's existing repositories and project history to identify durable goals, proven components, recurring failure modes, and lessons before committing to an architecture.

The purpose is not to automatically combine every old project or assume Evo 4 is simply Evo 3 with more features.

## User constraints and preferences known so far

These are starting context, not a substitute for validating requirements during discovery.

- The user wants blunt, evidence-based critique rather than cheerleading.
- Important project decisions must not get lost across conversations or sessions.
- The design should distinguish intended capabilities from implemented and verified behavior.
- The user has a high bar for software quality and is wary of releasing insecure, vibe-coded software publicly; personal-use software is an acceptable outcome.
- Prior work has explored local and online models, agents, persistent memory, experimentation, and an integrated AI workstation. Treat this as prior-art context, not yet the final Evo 4 scope.

## Session log

### 2026-10-27 — Notebook established

- **Decision:** Keep durable project notes in this repository throughout the design process.
- **Decision:** Maintain separate working notes, decision register, and prior-art archaeology index.
- **Decision:** Preserve rationale and decision history; mark superseded decisions rather than erasing them.
- **Open question:** What is Evo 4's primary job, and what must it deliberately *not* become?
- **Open question:** Which earlier projects and branches contain useful evidence, and which claims are actually implemented/tested?
- **Next:** Inspect prior repositories and histories; build an evidence-backed synthesis before proposing a final architecture.

## Current next actions

- [ ] Inspect Evo and Evo 3 repository structure, implementation, tests, and history.
- [ ] Inspect Nemoxiom, Omega, Cyberdeck, and other potentially relevant projects.
- [ ] Record reusable components separately from ideas that only existed in plans.
- [ ] Identify recurring failure modes, scope drift, and verification gaps.
- [ ] Review the archaeology synthesis with the user before establishing core requirements.
