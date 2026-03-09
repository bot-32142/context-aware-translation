# UX Program Roadmap

## Goal

Turn the app into a guided translation workspace without changing the underlying
ordered-document, context-tree, or task-engine model.

## Delivery Order

Recommended order:
1. Phase 0: product architecture, language, and journeys
2. Phase 1: Setup
3. Phase 2: Work
4. Phase 3: Queue
5. Phase 4: Document Workspace
6. Phase 5: Terms
7. Phase 6: Advanced Controls

Reasoning:
- Setup removes the largest onboarding barrier.
- Work establishes the new home and mental model.
- Queue remains secondary after Work is stable.
- Document Workspace defines where document-scoped tools live.
- Terms can then be finalized as the one shared surface.
- Advanced controls should be layered onto the new shell, not designed first.

## Parallelism

### Sequential gates

These must be approved before the next stage starts:
- Phase 0 before any visual system work
- Phase 1 before detailed Work interactions
- Phase 2 before Document Workspace and Terms are finalized
- Phase 4 before advanced document tooling is finalized

### Safe parallel work

- Copywriting can run in parallel with wireframes after Phase 0
- Setup components can be designed in parallel inside Phase 1
- Work row design and sidebar design can run in parallel inside Phase 2
- Queue and Document Workspace can overlap after Work is stable
- Terms can overlap late Document Workspace design

## Workstreams

Each phase should ship through the same workstreams:
- product spec
- low-fidelity wireframes
- mid-fidelity screen flows
- clickable prototype for high-risk screens
- copy pass
- usability review

## Roles

Recommended ownership:
- Product: approve journeys, scope, and success criteria
- UX: screen flows, wireframes, interaction model, copy intent
- Visual Design: visual system and component polish after low-fidelity approval
- Engineering: feasibility review after each phase spec is accepted

## Approval Gates

### Gate A: Post-Phase 1

Questions to answer:
- can a new user understand app setup from one screen?
- can the app explain missing capabilities without jargon?
- can a project clearly choose a shared workflow profile or create a project-specific profile without confusion?

### Gate B: Post-Phase 2

Questions to answer:
- does the Work screen make document order and context frontier obvious?
- can a user tell what to do next in under 30 seconds?
- are blockers understandable without opening the queue?

### Gate C: Post-Phase 4

Questions to answer:
- does the document workspace keep document-scoped work coherent?
- are reruns and retries explicit enough?
- do OCR and term edits feel trustworthy?

### Gate D: Post-Phase 6

Questions to answer:
- do advanced controls feel like an expansion of the same app?
- do default surfaces remain clean after advanced controls are added?
- is endpoint/model management still discoverable when needed?

## Deliverables by Phase

- Phase 1: app setup landing, setup wizard, workflow profile editor, project
  setup, profile-selection model
- Phase 2: Work shell, pipeline table/board, action hierarchy, blocker system
- Phase 3: queue drawer, status language, background-action feedback
- Phase 4: document shell, document tabs, document-scoped OCR/Terms/translation/image/export
- Phase 5: shared Terms shell, retained table model, toolbar and bulk actions
- Phase 6: advanced setup, queue details, power-user affordances, diagnostic panels

## Exit Criteria

The program is complete when:
- a new user can reach first successful translation without opening advanced setup
- app-level connections and shared workflow profiles are clearly distinct from
  project-level setup and project-specific profiles
- the ordered document model is obvious on the home screen
- document-scoped tools are clearly nested under Work
- shared Terms feels distinct from document tools but uses the same data model
- advanced controls remain available without reverting to the old information architecture
