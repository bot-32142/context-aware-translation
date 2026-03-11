# Q20: App Settings Dialog Host

## Goal

Move app settings out of the primary shell and into a dialog/sheet flow, then
replace the dialog body with native QML-backed pane chrome.

## Execute

Start after the app shell host is in place.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`
- `docs/tech_migration/tasks/q10-app-shell-host.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `context_aware_translation/ui/features/app_settings_pane.py`
- `context_aware_translation/ui/viewmodels/app_settings_dialog.py`
- `tests/ui/test_app_settings_dialog_host.py`

## Current Code To Inspect

- `context_aware_translation/ui/features/app_settings_pane.py`
- `context_aware_translation/ui/main_window.py`

## Ownership Boundary

Primary paths this task should own:

- app-settings dialog host code
- new `context_aware_translation/ui/viewmodels/app_settings_dialog.py`
- new `context_aware_translation/ui/qml/dialogs/app_settings/`
- minimal integration needed in `context_aware_translation/ui/main_window.py`

Avoid touching:

- project settings code
- work/document/terms feature logic
- app setup service contracts unless a small host-facing seam is necessary

## Scope

Create a dialog/sheet entry point for app settings:

- launched from the app menu or equivalent shell affordance
- deep-linkable from setup blockers
- backed by a dedicated QML dialog host and QML pane chrome

## Deliverables

1. App settings dialog viewmodel.
2. QML dialog chrome.
3. QML-backed app settings pane body.
4. Tests for open/close/deep-link behavior.

## Non-Goals

- do not change app setup service behavior
- do not rewrite the connection/profile editor dialogs unless needed for parity

## Acceptance Criteria

- app setup no longer needs to exist as a primary shell page
- the dialog can be opened from shell actions and blocker routes
- current app setup functionality remains accessible through the dialog flow
