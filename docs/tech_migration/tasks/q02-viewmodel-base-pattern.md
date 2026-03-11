# Q02: Viewmodel Base Pattern

## Goal

Establish a reusable QML-facing Python viewmodel pattern on top of the existing
application service boundary.

## Execute

Can start once the QML bootstrap direction is fixed. It does not need the final
shell implementation to exist.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `context_aware_translation/application/events.py`
- `context_aware_translation/application/contracts/common.py`

## Current Code To Inspect

- `context_aware_translation/application/events.py`
- `context_aware_translation/ui/main_window.py`
- `tests/application/fakes.py`

## Ownership Boundary

Primary paths this task should own:

- new `context_aware_translation/ui/viewmodels/`
- viewmodel-specific tests under `tests/ui/` or `tests/application/` if needed

Avoid touching:

- `context_aware_translation/ui/main.py`
- `cat-ui.spec`
- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/features/`
- `context_aware_translation/ui/shell_hosts/`

## Scope

Create the core Python-side pattern that QML will bind to:

- a base QObject viewmodel class or helper layer
- a small routing/state model suitable for shell navigation
- refresh/invalidation helpers that fit the existing application event model
- tests proving the pattern works with fake services or a fake event bus

## Deliverables

1. Base viewmodel infrastructure.
2. A route state model suitable for app/project/document shells.
3. Tests for property/signal update behavior.
4. Clear conventions for future shell and dialog viewmodels.

## Non-Goals

- do not build actual app/project/document shell viewmodels yet
- do not couple viewmodels to QML-specific layout concerns
- do not import storage/workflow/core internals

## Acceptance Criteria

- future shell tasks can subclass or compose the new base pattern
- route state can be represented without depending on QWidget widgets
- tests use fake application-layer dependencies, not backend internals
