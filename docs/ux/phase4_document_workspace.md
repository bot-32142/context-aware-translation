# Phase 4: Document Workspace

## Objective

Make OCR, Terms, Translation, Images, and Export feel like document-scoped
tools inside `Work`, not disconnected top-level areas.

## User Problem

Most correction and processing work is scoped to a single document or page. The
current redesign is cleaner when shared Terms stay shared at the top level,
while document-specific work lives inside a document workspace.

## Scope

Phase 4 covers:
- document detail shell
- document navigation model
- Overview
- OCR
- Terms
- Translation
- Images
- Export

Phase 4 does not cover:
- Work home
- shared Terms surface
- setup flow

## Core Surface

### Document Workspace

Purpose:
- provide one place for all document-scoped actions
- keep document review and processing close to the source content
- reduce the need for separate top-level review or outputs screens

Required sections:
- `Overview`
- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

## Terms in the Document Workspace

The document `Terms` tab is a filtered view of shared project Terms.

Rules:
- it uses the same table-first UI as the top-level `Terms` screen
- it is scoped to the current document
- edits write to the shared Terms table
- `Build Terms` lives here when the document is ready for glossary extraction
- editing terms does not automatically rerun translation

This means `Build Terms` is owned by the document `Terms` tab, not by
`Overview`.

## Interaction Rules

- document-level actions remain explicit
- OCR save does not auto-rerun downstream work
- term edits do not auto-rerun downstream work
- export can be initiated from this workspace or directly from `Work`
- the workspace should always preserve the sense of current document scope

## Component Design Package

Components that need dedicated design:
- document header
- document sub-navigation
- Overview summary
- OCR editor pane
- document Terms table
- translation editor
- image inspection / rerun surface
- export sheet or export panel

## Required States

The document workspace needs:
- empty / not yet processed
- ready for OCR
- ready for Build Terms
- ready for translation
- translation running
- image processing blocked by setup
- export ready

## Design Tasks

1. Wireframe the document shell and sub-navigation.
2. Define which actions live in Overview versus the tool tabs.
3. Reuse the Terms table for the document `Terms` tab.
4. Define document-scoped OCR and translation editing surfaces.
5. Define the export interaction from the document workspace.

## Acceptance Criteria

- Users understand that these tools apply to the current document only.
- The document `Terms` tab feels like the same UI as shared `Terms`, with
  narrower scope.
- `Build Terms` is clearly discoverable without inventing a special-case screen.
- Document-level work no longer requires separate top-level review or output destinations.
