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

## D-003 — Learning through use and self-directed research
- **Status:** Confirmed direction; implementation details open.
- **Date:** 2026-10-27.
- **Question:** What should Evo learn from, and how much initiative should it have?
- **User decision:** Evo should be able to learn from anything the user does through Evo and may initiate its own learning and research. The user wants the system to improve through experience, such as becoming a stronger chess or MTG opponent across repeated games, and to synthesize context across projects.
- **Adaptation rule:** Choose between immediate adoption and further testing based on the evidence and risk; no universal “always test first” or “always trust the latest lesson” rule. Confidence alone is not evidence.
- **Code boundary:** Self-modification of Evo's code should initially require a human in the loop; this may be revisited later.
- **Resource boundary:** The user needs a dependable way to free GPU VRAM. Deterministic services may stay running if their resource costs are acceptable; GPU-resident models may need unloading. Persistent memory and task state should survive model unload/shutdown.
- **Assistant interpretation / proposals:** Preserve provenance for learned lessons; evaluate generalization; keep code modification distinct from ordinary adaptation; measure actual VRAM release; retain a user-visible autonomy control. These are design implications, not approved technical architecture.
- **Open:** Scope of autonomous data/tool access and side effects; precise pause/VRAM-release semantics; safeguards for code changes; model-weight training; sensitive-data capture/retention/deletion; criteria for evaluating learned lessons.
- **Evidence:** User's direct answers in the 2026-10-27 discovery conversation. Related details recorded in `docs/LEARNING-THROUGH-EXPERIENCE.md`.
- **Consequences:** Discovery must account for self-directed learning and GPU resource reclamation before architecture is selected. No implementation is authorized by this entry.

## D-004 — Initial self-modification boundary
- **Status:** Confirmed initial boundary.
- **Date:** 2026-10-27.
- **Decision:** Evo may learn and adapt, but modifying its own code initially requires a human-in-the-loop procedure. This is a starting boundary and can be revisited with evidence later.
- **Not yet decided:** Exact test requirements, sandboxing, approval experience, rollback guarantees, or any low-risk exceptions.
- **Evidence:** User's direct answer in the 2026-10-27 discovery conversation.
