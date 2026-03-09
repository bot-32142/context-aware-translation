# Task 04: Test Harness, Fakes, and Boundary Enforcement

## Goal

Make the new architecture enforceable and testable before feature migration multiplies the surface area.

## Execute

Run after Task 02. It can overlap with Task 03, but final acceptance of
invalidation-driven refresh coverage should wait until Task 03 lands.

## Depends On

- [Task 00](00-foundation-boundaries.md)
- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 03](03-foundation-events-queue-contract.md)

## Must Read

- [Technical migration overview](../README.md)

## Scope

Add the technical guardrails needed for parallel work:
- import-boundary enforcement
- fake application services for UI tests
- contract tests for application services
- tests for invalidation-driven refresh and backend-owned action state
- feature-module scaffolding guidance for Qt

## Current Code To Inspect

- `pyproject.toml`
- existing tests under `tests/`
- `context_aware_translation/ui/`
- `context_aware_translation/workflow/`

## Deliverables

1. Import boundary checks in CI or local checks.
2. Fake service implementations or fixtures for UI tests.
3. Contract-test pattern for application services.
4. Optional feature scaffolding notes for `ui/features/` if that directory is introduced.

## Rules

- UI tests for migrated slices should not need SQLite or real LLM config.
- Import rules should fail fast when a migrated view imports backend internals directly.
- Tests for migrated slices should assert action enable/disable from application
  DTOs, not from widget-local preflight calls.
- Tests should cover invalidation + requery refresh for at least one migrated
  surface or shared presenter/controller.

## Acceptance Criteria

- architecture violations are mechanically catchable
- at least one migrated slice can be tested against a fake backend
- feature agents have a repeatable testing pattern
- direct `TaskEngine.preflight()` / `has_active_claims()` usage in migrated UI
  is mechanically catchable or clearly forbidden by test scaffolding
