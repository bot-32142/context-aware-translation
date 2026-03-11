# Q01: QML Bootstrap And Resource Loading

## Goal

Add the minimum runtime needed to load QML safely in local and packaged builds.

## Execute

Start after the QML shell migration direction is accepted.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `context_aware_translation/ui/main.py`
- `cat-ui.spec`

## Current Code To Inspect

- `context_aware_translation/ui/main.py`
- `context_aware_translation/ui/resources/`
- `cat-ui.spec`

## Ownership Boundary

Primary paths this task should own:

- `context_aware_translation/ui/main.py`
- new `context_aware_translation/ui/qml/`
- any QML resource-loader helpers created for startup
- packaging/resource-loading updates needed in `cat-ui.spec`

Avoid touching:

- `context_aware_translation/ui/viewmodels/`
- `context_aware_translation/ui/shell_hosts/`
- `context_aware_translation/ui/main_window.py`
- feature panes under `context_aware_translation/ui/features/`
- tests outside any new QML bootstrap-specific test files

## Scope

Create the bootstrap needed for future QML shells:

- add a stable way to resolve QML files from package resources
- make local editable runs and packaged runs use the same resolution path
- keep startup error surfacing as strong as the current QWidget startup path
- do not replace the existing app shell yet

## Deliverables

1. A QML resource directory with at least one trivial loadable component.
2. A Python loader/helper that can resolve QML assets.
3. Startup/runtime plumbing that can instantiate a minimal QML surface without changing the full app shell.
4. Packaging updates so QML files are included in PyInstaller builds.

## Non-Goals

- do not build the app shell
- do not introduce routing/viewmodel abstractions beyond what is necessary for bootstrap
- do not replace `MainWindow`

## Acceptance Criteria

- the app can resolve QML assets in both editable and packaged contexts
- a minimal QML component can be loaded through the new bootstrap path
- startup failures still surface with clear error details
- the existing app can keep running on the QWidget shell while this bootstrap lands
