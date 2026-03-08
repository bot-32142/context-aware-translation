# Task 30: Document OCR Slice

## Goal

Migrate OCR review/edit/rerun into the new document workspace and application-service boundary.

## Execute

Start after Task 22.

## Depends On

- [Task 22](22-document-workspace-shell.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)

## Must Read

- [Document workspace UX](../../ux/phase4_document_workspace.md)
- [UX journeys](../../ux/phase0/journeys.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/ocr_review_view.py`
- OCR task handler and related workflow code

## Scope

Implement the document `OCR` tab using application services:
- load OCR content
- edit/save OCR content
- rerun current page
- rerun pending pages
- show OCR task status via queue/event abstractions

## Rules

- saving OCR must not auto-rerun translation
- UI should not open `SQLiteBookDB` or `DocumentRepository` directly after migration

## Acceptance Criteria

- OCR UI is document-scoped and service-driven
- OCR behavior matches existing semantics where UX did not change
