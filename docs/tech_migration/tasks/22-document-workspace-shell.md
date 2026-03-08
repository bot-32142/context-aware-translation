# Task 22: Document Workspace Shell

## Goal

Create the new document-scoped workspace under `Work`.

## Execute

Start after Task 20 establishes Work navigation targets.

## Depends On

- [Task 10](10-app-shell-navigation.md)
- [Task 20](20-work-slice.md)
- [Task 01](01-foundation-contracts.md)

## Must Read

- [Document workspace UX](../../ux/phase4_document_workspace.md)
- [Work UX](../../ux/phase2_work.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/book_workspace.py`
- existing document-scoped tabs inside the old workspace

## Scope

Create the document workspace shell and navigation for:
- Overview
- OCR
- Terms
- Translation
- Images
- Export

This task should establish the shared document-scoped layout and routing, but not fully implement every tab.

## Acceptance Criteria

- document workspace exists as its own shell under Work
- later OCR/Translation/Images/Export tasks can attach independently
- document Terms uses the same conceptual component model as top-level Terms
