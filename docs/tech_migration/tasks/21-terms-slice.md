# Task 21: Terms Slice

## Goal

Migrate the shared Terms surface to the application-service boundary while preserving the table-first interaction model.

## Execute

Start after Wave 1.

## Depends On

- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 10](10-app-shell-navigation.md)

## Must Read

- [Terms UX](../../ux/phase5_terms.md)
- [Document workspace UX](../../ux/phase4_document_workspace.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/glossary_view.py`
- `context_aware_translation/ui/models/term_model.py`
- `context_aware_translation/glossary_io.py`
- `context_aware_translation/storage/term_repository.py`

## Scope

Implement the top-level `Terms` surface through application services:
- shared table data
- search/filter
- translate pending
- review
- filter noise
- import/export
- clear distinction between shared Terms and document Terms scope

## Rules

- preserve the existing table interaction model where possible
- document Terms and top-level Terms should share backend service logic
- do not auto-rerun translation after term edits
- toolbar action enable/disable and blockers must come from `TermsService`
- migrated Terms UI must not call task-engine preflight or claim checks directly
- Terms refresh must use application invalidation events + requery

## Acceptance Criteria

- Terms UI can operate against fake application services in tests
- no direct DB or repository access remains in migrated Terms UI
- toolbar buttons render from backend-provided action state
