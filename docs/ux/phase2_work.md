# Phase 2: Work

## Objective

Create the new default home screen and make the ordered document stack visible
as the core product model.

## User Problem

The current UI asks users to think in feature tabs. The redesign must make the
app feel like moving a document stack from imported to ready-to-export.

## Scope

Phase 2 covers:
- Work home shell
- ordered document pipeline
- context frontier visibility
- row-level primary actions
- blocker language on the home screen
- entry into the document workspace
- row-level export interaction

Phase 2 does not cover:
- detailed document editing surfaces
- queue drawer internals
- setup internals

## Core Screen

### Work Home

Purpose:
- show the ordered document stack
- show current context frontier
- show blockers
- let users act on the current row or open the document workspace

Required areas:
- project header
- context / blocker strip
- ordered document list
- row primary actions

## Document Pipeline Model

Each document row should expose:
- order number
- document label
- short state description
- current status
- one primary action

The row must make order and dependency visible. Later documents should not look
independent when earlier documents still block downstream work.

## Action Model

There is no global `Continue` CTA.

Each row owns exactly one primary action, such as:
- `Open`
- `Open OCR`
- `Open Terms`
- `Open Translation`
- `Open Images`
- `Export`
- `Blocked`

Routing rules:
- if the next step benefits from document context, the row action should open
  the relevant document tab
- examples:
  - OCR correction -> `Open OCR`
  - term extraction or review -> `Open Terms`
  - translation work -> `Open Translation`
  - image inspection -> `Open Images`
- `Export` may remain a direct row action

`Build Terms` is owned by document `Terms`, not directly by the Work row.

## Context Frontier

The Work screen must show the context frontier explicitly.

User-facing behavior:
- identify the last document that safely contributes to downstream context
- explain what is missing before the frontier can advance
- connect blockers to the frontier, not just to isolated documents

The context frontier can be presented as a thin status strip or other low-noise
summary. It does not need a large card.

## Blocker System

The Work screen must explain blockers without forcing the user into the queue.

Blocked reasons must map to the approved taxonomy:
- needs setup
- needs earlier document first
- already running elsewhere
- needs review
- nothing to do

If setup is missing, Work should distinguish:
- `Open App Setup` for missing global connections
- `Open Setup` for missing project-specific configuration

## Component Design Package

Components that need dedicated design:
- top bar
- context / blocker strip
- document list container
- document pipeline row
- status chip system
- blocker badge / tooltip / inline message
- row-level export dialog

## Required States

The Work home needs at least these states:
- empty project
- app setup incomplete
- project setup incomplete
- documents imported but unprocessed
- ready to open document Terms for `Build Terms`
- mid-pipeline with blockers
- exportable document
- all work complete

Document rows need at least:
- ready
- blocked
- running
- failed
- done
- not applicable

## Design Tasks

1. Wireframe the Work home shell.
2. Design the context / blocker strip.
3. Design the document row and all row states.
4. Design how the context frontier appears.
5. Define how Work opens the document workspace.
6. Lock the row-action routing rules.
7. Design the row-level export dialog.
8. Define how missing app setup vs project setup is shown from Work.

## Acceptance Criteria

- A user can understand document order and downstream dependency quickly.
- The current row action is obvious.
- Blocked documents explain the reason without opening another screen.
- Users can tell whether setup problems are app-level or project-level.
- The home screen feels operational, not tab-driven.
