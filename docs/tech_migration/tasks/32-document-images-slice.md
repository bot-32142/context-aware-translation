# Task 32: Document Images Slice

## Goal

Migrate image reembedding/reinsertion workflows into the new document workspace and service layer.

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
- [Advanced controls UX](../../ux/phase6_advanced_controls.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/reembedding_view.py`
- image reembedding task handler(s)
- recent manga grouped-reembed implementation in `context_aware_translation/documents/manga.py` and related helpers as needed

## Scope

Implement the document `Images` tab:
- view image/text reinsertion status
- run explicit image-edit actions
- retry/cancel where applicable
- expose setup blockers cleanly

## Rules

- image editing stays explicit
- missing setup should route to the correct setup surface
- UI should not talk to low-level image-backend code directly

## Acceptance Criteria

- document images UI depends only on application services
- setup blockers are surfaced through application contracts, not ad hoc logic in the view
