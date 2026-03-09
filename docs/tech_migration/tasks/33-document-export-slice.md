# Task 33: Document Export Slice

## Goal

Migrate export to the new document workspace and Work row-dialog model.

## Execute

Start after Task 22. It can run in parallel with OCR/Translation/Images.

## Depends On

- [Task 20](20-work-slice.md)
- [Task 22](22-document-workspace-shell.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)

## Must Read

- [Work UX](../../ux/phase2_work.md)
- [Document workspace UX](../../ux/phase4_document_workspace.md)
- [UX journeys](../../ux/phase0/journeys.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/export_view.py`
- export-related workflow/task code

## Scope

Implement:
- row-level export dialog from Work
- document `Export` tab
- export readiness query
- export execution through application service
- output-path/result feedback

## Rules

- there is no top-level Outputs screen
- export should remain scoped and small by default
- advanced export options can remain secondary
- export readiness and blockers must come from `WorkService` / `DocumentService`
- migrated export UI must not call task-engine preflight or claim checks directly
- export dialog/state refresh must use application invalidation events + requery

## Acceptance Criteria

- export is available from Work and document scope without exposing raw backend details
- export UI is application-service driven and testable with fakes
- export actions render from backend-provided action state
