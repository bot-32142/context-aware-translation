# Phase 3: Queue

## Objective

Preserve concurrency visibility and control without making the product feel like
a task console.

## User Problem

Background actions matter, but non-technical users should not have to manage
tasks to operate the app. They only need to understand progress, blockers, and
what is safe to do next.

## Scope

Phase 3 covers:
- queue drawer shell
- queue item display model
- status language
- blocker and failure presentation
- task actions and escalation to details

Phase 3 does not cover:
- Work home itself
- document editing surfaces
- setup flow design

## Core Surface

### Queue Drawer

Purpose:
- show what is running, queued, blocked, failed, or done
- provide explicit control over background actions
- explain task state in human language

The drawer should be accessible globally but remain secondary to the Work home.

## Queue Item Model

Each queue item should show:
- user-facing action title
- related document or project scope
- status
- progress
- current stage if meaningful
- blocker or failure reason
- actions

Allowed actions:
- `Run`
- `Cancel`
- `Retry`
- `Delete`
- `Open related item`

`Open related item` should route to one of:
- the related document row in `Work`
- the related document tab (`OCR`, `Terms`, `Translation`, `Images`, `Export`)
- top-level `Terms` when the issue is truly shared
- project `Setup` when the issue is project-scoped configuration
- `App Setup` when the issue is missing or broken global connections

## Status Language

Use these statuses:
- `Running`
- `Queued`
- `Blocked`
- `Failed`
- `Done`
- `Cancelled`

Avoid engine-centric language on the main row. Technical detail belongs in a
details area.

## Blocker Language

Queue blockers should use the same high-level taxonomy as Work:
- needs setup
- needs earlier document first
- already running elsewhere
- needs review
- nothing to do

A details affordance may reveal exact technical reasons behind the friendly
message.

## Notification Model

This phase must also define how the app notifies users of status changes.

Use:
- inline issue summaries on Work
- lightweight toasts for completion or failure
- queue drawer for deep inspection

Do not require modal dialogs for routine task completions.

## Component Design Package

Components that need dedicated design:
- queue drawer shell
- queue section header
- queue item row
- inline progress indicator
- blocker reason row
- failure detail affordance
- task action menu
- completion toast
- failure toast / banner

## Required States

Queue items need at least:
- queued
- running with progress
- running without progress
- blocked
- failed
- completed
- cancelled

The drawer needs:
- empty
- active only
- mixed history
- overflow / scroll behavior

## Design Tasks

1. Wireframe the queue drawer.
2. Design the queue item row and all statuses.
3. Define how a user opens related Work, Document, Terms, Project Setup, or App Setup targets from the queue.
4. Define the notification model for routine completions and failures.
5. Prototype the drawer on top of the Work home.

## Acceptance Criteria

- A user can understand what is happening in the background without learning the
  task engine.
- Queue visibility does not overwhelm the default shell.
- Failures and blockers are understandable and actionable.
- Advanced operational detail is available without taking over the main UI.
