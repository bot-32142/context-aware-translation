# Task 10: App Shell and Navigation Skeleton

## Goal

Create the new shell structure that separates app-level and project-level surfaces.

## Execute

Start after Wave 0.

## Depends On

- [Task 00](00-foundation-boundaries.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 04](04-foundation-tests-and-boundaries.md)

## Must Read

- [UX architecture](../../ux/phase0/architecture.md)
- [UX journeys](../../ux/phase0/journeys.md)
- [Setup UX](../../ux/phase1_setup.md)

## Current Code To Inspect

- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/views/library_view.py`
- `context_aware_translation/ui/views/profile_view.py`
- `context_aware_translation/ui/views/book_workspace.py`

## Scope

Build the shell/navigation skeleton for:
- app-level `Projects`
- app-level `App Setup`
- project-level `Work`
- project-level `Terms`
- project-level `Setup`
- utility `Queue`

This task should create containers and navigation targets, not fully implement all surfaces.

Implementation note:
- `Work` may temporarily host the embedded legacy `BookWorkspace` as a
  transitional container. That is acceptable for this task because the shell
  contract matters more than replacing the Work surface immediately.

## Deliverables

1. New top-level navigation structure.
2. Placeholder or skeleton screens for the new destinations.
3. Routing into a project shell from the app shell.
4. Removal of dependency on the old `Library / Profiles / workflow tabs` shell as the primary model.

## Non-Goals

- do not fully implement App Setup or Project Setup logic
- do not fully implement Work or Terms features

## Acceptance Criteria

- the app has a visible shell compatible with the approved UX IA
- feature tasks can attach their screens without redefining navigation
- the Work target can remain backed by the embedded legacy workspace until the
  dedicated Work slice replaces it
