# Task 31: Document Translation Slice

## Goal

Migrate translation progress, review, save, and explicit retranslation into the new document workspace and contract layer.

## Execute

Start after Task 22.

## Depends On

- [Task 22](22-document-workspace-shell.md)
- [Task 21](21-terms-slice.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)

## Must Read

- [Document workspace UX](../../ux/phase4_document_workspace.md)
- [Terms UX](../../ux/phase5_terms.md)
- [UX journeys](../../ux/phase0/journeys.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/translation_view.py`
- `context_aware_translation/ui/views/manga_review_widget.py`
- translation-related workflow handlers

## Scope

Implement the document `Translation` tab:
- translation progress state
- review/edit/save
- chunk/page selection
- explicit retranslation
- document-scoped `Terms used here` integration if introduced during implementation

## Rules

- no hidden mass reruns
- translation UI must consume service DTOs, not direct DB rows
- document-scoped terms must still write through the shared Terms service

## Acceptance Criteria

- translation UI no longer imports repositories or raw task engine details directly
- retranslation stays explicit and scoped
