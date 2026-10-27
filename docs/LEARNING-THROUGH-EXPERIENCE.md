# Evo 4: Learning Through Experience

Status: discovery note, 2026-10-27. This captures user intent and separates it from implementation choices.

## User-confirmed ambition

The user compares Evo 4's long-term development to Tony Stark developing JARVIS, EDITH, and even Ultron: a system that becomes more than the sum of its parts. It should learn meaningful lessons from experience and use them to shape future behavior, including communication style or “personality.” Initially, it should be broadly like ChatGPT, but become much more capable over time.

Examples the user gave:

- Learn a strategy for playing Magic: The Gathering together, then use lessons from previous games to play more effectively in future games.
- Understand a new project described as a synthesis of three existing projects, connecting the references to infer what the user means rather than treating each project in isolation.
- Develop a progressively richer understanding of the user's intent, preferences, and working style.

## Product interpretation — proposal, not an approved implementation

A plausible high-level loop is: experience → record evidence and outcome → derive candidate lessons → test whether a lesson is reliable and generalizes → apply it to future behavior → observe results → keep, revise, or roll back the lesson. This is a candidate design to discuss, not a settled architecture.

Memory alone does not satisfy the ambition. The system needs some way to turn experiences into reusable strategies and behavioral adaptations, while preserving the episodes that support them. For example, an MTG lesson should be grounded in recorded game state, legal moves, decisions, and outcomes rather than the simplistic assumption that a winning move was always correct or a losing move always wrong. A cross-project inference should be checked against the user's intended connection.

The user should be able to inspect the evidence and rationale behind learned lessons, steer how they affect behavior, correct mistaken conclusions, and observe whether changes actually improve results. The personality should be able to evolve in response to experience and user direction, without treating an unverified inference as fact.

## Unresolved; do not assume

- What can be learned automatically and what requires approval?
- How do we evaluate whether a lesson is correct and generalizes beyond one episode?
- How should Evo detect regressions, overfitting, false patterns, and harmful drift?
- What degree of initiative or autonomy is desired?
- Does “learning” eventually include training or changing model weights, or should we first focus on persistent knowledge, strategies, tools, and policies? No choice has been made.
- The fictional JARVIS/EDITH/Ultron analogy expresses ambition; it is not itself approval for unrestricted self-modification or autonomous goal formation.

## Next discovery question

Define the desired balance between automatic adaptation and user control. This should be discussed behaviorally, with examples, before choosing technical mechanisms.