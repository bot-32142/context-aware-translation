# Task 02: Application Services and Composition Root

## Goal

Implement the backend-facing application service layer and a composition root that wires existing backend pieces into it.

## Execute

Run after Task 01.

## Depends On

- [Task 00](00-foundation-boundaries.md)
- [Task 01](01-foundation-contracts.md)

## Must Read

- [Technical migration overview](../README.md)
- [UX architecture](../../ux/phase0/architecture.md)

## Current Code To Inspect

- `context_aware_translation/workflow/bootstrap.py`
- `context_aware_translation/workflow/runtime.py`
- `context_aware_translation/workflow/session.py`
- `context_aware_translation/storage/book_manager.py`
- `context_aware_translation/workflow/tasks/engine_core.py`
- `context_aware_translation/workflow/tasks/handlers/`
- `context_aware_translation/ui/tasks/qt_task_engine.py`

## Scope

Create real application service implementations that wrap the current backend.

Expected outputs:
- `application/services/*.py`
- `application/composition.py`
- dependency wiring for project/session/task services

## Required Behavior

- services own orchestration for commands and queries
- composition is the single place where infrastructure is instantiated
- UI should no longer need to know how to build `BookManager`, `WorkflowSession`, or repo objects

## Design Constraint

Do not rewrite backend workflows. Wrap them.

## Non-Goals

- do not migrate Qt screens yet
- do not add HTTP transport

## Acceptance Criteria

- there is one backend composition root for the application layer
- UI could request service instances without constructing backend infrastructure itself
- backend internals remain reusable and unchanged where possible
