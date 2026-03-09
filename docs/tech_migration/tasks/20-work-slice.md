# Task 20: Work Slice

## Goal

Implement the new `Work` home as the primary project surface.

## Execute

Start after Wave 1 skeletons are in place.

## Depends On

- [Task 10](10-app-shell-navigation.md)
- [Task 12](12-project-setup-slice.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 03](03-foundation-events-queue-contract.md)

## Must Read

- [Work UX](../../ux/phase2_work.md)
- [UX architecture](../../ux/phase0/architecture.md)
- [UX terminology](../../ux/phase0/terminology.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/book_workspace.py`
- `context_aware_translation/ui/views/import_view.py`
- current book/document progress usage in storage/repositories

## Scope

Implement:
- ordered document list
- context frontier strip
- one primary row action per document
- blocker messages
- row-level export dialog entry
- navigation into document workspace tabs

## Rules

- Work is a routing/orchestration surface, not a place to expose raw backend task details
- row actions should mostly navigate to document tabs
- `Build Terms` belongs in document `Terms`, not on Work rows
- row action enabled/disabled state and blockers must come from `WorkService`
- the view must not call task-engine preflight or claim checks directly
- Work refresh must use application invalidation events + requery

## Acceptance Criteria

- Work no longer depends on the old tab-first book workspace model
- Work data comes from a `WorkService`
- the view does not open SQLite repositories directly
- row buttons render from backend-provided action state
