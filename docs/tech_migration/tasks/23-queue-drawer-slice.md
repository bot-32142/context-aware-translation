# Task 23: Queue Drawer Slice

## Goal

Implement the queue drawer against the new application event and queue contract.

## Execute

Can start after Task 03 and Task 10.

## Depends On

- [Task 03](03-foundation-events-queue-contract.md)
- [Task 10](10-app-shell-navigation.md)

## Must Read

- [Queue UX](../../ux/phase3_queue.md)
- [UX terminology](../../ux/phase0/terminology.md)

## Current Code To Inspect

- `context_aware_translation/ui/widgets/task_activity_panel.py`
- `context_aware_translation/ui/widgets/task_status_card.py`
- `context_aware_translation/ui/tasks/qt_task_engine.py`

## Scope

Implement:
- queue drawer shell
- queue list from application DTOs
- run/cancel/retry/delete actions
- open-related-item routing
- basic completion/failure notification behavior

## Rules

- do not let queue become the primary shell
- use application event models, not raw task-engine internals

## Acceptance Criteria

- queue UI can be backed by fake queue services/events in tests
- queue items expose UX-friendly state and routing targets
