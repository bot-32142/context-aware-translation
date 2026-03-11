# Q10: App Shell Host

## Goal

Replace the current app-level navigation chrome with a QML-driven app shell
while keeping the existing service-backed feature panes alive.

## Execute

Start after Q01 to Q04 are complete.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`
- `docs/tech_migration/tasks/q01-qml-bootstrap-and-resource-loading.md`
- `docs/tech_migration/tasks/q02-viewmodel-base-pattern.md`
- `docs/tech_migration/tasks/q03-hybrid-shell-host-infrastructure.md`
- `docs/tech_migration/tasks/q04-qml-test-harness-and-boundary-guards.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `context_aware_translation/ui/main_window.py`
- `tests/ui/test_main_window_shell.py`

## Current Code To Inspect

- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/features/library_view.py`
- `context_aware_translation/ui/features/queue_drawer_view.py`

## Ownership Boundary

Primary paths this task should own:

- `context_aware_translation/ui/main_window.py`
- new `context_aware_translation/ui/viewmodels/app_shell.py`
- new `context_aware_translation/ui/qml/app/`
- new `context_aware_translation/ui/shell_hosts/app_shell_host.py`
- app-shell-specific tests

Avoid touching:

- project/document shell implementations beyond new integration seams
- settings internals
- feature-pane business logic

## Scope

Build the QML app shell that:

- uses `Projects` as the primary app surface
- removes the global left sidebar from the primary chrome
- routes project opening/closing through the new shell model
- leaves `App Settings` as a dialog entry point, not a primary page

## Deliverables

1. App shell viewmodel.
2. App shell QML chrome.
3. Integration into `MainWindow`.
4. Tests for route changes and project open/close behavior.

## Non-Goals

- do not fully implement app settings dialog internals
- do not replace work/terms/document panes

## Acceptance Criteria

- the primary app shell no longer relies on the global left sidebar
- opening a project still works with the existing feature panes
- app settings is represented as a dialog affordance, not a main route
