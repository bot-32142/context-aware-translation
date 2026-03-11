# Phase 4: Document Workspace

## Objective

Make `OCR`, `Terms`, `Translation`, `Images`, and `Export` feel like
document-scoped tools inside `Work`, not disconnected top-level areas.

## User Problem

Most correction and processing work is scoped to a single document or page. The
current shell model keeps shared project work in `Work` and top-level `Terms`,
while document-specific work lives behind a local document navigation surface.

## Scope

Phase 4 covers:

- document shell chrome
- document-local navigation
- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

Phase 4 does not cover:

- work-home layout
- shared project `Terms`
- app/project settings dialog flows

## Core Surface

### Document Workspace

Purpose:

- provide one place for document-scoped actions
- keep review, correction, and export close to the current document
- avoid bouncing users through unrelated top-level surfaces

Required sections:

- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

The document shell should also expose:

- a clear document title/context
- a `Back to Work` action
- local section switching without changing project-level navigation

## Terms in the Document Workspace

The document `Terms` section is a filtered view of shared project `Terms`.

Rules:

- it uses the same table-first UI as the top-level `Terms` surface
- it is scoped to the current document
- edits write to the shared terms table
- `Build Terms` lives here when the document is ready for glossary extraction
- editing terms does not automatically rerun translation

## Interaction Rules

- document-level actions remain explicit
- OCR save does not auto-rerun downstream work
- term edits do not auto-rerun downstream work
- export can be initiated from this workspace or directly from `Work`
- the workspace should always preserve the sense of current document scope

## Component Design Package

Components that need dedicated design:

- document header
- document local navigation
- OCR editor pane
- document terms table
- translation editor
- image inspection / rerun surface
- export sheet or export panel

## Required States

The document workspace needs:

- empty / not yet processed
- ready for OCR
- ready for `Build Terms`
- ready for translation
- translation running
- image processing blocked by setup
- export ready

## Design Tasks

1. Wireframe the document shell and local navigation.
2. Reuse the terms table for the document `Terms` section.
3. Define document-scoped OCR and translation editing surfaces.
4. Define image inspection and rerun affordances.
5. Define export interaction from the document workspace.

## Acceptance Criteria

- Users understand that these tools apply to the current document only.
- The document `Terms` section feels like the same UI as shared `Terms`, with narrower scope.
- `Build Terms` is clearly discoverable without inventing a separate overview screen.
- Document-level work no longer requires separate top-level review or output destinations.
