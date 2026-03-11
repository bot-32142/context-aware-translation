# Task 11: App Setup Slice

## Goal

Implement the app-level setup surface and provider-first wizard through application services.

## Execute

Start after Task 10. Can run in parallel with Task 12 once the shell exists.

## Depends On

- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 10](10-app-shell-navigation.md)

## Must Read

- [Setup UX](../../ux/phase1_setup.md)
- [UX journeys](../../ux/phase0/journeys.md)
- [Advanced controls UX](../../ux/phase6_advanced_controls.md)

## Current Code To Inspect

- `context_aware_translation/ui/views/profile_view.py`
- `context_aware_translation/ui/views/endpoint_profile_view.py`
- `context_aware_translation/ui/views/config_profile_view.py`
- `context_aware_translation/storage/library/book_manager.py`
- `context_aware_translation/storage/registry_db.py`

## Scope

Implement the new `App Setup` feature:
- list connections
- add/edit/delete/test connection
- provider-first wizard
- capability tests as readiness feedback
- recommended workflow profile generation
- workflow profile editing
- advanced endpoint/model editing behind a secondary affordance

Implementation note for the first migrated version:
- `Test connection` may infer capabilities from the selected provider type
  instead of performing live provider probing.
- This is acceptable for the slice because the application contract already
  supports replacing inference with real probing later.
- The wizard should save a concrete shared workflow profile, not a separate routing artifact.

## Ownership Boundary

Primary paths this task should own:
- `context_aware_translation/application/contracts/app_setup*.py`
- `context_aware_translation/application/services/app_setup*.py`
- `context_aware_translation/ui/features/app_setup/` or equivalent new app-setup UI module

Avoid touching Work, Terms, or document feature code.

## Acceptance Criteria

- App Setup is framed around connections and shared workflow profiles
- known providers are key-first
- custom provider path can still handle base URL/model config
- UI depends on application service contracts, not `BookManager` directly
- setup actions and blockers are rendered from backend query state
- setup refresh uses application invalidation events + requery, not direct
  profile-storage listeners
- capability tests are rendered as summary feedback, not capability-card editing UI
- if capability tests are provider-inferred rather than live-probed, that
  limitation must be explicit in task notes and user-facing copy
