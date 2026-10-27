# Evo 4 Product Discovery Log

Status: active discovery; no substantial implementation authorized yet.

## D-001 — Product identity (user-confirmed, 2026-10-27)

The user wants Evo 4 to eventually replace both ChatGPT and OpenCode as their primary AI workspace. It should provide one place to keep detailed personal records under the user's control rather than relying on OpenAI or another provider as custodian. It should learn the user's preferences and working style to improve assistance over time. The user wants to steer this development, inspect it, and observe whether unexpected or emergent properties appear as the system learns and gains capability.

This is more than chat-history search or a coding agent with memory: the ambition includes a personal AI system that becomes increasingly capable through use.

### Open questions — do not assume answers

- What should “learn” mean in observable behavior?
- Does it mean changing stored memories and strategies, adapting workflows, changing code, training model weights, or some combination? These are alternatives to discuss, not approved choices.
- How should the user inspect, steer, correct, and roll back learning?
- How should emergent properties be detected and distinguished from errors, drift, and confirmation bias?
- What are the required data ownership, privacy, retention, deletion, and export guarantees?
- What is the smallest useful integrated experience that begins replacing ChatGPT and OpenCode?

### Discovery acceptance criterion

Before implementation, specify concrete examples showing how Evo 4 learns a preference, uses it later, exposes supporting evidence and uncertainty, accepts a correction, and checks whether the correction improves future assistance.

## D-002 — Discovery process (confirmed, 2026-10-27)

The user wants the assistant to understand the product in detail before building. Continue conversationally, generally one high-impact question at a time. Maintain the product vision and decision log; clearly distinguish confirmed requirements, assistant proposals, research findings, and unresolved questions. Do not begin substantial implementation until the user confirms the specification accurately represents the intended product.

## Next discovery topic

Define the intended meaning of “learn me” and “raise an AI system through use” behaviorally, before selecting technical mechanisms.