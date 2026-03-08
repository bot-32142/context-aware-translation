# Technical Migration Task Pack

This directory turns the approved UX design into an implementation program with
clear backend/UI isolation and parallelizable feature slices.

## Goal

Establish a stable application-contract boundary between UI and backend so that:
- the Qt UI can be replaced later without rewriting backend logic
- backend refactors do not force UI rewrites as long as contracts stay stable
- feature work can be split across multiple agents with minimal file overlap

## Locked Architectural Direction

Foundation boundary ADR:
- [ADR 0001: Application Boundary and UI Isolation](adr-0001-application-boundary.md)

- UI must talk only to an application layer.
- The application layer owns commands, queries, DTOs, events, and errors.
- Backend internals (`workflow`, `storage`, `core`, `documents`, `llm`) stay behind that boundary.
- Qt becomes one adapter; a future HTTP/WebSocket adapter can be added later.
- Contracts should be JSON-serializable from day one.
- Advanced controls stay inside the same application/service boundary.

## Current Problem Summary

Today the Qt views directly import and use backend internals such as:
- `BookManager`
- `SQLiteBookDB`
- `DocumentRepository`
- `TaskEngine` preflight / submit details
- profile/config storage details

That means the UI knows too much about backend structure and task semantics.
The first migration goal is to stop direct UI imports of backend internals.

## Must-Read UX Specs

Read these first before touching technical design:
- [UX architecture](../ux/phase0/architecture.md)
- [UX journeys](../ux/phase0/journeys.md)
- [UX terminology](../ux/phase0/terminology.md)
- [Setup UX](../ux/phase1_setup.md)
- [Work UX](../ux/phase2_work.md)
- [Queue UX](../ux/phase3_queue.md)
- [Document workspace UX](../ux/phase4_document_workspace.md)
- [Terms UX](../ux/phase5_terms.md)
- [Advanced controls UX](../ux/phase6_advanced_controls.md)

## Current Technical Seams To Know

Current UI/backend coupling is concentrated in:
- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/views/book_workspace.py`
- `context_aware_translation/ui/views/library_view.py`
- `context_aware_translation/ui/views/profile_view.py`
- `context_aware_translation/ui/views/translation_view.py`
- `context_aware_translation/ui/views/glossary_view.py`
- `context_aware_translation/ui/views/ocr_review_view.py`
- `context_aware_translation/ui/views/reembedding_view.py`
- `context_aware_translation/ui/views/export_view.py`

Existing backend foundations that should be reused, not replaced:
- `context_aware_translation/workflow/bootstrap.py`
- `context_aware_translation/workflow/runtime.py`
- `context_aware_translation/workflow/session.py`
- `context_aware_translation/workflow/tasks/engine_core.py`
- `context_aware_translation/workflow/tasks/handlers/`
- `context_aware_translation/storage/book_manager.py`

## Target Package Shape

Expected new package direction:

```text
context_aware_translation/
  application/
    contracts/
    services/
    events.py
    errors.py
    composition.py
  ui/
    features/
      projects/
      app_setup/
      project_setup/
      work/
      terms/
      queue/
      document/
```

Exact naming can be adjusted if needed, but the dependency rule is fixed.

## How To Use These Task Files

When assigning one task to a new Codex session, send:
- this overview file
- the specific task file
- any linked UX specs listed in that task

Tell the agent to stay inside the task scope, avoid opportunistic refactors, and
call out any dependency blocker instead of expanding the task.

## Global Rules For All Tasks

1. UI code must not import `storage`, `workflow`, `core`, `documents`, or `llm` directly once a slice is migrated.
2. New application contracts must be framework-agnostic and JSON-serializable.
3. Preserve existing behavior unless the UX spec explicitly changes it.
4. Do not build a network service yet. The first adapter stays in-process Python.
5. Prefer adding a clean seam before moving feature code.
6. Keep tasks narrow. Do not opportunistically refactor adjacent slices.
7. Add or update tests for every migrated slice.

## Execution Waves

### Wave 0: Foundation
Execute in this order:
1. [Task 00](tasks/00-foundation-boundaries.md)
2. [Task 01](tasks/01-foundation-contracts.md)
3. [Task 02](tasks/02-foundation-services-composition.md)
4. [Task 03](tasks/03-foundation-events-queue-contract.md)
5. [Task 04](tasks/04-foundation-tests-and-boundaries.md)

Wave 0 must land before feature-slice migration starts.

### Wave 1: Shell and Setup
Can start after Wave 0. Recommended order:
1. [Task 10](tasks/10-app-shell-navigation.md)
2. [Task 11](tasks/11-app-setup-slice.md)
3. [Task 12](tasks/12-project-setup-slice.md)

Task 11 and Task 12 can run in parallel once Task 10 provides the navigation shell.

### Wave 2: Project-Level Surfaces
Can start after Wave 1 skeletons exist:
- [Task 20](tasks/20-work-slice.md)
- [Task 21](tasks/21-terms-slice.md)
- [Task 22](tasks/22-document-workspace-shell.md)
- [Task 23](tasks/23-queue-drawer-slice.md)

Task 20, 21, and 23 can run in parallel. Task 22 should start once the new Work navigation target exists.

### Wave 3: Document Functionality
Can start after Task 22:
- [Task 30](tasks/30-document-ocr-slice.md)
- [Task 31](tasks/31-document-translation-slice.md)
- [Task 32](tasks/32-document-images-slice.md)
- [Task 33](tasks/33-document-export-slice.md)

These can mostly run in parallel if they stay inside their assigned document tabs.

## Recommended Agent Assignment

- Agent A: Wave 0 foundation tasks
- Agent B: App shell + App Setup
- Agent C: Project Setup
- Agent D: Work + Queue
- Agent E: Terms
- Agent F: Document shell + OCR
- Agent G: Translation
- Agent H: Images + Export

## Definition Of Foundation Done

The foundation is good enough when:
- a new `application/` layer exists
- UI can depend on service interfaces and contract DTOs
- backend internals are hidden behind composition
- queue/task updates can be exposed as application events
- import boundaries are enforceable in CI
- at least one migrated slice can be tested against a fake application service

## Important Constraint

Do not treat these as independent greenfield rewrites. The existing backend is
valuable. The migration should wrap and isolate it first, then replace UI
surface by surface.
