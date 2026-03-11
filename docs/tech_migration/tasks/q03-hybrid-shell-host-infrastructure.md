# Q03: Hybrid Shell Host Infrastructure

## Goal

Create host widgets that let QML shell chrome coexist with legacy QWidget
feature panes during the migration.

## Execute

Start after QML bootstrap and the base viewmodel pattern exist.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`
- `docs/tech_migration/tasks/q01-qml-bootstrap-and-resource-loading.md`
- `docs/tech_migration/tasks/q02-viewmodel-base-pattern.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/shell_hosts/project_shell_host.py`
- `context_aware_translation/ui/features/document_workspace_view.py`

## Current Code To Inspect

- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/shell_hosts/project_shell_host.py`
- `context_aware_translation/ui/viewmodels/project_shell.py`
- `context_aware_translation/ui/features/work_view.py`
- `context_aware_translation/ui/features/document_workspace_view.py`

## Ownership Boundary

Primary paths this task should own:

- new `context_aware_translation/ui/shell_hosts/`
- any host-specific tests

Avoid touching:

- `context_aware_translation/ui/features/` internals beyond host integration seams
- `context_aware_translation/ui/viewmodels/` base definitions created by Q02
- packaging/bootstrap code from Q01

## Scope

Implement the container layer that will:

- render QML shell/header/navigation chrome
- host a current QWidget content pane beside or under that chrome
- swap legacy panes based on Python route state
- support modal/dialog hosting for later settings flows

## Deliverables

1. A generic shell host pattern for QML + QWidget coexistence.
2. A dialog host helper.
3. Tests proving route-based pane swapping works.

## Non-Goals

- do not replace the real app shell yet
- do not rewrite feature panes
- do not introduce product-specific navigation policy in the generic host layer

## Acceptance Criteria

- a host can mount a legacy QWidget pane and switch routes without recreating the full window
- host code stays independent of backend internals
- later shell tasks can reuse these hosts instead of inventing new embedding logic
