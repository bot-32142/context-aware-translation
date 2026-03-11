# Task 00: Foundation Boundaries and ADR

## Goal

Lock the technical boundary between UI and backend before any feature migration.
This task defines the rules every later task must obey.

## Execute

This task must be executed first.

## Depends On

- approved UX specs in `docs/ux/`

## Must Read

- [Technical migration overview](../README.md)
- [UX architecture](../../ux/phase0/architecture.md)
- [UX journeys](../../ux/phase0/journeys.md)

## Current Code To Inspect

- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/views/book_workspace.py`
- `context_aware_translation/workflow/bootstrap.py`
- `context_aware_translation/workflow/runtime.py`
- `context_aware_translation/workflow/session.py`
- `context_aware_translation/storage/library/book_manager.py`

## Scope

Define and document:
- target package boundaries
- allowed import directions
- what belongs in `application/`
- what stays backend-internal
- what stays UI-only
- how future non-Python UI would talk to the backend contract

## Deliverables

Primary output for this task:
- [ADR 0001: Application Boundary and UI Isolation](../adr-0001-application-boundary.md)

1. An ADR or technical design doc under `docs/tech_migration/` or `docs/adr/`.
2. A package/dependency diagram.
3. A fixed import rule set.
4. A migration note explaining how Qt becomes an adapter, not the owner of business logic.

## Required Decisions

Lock these explicitly:
- whether application contracts use Pydantic models, dataclasses, or another validated DTO approach
- where events live
- how composition/bootstrap works
- whether `BookManager` stays infrastructure-internal
- whether `TaskEngine` is wrapped or partially exposed through application services

## Non-Goals

- do not implement feature slices yet
- do not redesign UX
- do not add HTTP transport yet

## Acceptance Criteria

- later tasks can point to one source of truth for package boundaries
- import direction rules are explicit enough to enforce automatically
- the plan makes React or another UI stack plausible without backend rewrite
