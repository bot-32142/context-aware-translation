# Q04: QML Test Harness And Boundary Guards

## Goal

Add test and CI guardrails for new QML/viewmodel/host code.

## Execute

Can start once the new package directions are fixed. It should finish before
larger QML shell tasks proceed.

## Depends On

- `docs/tech_migration/qml-shell-migration-plan.md`

## Must Read

- `docs/tech_migration/qml-shell-migration-plan.md`
- `tests/architecture/test_migrated_ui_boundaries.py`
- `tests/ui/AGENTS.md`

## Current Code To Inspect

- `tests/architecture/test_migrated_ui_boundaries.py`
- `tests/ui/test_main_window_shell.py`
- `tests/application/fakes.py`

## Ownership Boundary

Primary paths this task should own:

- new QML-related test files under `tests/ui/`
- new or updated guard tests under `tests/architecture/`

Avoid touching:

- production QML shell implementation files except for tiny testability hooks if absolutely required
- feature-pane logic

## Scope

Create the first guardrails for the new QML migration layers:

- architecture guards for `ui/viewmodels` and `ui/shell_hosts`
- a smoke-test pattern for loading a tiny QML component
- a host/viewmodel integration test pattern

## Deliverables

1. Import-boundary tests covering the new QML-related Python layers.
2. A repeatable QML smoke-test pattern for future tasks.
3. A test harness pattern future agents can extend.

## Non-Goals

- do not build the app shell
- do not enforce visual assertions beyond smoke-level loading/binding

## Acceptance Criteria

- CI can catch backend-boundary violations in new QML-related code
- future QML tasks have a simple, copyable test pattern
