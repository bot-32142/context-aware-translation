# Technical Migration Docs

This directory now contains two related but distinct migration tracks:

1. The completed application-boundary migration that moved UI behavior behind
   `context_aware_translation/application/` contracts and services.
2. The active QML shell migration that replaces widget shell chrome with hybrid
   Qt Quick / QML hosts while keeping the same backend boundary.

## Current Execution Plan

The active source of truth is:

- [QML Shell Migration Plan](qml-shell-migration-plan.md)

Use that plan for:

- current task status
- task numbering (`Q01` through `Q42`)
- shell IA decisions
- subagent/task splitting guidance

## Historical Task Pack

Older task files in this directory describe the earlier application-boundary
migration and are still useful as historical implementation context. They are
not the current execution checklist for shell/chrome work.

In particular:

- app settings is now an app-level dialog, not a shell page
- project settings is now a project-level dialog, not a project route
- project primary routes are `Work` and `Terms`
- document local navigation is `OCR`, `Terms`, `Translation`, `Images`, `Export`
- app/project/document/queue chrome should be described in terms of
  `ui/qml/`, `ui/viewmodels/`, and `ui/shell_hosts/`

## Still-Locked Architecture

These rules remain unchanged across both migrations:

- UI talks only to the application layer.
- Backend internals (`workflow`, `storage`, `core`, `documents`, `llm`) stay
  behind that boundary.
- New shell code should follow:

```text
QML -> QObject viewmodels / presenters -> application.services/contracts/events
```

- Do not reintroduce direct backend imports into new UI code.
- Preserve existing behavior unless the UX or migration plan explicitly changes it.

## How To Use This Directory

When assigning work to a new Codex session:

- send this overview
- send [QML Shell Migration Plan](qml-shell-migration-plan.md)
- send the specific task file(s) for the assigned slice
- include the relevant UX spec if the task changes interaction design

Keep tasks narrow, respect file ownership, and prefer the current migration plan
over older shell/navigation assumptions elsewhere in the docs.
