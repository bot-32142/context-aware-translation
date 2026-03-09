# UI Feature Testing Pattern

Use this pattern for migrated UI slices that depend on the application boundary.

## Rules

1. Do not instantiate `BookManager`, `SQLiteBookDB`, repositories, or `TaskEngine` in migrated feature tests.
2. Build tests around application DTOs and invalidation events.
3. Assert button state from backend-provided query data, not from widget-local preflight logic.
4. Trigger refresh through application invalidation events and then requery.

## Test Harness

Reusable test fakes live in:
- [tests/application/fakes.py](/Users/mingqiz/.codex/worktrees/f999/context-aware-translation/tests/application/fakes.py)

The expected harness shape is:
- fake application services with deterministic DTO state
- `InMemoryApplicationEventBus`
- a thin presenter/controller/widget binding that:
  - performs an initial query
  - subscribes to invalidation events
  - reruns the query on relevant invalidation

## Minimal Pattern

1. Create fake service state.
2. Instantiate the feature/controller with fake services and event bus.
3. Call initial `load()`.
4. Mutate the fake service state.
5. Publish the relevant invalidation event.
6. Assert that the surface reloaded and now reflects the new DTOs.

Reference example:
- [tests/application/test_ui_harness_pattern.py](/Users/mingqiz/.codex/worktrees/f999/context-aware-translation/tests/application/test_ui_harness_pattern.py)

## Boundary Enforcement

Architecture tests live in:
- [tests/architecture/test_migrated_ui_boundaries.py](/Users/mingqiz/.codex/worktrees/f999/context-aware-translation/tests/architecture/test_migrated_ui_boundaries.py)

These tests are intended to fail when migrated UI code:
- imports backend internals directly
- calls raw task-engine preflight helpers directly

## Migration Guidance

For a migrated feature slice:
- keep the view thin
- keep refresh logic in a small presenter/controller/binding layer if needed
- subscribe only to the invalidation events relevant to that surface
- requery via the application service after invalidation instead of patching local state heuristically
