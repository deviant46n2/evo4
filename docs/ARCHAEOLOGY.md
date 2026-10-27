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
| [evo](https://github.com/deviant46n2/evo) | Early goals, architecture, autonomy boundaries, and lessons from the first iteration | Not yet reviewed in this notebook |
| [evo-3](https://github.com/deviant46n2/evo-3) | Experiment workflow, model improvement without weight training, memory, evaluation, and practical constraints | Not yet reviewed in this notebook |
| [Nemoxiom](https://github.com/deviant46n2/Nemoxiom) | Trustworthy continuity, provenance, archive-first state, and inspectable memory | Not yet reviewed in this notebook |
| [omega](https://github.com/deviant46n2/omega) | AI workstation/runtime integration and local/online model workflows | Not yet reviewed in this notebook |
| [cyberdeck](https://github.com/deviant46n2/cyberdeck) | Integrated operator experience, existing-tool integration, and interface boundaries | Not yet reviewed in this notebook |

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
