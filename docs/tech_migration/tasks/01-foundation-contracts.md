# Task 01: Application Contracts and Service Interfaces

## Goal

Create the contract layer that the UI will depend on.

## Execute

Run after Task 00.

## Depends On

- [Task 00](00-foundation-boundaries.md)

## Must Read

- [Technical migration overview](../README.md)
- [UX terminology](../../ux/phase0/terminology.md)
- [Setup UX](../../ux/phase1_setup.md)
- [Work UX](../../ux/phase2_work.md)
- [Queue UX](../../ux/phase3_queue.md)
- [Document workspace UX](../../ux/phase4_document_workspace.md)
- [Terms UX](../../ux/phase5_terms.md)

## Scope

Define the application-level interfaces and DTOs for:
- projects
- app setup
- project setup
- work
- terms
- document workspace
- queue
- common errors and status DTOs

## Expected Package Shape

```text
context_aware_translation/application/
  contracts/
    common.py
    projects.py
    app_setup.py
    project_setup.py
    work.py
    terms.py
    document.py
    queue.py
  services/
    *.py
  errors.py
```

## Current Code To Inspect

- `context_aware_translation/ui/views/library_view.py`
- `context_aware_translation/ui/views/profile_view.py`
- `context_aware_translation/ui/views/book_workspace.py`
- `context_aware_translation/ui/views/glossary_view.py`
- `context_aware_translation/ui/views/translation_view.py`
- `context_aware_translation/ui/views/ocr_review_view.py`
- `context_aware_translation/ui/views/reembedding_view.py`
- `context_aware_translation/ui/views/export_view.py`

## Deliverables

1. Contract models for every screen/surface in the new UX.
2. Service interfaces or protocols for every application service.
3. Stable error/result types.
4. Serialization rules for contracts.

## Contract Requirements

- JSON-serializable
- no Qt types
- no raw SQLite rows
- no `TaskRecord` or handler-specific models as UI contracts
- status and blocker language should map cleanly to the UX taxonomy

## Non-Goals

- do not implement backend wiring yet
- do not migrate views yet

## Acceptance Criteria

- a UI adapter could be written against these interfaces without importing backend internals
- all top-level UX surfaces have a corresponding contract
- queue/task semantics are translated into user-facing DTOs, not leaked directly
