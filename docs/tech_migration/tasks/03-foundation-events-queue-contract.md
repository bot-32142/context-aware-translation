# Task 03: Application Events and Queue Contract

## Goal

Define and implement the event model that decouples UI updates from Qt-specific task engine signals.

## Execute

Run after Task 02.

## Depends On

- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)

## Must Read

- [Queue UX](../../ux/phase3_queue.md)
- [Document workspace UX](../../ux/phase4_document_workspace.md)

## Current Code To Inspect

- `context_aware_translation/ui/tasks/qt_task_engine.py`
- `context_aware_translation/ui/widgets/task_activity_panel.py`
- `context_aware_translation/ui/widgets/task_status_card.py`
- `context_aware_translation/workflow/tasks/engine_core.py`
- `context_aware_translation/workflow/tasks/models.py`

## Scope

Build a UI-framework-agnostic event layer for:
- task updates
- queue changes
- project updates
- document updates
- setup changes
- terms changes

## Deliverables

1. Typed application event models.
2. Event publisher/subscriber interface.
3. Queue DTOs that map backend task state into UX state.
4. A Qt adapter that translates application events into Qt signals.
5. A locked invalidation model for migrated surfaces.
6. Shared action-state patterns for feature queries where current contracts are
   still ad hoc.

## Rules

- the UI should not treat `TaskEngine` signals as the system of record anymore
- queue items must use application DTOs, not raw `TaskRecord`
- future HTTP/SSE/WebSocket transport should be plausible from the same event contract
- events should be invalidation-first, not raw task-engine mirrors
- migrated widgets must not call `TaskEngine.preflight()` or
  `has_active_claims()` directly for button enable/disable
- command execution paths must still run strict backend preflight at click time
- invalidation must account for both persisted DB changes and in-memory active
  claim changes

## Acceptance Criteria

- queue updates can be consumed without importing Qt classes
- task/queue state is exposed in UX-friendly terms
- later Queue and feature slices can build on this without touching `EngineCore`
- there is a documented way for migrated surfaces to refresh via invalidation +
  requery
- there is a documented way for migrated surfaces to render action availability
  and blockers from backend query state
