# Phase 5: Terms

## Objective

Keep Terms as the only shared glossary surface while preserving the existing
table-first interaction model.

## User Problem

Terms are shared across documents, but users already understand the current
table view well enough. The redesign should not replace a working interaction
model just for consistency with the rest of the shell.

## Scope

Phase 5 covers:
- top-level `Terms` screen
- shared term table behavior
- review / translate / filter / import / export actions
- relationship between global Terms and document Terms

Phase 5 does not cover:
- document workspace shell
- Work home
- setup flow

## Core Screen

### Terms

Purpose:
- provide the shared, canonical glossary surface for the project
- support translation, review, filtering, import, export, and editing
- remain familiar to existing users

Required areas:
- existing table-first Terms view
- search
- bulk actions
- top toolbar for shared term operations

## Interaction Rules

- `Build Terms` is not initiated here; it is initiated from document `Terms`
- this screen is the source of truth for shared terms
- document `Terms` is the same data with narrower scope
- edits here do not automatically rerun translation
- toolbar actions stay table-centric and shared-scope

## Component Design Package

Components that need dedicated design:
- shared Terms toolbar
- term table
- filters and search
- bulk action bar
- import / export affordances
- shared/document scope indicator

## Required States

The Terms screen needs:
- empty
- pending translation
- needs review
- filtered noise
- imported glossary
- mixed-status table

## Design Tasks

1. Preserve the existing table interaction model.
2. Redesign only the surrounding shell and scope messaging.
3. Define how global Terms and document Terms share one component model.
4. Make `Translate pending`, `Review`, and `Filter noise` explicit in the top toolbar.

## Acceptance Criteria

- Existing users recognize the Terms table immediately.
- New users can understand that Terms is shared across the project.
- The difference between global Terms and document Terms is clear but minimal.
- The redesign does not invent unnecessary new glossary interaction patterns.
