# Evo 4: Learning Through Experience

Status: discovery note, 2026-10-27. This captures user intent and separates it from implementation choices.

## User-confirmed ambition

The user compares Evo 4's long-term development to Tony Stark developing JARVIS, EDITH, and even Ultron: a system that becomes more than the sum of its parts. It should learn meaningful lessons from experience and use them to shape future behavior, including communication style or “personality.” Initially, it should be broadly like ChatGPT, but become much more capable over time.

The user prefers that Evo adapt freely within boundaries the user establishes, rather than requiring approval for each individual lesson. The goal is practical improvement from experience: after ten games of chess, for example, Evo should have a better chance of winning game eleven because it learned from the prior games.

Examples the user gave:

- Learn a strategy for playing Magic: The Gathering together, then use lessons from previous games to play more effectively in future games.
- Understand a new project described as a synthesis of three existing projects, connecting the references to infer what the user means rather than treating each project in isolation.
- Develop a progressively richer understanding of the user's intent, preferences, and working style.

## Product interpretation — proposal, not an approved implementation

A plausible high-level loop is: experience → record evidence and outcome → derive candidate lessons → test whether a lesson is reliable and generalizes → apply it to future behavior → observe results → keep, revise, or roll back the lesson. This is a candidate design to discuss, not a settled architecture.

Memory alone does not satisfy the ambition. The system needs some way to turn experiences into reusable strategies and behavioral adaptations, while preserving the episodes that support them. For example, a chess or MTG lesson should be grounded in recorded game state, legal moves, decisions, and outcomes rather than the simplistic assumption that a winning move was always correct or a losing move always wrong. A cross-project inference should be checked against the user's intended connection.

The user wants adaptation to happen freely within user-established boundaries, with the ability to steer it. The precise boundaries, visibility, rollback, and approval rules remain open. This is not authorization for unrestricted autonomy, independent goal formation, or model-weight changes.

## User-confirmed boundary: self-modification

The user thinks Evo modifying its own code should initially be a human-in-the-loop procedure. This can be revisited later; it is a starting boundary, not necessarily a permanent prohibition.

Design implication to explore (proposal, not yet approved): distinguish ordinary learning/adaptation from changes to the system's own implementation. Initially, Evo may be able to propose code changes and gather test evidence, but a human should review and approve before those changes are activated. The exact sandboxing, test requirements, approval UX, rollback procedure, and whether any low-risk changes can be exempted remain undecided.

The user should be able to inspect the evidence and rationale behind learned lessons, steer how they affect behavior, correct mistaken conclusions, and observe whether changes actually improve results. Personality should be able to evolve in response to experience and user direction, without treating an unverified inference as fact.

## User-confirmed principle: evidence-proportional adaptation

The user expects Evo to choose between acting on a lesson immediately and testing it further depending on the evidence. The product should not impose a universal “always test first” or “always trust the latest lesson” rule.

Design interpretation (proposal, not a settled algorithm): adaptation should account for evidence strength, uncertainty, repeatability, plausible alternative explanations, observed effect on outcomes, and the risk or reversibility of the proposed change. A well-supported, low-risk lesson may be applied immediately; an uncertain lesson can remain a hypothesis and be tested; conflicting or weak evidence should not be promoted to reliable knowledge. High-impact changes need stronger safeguards regardless of the system's subjective confidence. Confidence alone is not evidence.

This principle concerns how Evo learns and adapts. It does not override the separately confirmed initial human-in-the-loop boundary for modifying Evo's own code.

## User-confirmed principle: self-directed learning with a user-controlled stop

The user is strongly in favor of Evo learning and researching on its own, without requiring the user to assign every learning task. They specifically want a switch that stops this activity when they need their PC resources.

Confirmed intent:
- Evo may initiate its own learning and research.
- The user needs a direct, dependable way to stop that activity when PC resources are needed elsewhere.

Design implications to explore (proposals, not yet approved requirements):
- Make background autonomy explicitly controllable by the user, with a clear stop/pause control.
- Stopping should halt resource-consuming work promptly and preserve enough task state to resume later without losing progress or duplicating side effects.
- Consider separate controls for background work, local model inference, and full shutdown, so pausing autonomous work need not disable ordinary interactive use.
- Add configurable resource budgets or priority limits so Evo does not routinely make the PC unusable before the user intervenes.
- Expose current activity, rationale, resource use, and resumable progress so autonomy is inspectable.

The exact semantics of “stop,” whether active external actions must be cancelled or allowed to finish safely, how quickly resource use must fall, and which activities remain available after pausing are unresolved. Do not claim the stop control is reliable until tested under real workloads and interruption scenarios.

### Clarification: the stop control is primarily about reclaiming VRAM

The user clarified that the central concern is freeing GPU VRAM when needed, rather than indiscriminately stopping every Evo process. The correct behavior depends on the eventual architecture:
- Deterministic, lightweight services may remain running if their CPU/RAM overhead is acceptable.
- GPU-resident models or other VRAM-consuming components may need to unload or terminate.
- A full-off / VRAM-release switch is needed if Evo's normal memory operations depend on a resident model.
- The system should avoid making durable memory operations unnecessarily dependent on a running GPU model. Persistent memory and task state should survive model unload/shutdown and be available again afterward.

Architecture is not chosen yet. Future design should distinguish process shutdown, model unload, and full Evo shutdown, and measure actual VRAM release rather than assuming a process exit or UI status guarantees it. Deterministic services are acceptable to leave running only when their resource costs are tolerable.

## Unresolved; do not assume

- What are the boundaries within which adaptation may happen freely?
- How should evidence strength, uncertainty, repeatability, alternative explanations, outcome improvement, and risk be operationalized when deciding whether to apply or test a lesson?
- How do we evaluate whether a lesson is correct and generalizes beyond one episode?
- How should Evo detect regressions, overfitting, false patterns, and harmful drift?
- What boundaries should govern self-directed research and learning beyond the confirmed need for a user-controlled stop?
- What exact behavior should the stop/pause control guarantee, including interruption latency, safe cancellation, preservation of task state, residual resource use, and verifiable VRAM release?
- Which components can operate without a resident model, and what CPU/RAM overhead is acceptable for deterministic services left running?
- What degree of initiative or autonomy is desired outside the confirmed initial human-approval gate for code self-modification?
- What evidence and safeguards should be required before a proposed code change is approved or activated?
- Does “learning” eventually include training or changing model weights, or should we first focus on persistent knowledge, strategies, tools, and policies? No choice has been made.
- The fictional JARVIS/EDITH/Ultron analogy expresses ambition; it is not itself approval for unrestricted self-modification or autonomous goal formation.

## Next discovery question

Clarify which non-code changes Evo may make automatically (for example, strategies, communication style, workflows, and tools), and which changes need review. The initial human-in-the-loop boundary for self-modifying code is confirmed; its concrete safeguards are not.