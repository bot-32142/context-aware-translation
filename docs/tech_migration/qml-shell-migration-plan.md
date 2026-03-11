# QML Shell Migration Plan

## Purpose

This plan defines the next UI migration stage after the application-boundary
work already completed in `context_aware_translation/application/`.

The goal is not a greenfield rewrite. The goal is to replace the current
QWidget shell/chrome with Qt Quick / QML in phases while preserving:

- the existing `application/*` contracts, services, events, and errors
- the current PySide6 runtime and packaging model
- the already-migrated service-backed feature slices under `ui/features/`
- the ability to ship partial progress without breaking the desktop app

## Current Baseline

The codebase already has the backend boundary needed for this migration:

- `context_aware_translation/application/__init__.py`
- `context_aware_translation/application/composition.py`
- `context_aware_translation/application/contracts/*`
- `context_aware_translation/application/services/*`
- `context_aware_translation/application/events.py`

The remaining shell/lifetime work is now hybrid:

- `context_aware_translation/ui/main_window.py`
  - acts as the composition root and top-level lifetime manager
- `context_aware_translation/ui/window_controllers.py`
  - owns project-session and queue-dock orchestration extracted from `MainWindow`
- `context_aware_translation/ui/features/work_view.py`
  - owns project work-home behavior and nested document-workspace launching
- `context_aware_translation/ui/features/terms_view.py`
  - owns project/document terms behavior inside hosted shell chrome
- `context_aware_translation/ui/features/document_workspace_view.py`
  - owns document-section host wiring and export behavior

The repo now contains the initial QML / Qt Quick migration foundation under
`context_aware_translation/ui/qml/`, `ui/viewmodels/`, and `ui/shell_hosts/`,
and the plan below records the completed execution path plus the locked
architecture for follow-up work.

## Implementation Status

Landed:
- Q01 QML bootstrap and packaged resource loading
- Q02 viewmodel base and route-state helpers
- Q03 hybrid shell/dialog host infrastructure
- Q04 QML test harness and architecture guards
- Q10 app shell host
- Q11 project shell host
- Q12 document shell host
- Q13 queue shell host
- Q14 navigation target bridge refactor
- Q20 app settings dialog host
- Q21 project settings dialog host
- Q32 app settings internals to native QML
- Q33 project settings internals to native QML
- Q30 work-home QML chrome
- Q31 shared terms QML chrome
- Q34 document OCR QML chrome
- Q35 document-scoped terms QML chrome
- Q36 document translation QML chrome
- Q37 document images QML chrome
- Q38 document export QML chrome
- Q22 initial `MainWindow` decomposition via `ui/window_controllers.py`
- partial Q40 cleanup: obsolete `ui/features/project_shell_view.py` removed
- partial Q40 cleanup: obsolete `ui/features/project_setup_view.py` removed
- partial Q40 cleanup: `AppSetupView` page wrapper removed; only still-needed helper dialogs/forms remain
- Q40 final shell/dead-code cleanup
- Q41 packaging, i18n, and runtime hardening
- Q42 regression sweep and documentation cleanup

Current state:
- the QML shell migration plan is complete on this branch
- app/project/document/queue chrome is QML-hosted
- app/project settings are dialog-based rather than shell pages
- document local navigation is `OCR`, `Terms`, `Translation`, `Images`, `Export`

## Locked Direction

These decisions are fixed for this migration:

1. `application/*` remains the only backend boundary.
2. Do not reintroduce direct storage/workflow/core imports into UI.
3. Do not switch to React, Tauri, or another widget framework.
4. Preferred shell/chrome technology is Qt Quick / QML on top of PySide6.
5. Use a hybrid migration first.
   - Keep legacy QWidget feature panes temporarily.
   - Replace shell/chrome before rewriting every feature pane.
6. `App Settings` must become a dialog opened from the app menu, not a main page.
7. `Project Settings` must become a dialog opened from a gear action, not a main page.
8. No global left sidebar.
9. No project-level left sidebar.
10. `Work` and `Terms` remain the only primary project surfaces.
11. Inside a document workspace, use local left navigation for:
    - `OCR`
    - `Terms`
    - `Translation`
    - `Images`
    - `Export`

## Source Of Truth Note

This document supersedes older shell/navigation assumptions in:

- `docs/ux/phase0/architecture.md`
- `docs/ux/phase1_setup.md`
- `docs/ux/phase4_document_workspace.md`
- `docs/tech_migration/tasks/10-app-shell-navigation.md`
- `docs/tech_migration/tasks/22-document-workspace-shell.md`

Those earlier docs still describe the application-boundary migration correctly,
but this file remains the source of truth for shell/chrome sequencing and
should stay aligned with the UX docs as they are updated.

## Technical Strategy

### Hybrid Host Model

Do not try to embed legacy QWidget feature panes directly inside QML scenes.
That path is high-risk and unnecessary for the first migration wave.

Use this host model instead:

1. Keep `QApplication` and an initial QWidget-based main window.
2. Introduce QML-driven shell hosts using `QQuickWidget` or equivalent
   QWidget-compatible Qt Quick hosting.
3. Place shell chrome and navigation in QML.
4. Keep legacy feature panes in sibling QWidget content hosts managed by Python.
5. Let Python routing synchronize:
   - current app shell route
   - current project route
   - current document route
   - active modal/dialog state

This gives QML control over layout and navigation while avoiding early
cross-technology embedding problems.

### Dependency Rule

The dependency rule for new code is:

```text
QML -> QObject viewmodels / presenters -> application.services/contracts/events
```

QML must never call storage/workflow/runtime APIs directly.

### New Package Direction

Expected additions:

```text
context_aware_translation/ui/
  qml/
    common/
    app/
    project/
    document/
    dialogs/
    queue/
  viewmodels/
    base.py
    router.py
    app_shell.py
    project_shell.py
    document_shell.py
    queue_shell.py
    app_settings_dialog.py
    project_settings_dialog.py
  shell_hosts/
    app_shell_host.py
    project_shell_host.py
    document_shell_host.py
    dialog_host.py
```

Legacy `ui/features/*` remains in place until each pane reaches parity.

### Viewmodel Rules

All QML-facing Python objects should:

- inherit from `QObject`
- expose readonly query state via properties/signals
- expose imperative actions only for user intent
- call `application.services` for commands and queries
- translate application events into minimal refresh/requery behavior
- avoid owning backend persistence or workflow details

### Testing Rules

Add tests in layers:

1. Viewmodel tests
   - no QML engine needed
   - use fake application services and fake event bus
2. Host integration tests
   - verify route changes, dialog opening, and legacy-pane mounting
3. QML smoke tests
   - verify components load and bind to viewmodels
4. Architecture guard tests
   - ensure `ui/viewmodels` and `ui/shell_hosts` do not import backend internals

## Execution Waves

### Wave A: Bootstrap And Guardrails

Outcome:
- QML can be loaded and packaged
- a Python viewmodel pattern exists
- hybrid shell hosting is possible

### Wave B: Shell Replacement

Outcome:
- app shell, project shell, document shell, and queue shell are QML-driven
- current feature panes still run through legacy QWidget hosts

### Wave C: Settings Conversion

Outcome:
- app/project settings stop being shell pages and become modal/dialog flows
- legacy settings forms may still be hosted temporarily

### Wave D: Feature Pane Replacement

Outcome:
- major QWidget feature panes are replaced one by one with QML equivalents

### Wave E: Cleanup And Release Hardening

Outcome:
- old shell code is removed
- packaging, i18n, and tests are updated for the new runtime shape

## Task Graph

Each task below is intentionally small enough to hand to one subagent.
Ownership boundaries are explicit to reduce merge conflicts.

### Q00: QML Migration ADR And Doc Alignment

Goal:
- record the shell IA change and hybrid-host strategy

Depends on:
- none

Primary ownership:
- `docs/tech_migration/qml-shell-migration-plan.md`
- `docs/ux/phase0/architecture.md`
- `docs/ux/phase1_setup.md`
- `docs/ux/phase4_document_workspace.md`

Deliverables:
- doc updates reflecting no sidebars, settings-as-dialogs, and document local nav
- explicit note that application-boundary work is reused, not replaced

Acceptance criteria:
- shell IA conflicts are removed from docs
- later implementation tasks can cite one consistent shell spec

### Q01: QML Bootstrap And Resource Loading

Goal:
- add the minimum runtime needed to load QML safely in dev and packaged builds

Depends on:
- Q00

Primary ownership:
- `context_aware_translation/ui/main.py`
- new `context_aware_translation/ui/qml/`
- packaging resource declarations if needed

Deliverables:
- QML resource loader
- startup-safe engine/widget initialization
- fallback error surfacing comparable to current QWidget startup path

Acceptance criteria:
- a trivial QML shell can load in the desktop app
- packaged/local runs resolve QML assets consistently

### Q02: Viewmodel Base Pattern

Goal:
- establish a reusable QML-facing Python API pattern

Depends on:
- Q01

Primary ownership:
- new `context_aware_translation/ui/viewmodels/base.py`
- new `context_aware_translation/ui/viewmodels/router.py`
- tests for viewmodel base behavior

Deliverables:
- base viewmodel conventions
- route state object model
- signal/property refresh helpers

Acceptance criteria:
- later tasks can build shell viewmodels without inventing incompatible patterns

### Q03: Hybrid Shell Host Infrastructure

Goal:
- create Python host widgets that combine QML chrome with legacy QWidget content hosts

Depends on:
- Q01
- Q02

Primary ownership:
- new `context_aware_translation/ui/shell_hosts/`

Deliverables:
- generic host for:
  - QML navigation/header region
  - QWidget content region
  - route-driven pane swapping
- dialog host helper for modal flows

Acceptance criteria:
- one host can mount a legacy QWidget pane and switch routes without recreating the whole app window

### Q04: QML Test Harness And Boundary Guards

Goal:
- keep QML migration safe in CI

Depends on:
- Q01
- Q02

Primary ownership:
- `tests/ui/`
- `tests/architecture/`

Deliverables:
- QML/viewmodel smoke-test pattern
- import-boundary guard for `ui/viewmodels` and `ui/shell_hosts`

Acceptance criteria:
- CI can fail fast on backend-boundary regressions in new QML code

### Q10: App Shell Host

Goal:
- replace app-level left-nav shell with a QML app shell

Depends on:
- Q03
- Q04

Primary ownership:
- `context_aware_translation/ui/main_window.py`
- new `context_aware_translation/ui/viewmodels/app_shell.py`
- new `context_aware_translation/ui/qml/app/`
- new `context_aware_translation/ui/shell_hosts/app_shell_host.py`

Deliverables:
- top-level app shell with `Projects` as primary surface
- app menu entry for `App Settings`
- project opening/closing routed through new shell host

Acceptance criteria:
- no global left sidebar remains in the primary shell
- `Projects` can open a project through the new route model
- queue and settings affordances are present but may still open placeholder hosts

### Q11: Project Shell Host

Goal:
- replace `ProjectShellView` tabs with a QML project overview shell

Depends on:
- Q10

Primary ownership:
- `context_aware_translation/ui/main_window.py`
- new `context_aware_translation/ui/viewmodels/project_shell.py`
- new `context_aware_translation/ui/qml/project/`
- new `context_aware_translation/ui/shell_hosts/project_shell_host.py`

Deliverables:
- project header
- `Work` / `Terms` top navigation only
- project gear action for `Project Settings`
- queue affordance in project shell

Acceptance criteria:
- project `Setup` is no longer a tab/page
- `Work` and `Terms` are the only primary project routes
- legacy `WorkView` and `TermsView` can still be mounted as hosted panes

### Q12: Document Shell Host

Goal:
- replace `DocumentWorkspaceView` tab shell with QML document chrome

Depends on:
- Q11

Primary ownership:
- `context_aware_translation/ui/features/document_workspace_view.py`
- new `context_aware_translation/ui/viewmodels/document_shell.py`
- new `context_aware_translation/ui/qml/document/`
- new `context_aware_translation/ui/shell_hosts/document_shell_host.py`

Deliverables:
- document header
- back-to-work action
- local left nav for `OCR`, `Terms`, `Translation`, `Images`, `Export`
- hosted legacy pane mounting per section

Acceptance criteria:
- document tabs are gone from the primary document shell
- route changes can mount current QWidget panes without behavior regressions

### Q13: Queue Drawer QML Shell

Goal:
- move queue chrome from `QDockWidget` into a QML secondary surface

Depends on:
- Q10

Primary ownership:
- `context_aware_translation/ui/features/queue_drawer_view.py`
- new `context_aware_translation/ui/viewmodels/queue_shell.py`
- new `context_aware_translation/ui/qml/queue/`

Deliverables:
- QML queue drawer/panel shell
- current queue list/detail behavior exposed through a viewmodel

Acceptance criteria:
- queue remains secondary to the main shell
- navigation targets emitted from queue items still route correctly

### Q14: Navigation Target Bridge Refactor

Goal:
- centralize route translation between application navigation targets and shell routes

Depends on:
- Q10
- Q11
- Q12

Primary ownership:
- `context_aware_translation/ui/main_window.py`
- new `context_aware_translation/ui/viewmodels/router.py`
- route mapping tests

Deliverables:
- one route translation layer for:
  - app shell
  - project shell
  - document shell
  - dialogs

Acceptance criteria:
- route logic no longer lives in scattered widget callbacks
- queue and feature panes use the same routing bridge

### Q20: App Settings Dialog Host

Goal:
- remove app setup from the app shell as a full page

Depends on:
- Q10
- Q14

Primary ownership:
- `context_aware_translation/ui/features/app_settings_pane.py`
- new `context_aware_translation/ui/viewmodels/app_settings_dialog.py`
- new `context_aware_translation/ui/qml/dialogs/app_settings/`
- new `context_aware_translation/ui/shell_hosts/app_settings_dialog_host.py`

Deliverables:
- modal or sheet presentation from app menu
- QML-backed app settings pane body
- legacy connection/profile editor dialogs can remain temporary Python bridges

Acceptance criteria:
- app setup no longer occupies a primary app route
- dialog can open, close, refresh, and deep-link correctly

### Q21: Project Settings Dialog Host

Goal:
- remove project setup from the project shell as a full page

Depends on:
- Q11
- Q14

Primary ownership:
- `context_aware_translation/ui/features/project_settings_pane.py`
- `context_aware_translation/ui/features/workflow_profile_editor.py`
- new `context_aware_translation/ui/viewmodels/project_settings_dialog.py`
- new `context_aware_translation/ui/qml/dialogs/project_settings/`
- new `context_aware_translation/ui/shell_hosts/project_settings_dialog_host.py`

Deliverables:
- project settings dialog launched from project gear action
- QML-backed project settings pane body
- `WorkflowRoutesEditor` may remain the temporary advanced-route bridge

Acceptance criteria:
- project setup no longer appears as a project tab/page
- work/setup blocker routing can open this dialog or app settings as appropriate

### Q22: Main Window Decomposition

Goal:
- shrink `MainWindow` into composition + lifetime management only

Depends on:
- Q10
- Q13
- Q14
- Q20
- Q21

Primary ownership:
- `context_aware_translation/ui/main_window.py`

Deliverables:
- move shell-specific routing and pane orchestration into dedicated hosts/viewmodels
- keep close handling, status messages, and app lifetime management coherent

Acceptance criteria:
- `MainWindow` no longer owns most shell policy
- shell code is testable outside the full app window

### Q30: Work Home QML Pane

Goal:
- replace the project work-home QWidget chrome while preserving service behavior

Depends on:
- Q11

Primary ownership:
- `context_aware_translation/ui/features/work_view.py`
- new `context_aware_translation/ui/qml/project/work_home/`
- related viewmodel additions

Deliverables:
- QML work home layout for document list, context strip, import controls
- continued reuse of `WorkService`

Acceptance criteria:
- work home no longer depends on QWidget table/layout chrome
- document opening still routes into document shell

### Q31: Shared Terms QML Pane

Goal:
- replace top-level project terms chrome

Depends on:
- Q11

Primary ownership:
- `context_aware_translation/ui/features/terms_view.py`
- `context_aware_translation/ui/features/terms_table_widget.py`
- new `context_aware_translation/ui/qml/project/terms/`

Acceptance criteria:
- project-wide terms is rendered through QML while keeping the same service boundary

### Q32: App Settings Internals To Native QML

Goal:
- replace hosted QWidget internals inside app settings dialog

Depends on:
- Q20

Primary ownership:
- app-settings-specific QML/viewmodel files

Delivered:
- `context_aware_translation/ui/features/app_settings_pane.py`
- `context_aware_translation/ui/viewmodels/app_settings_pane.py`
- `context_aware_translation/ui/qml/dialogs/app_settings/AppSettingsPane.qml`
- legacy connection/profile editor dialogs remain temporary Python bridges

Acceptance criteria:
- app settings dialog no longer depends on the old QWidget page internals

### Q33: Project Settings Internals To Native QML

Goal:
- replace hosted QWidget internals inside project settings dialog

Depends on:
- Q21

Primary ownership:
- project-settings-specific QML/viewmodel files

Delivered:
- `context_aware_translation/ui/features/project_settings_pane.py`
- `context_aware_translation/ui/viewmodels/project_settings_pane.py`
- `context_aware_translation/ui/qml/dialogs/project_settings/ProjectSettingsPane.qml`
- `WorkflowRoutesEditor` remains the temporary hosted advanced-route bridge

Acceptance criteria:
- project settings dialog no longer depends on the old QWidget page internals

### Q34: Document OCR QML Pane

Goal:
- replace OCR pane internals under the new document shell

Depends on:
- Q12

Primary ownership:
- `context_aware_translation/ui/features/document_ocr_tab.py`
- new QML/viewmodel files for OCR

Acceptance criteria:
- OCR pane is QML-rendered and still uses `DocumentService`

### Q35: Document Terms QML Pane

Goal:
- replace document-scoped terms pane

Depends on:
- Q12
- Q31

Primary ownership:
- document-terms-specific QML/viewmodel files

Acceptance criteria:
- document terms remains a filtered view over shared terms

### Q36: Document Translation QML Pane

Goal:
- replace document translation pane

Depends on:
- Q12

Primary ownership:
- `context_aware_translation/ui/features/document_translation_view.py`
- translation QML/viewmodel files

Acceptance criteria:
- translation pane is QML-rendered with parity on editing and status handling

### Q37: Document Images QML Pane

Goal:
- replace image inspection/re-run pane

Depends on:
- Q12

Primary ownership:
- `context_aware_translation/ui/features/document_images_view.py`
- image-pane QML/viewmodel files

Acceptance criteria:
- image setup blockers and actions still route correctly

### Q38: Document Export QML Pane

Goal:
- replace document export pane and export dialogs

Depends on:
- Q12

Primary ownership:
- export-related code in `document_workspace_view.py`
- export-pane QML/viewmodel files

Acceptance criteria:
- document export works from QML and retains blocker/format handling

### Q40: Remove Old Shell Code

Goal:
- delete obsolete QWidget shell layers once parity is reached

Depends on:
- Q22
- Q30
- Q31
- Q32
- Q33
- Q34
- Q35
- Q36
- Q37
- Q38

Primary ownership:
- `context_aware_translation/ui/main_window.py`
- `context_aware_translation/ui/window_controllers.py`
- old shell wrappers no longer referenced

Acceptance criteria:
- no obsolete shell tabs/page/dock logic remains
- only still-needed legacy panes survive

### Q41: Packaging, i18n, And Runtime Hardening

Goal:
- make the QML runtime production-safe

Depends on:
- Q10 minimum; should finish after Q40

Primary ownership:
- `context_aware_translation/ui/main.py`
- resource packaging config
- translation loading for QML strings
- installer/build config as needed

Acceptance criteria:
- QML assets load in dev and packaged builds
- language switching still works
- startup failures surface clearly

Delivered:
- explicit Qt QML module bundling in `cat-ui.spec`
- bundled Qt translation catalogs plus frozen-runtime lookup fallback
- startup error handling widened to cover translation loading and QML host construction
- nested-QML bootstrap coverage and live host retranslation tests

### Q42: Regression Sweep And Dead Code Cleanup

Goal:
- finalize the migration and remove stale helpers/tests/docs

Depends on:
- Q40
- Q41

Primary ownership:
- affected tests/docs/dead modules

Acceptance criteria:
- no dead shell path remains
- docs and tests reflect the new shell architecture

Delivered:
- stale `AppSetupView` / `ProjectSetupView` paths removed from live code and tests
- `zh_CN.ts` / `zh_CN.qm` regenerated against the current pane/dialog contexts
- migration, AGENTS, and UX docs updated to the current shell IA
- full `tests/ui` plus `tests/architecture/test_qml_ui_boundaries.py` sweep passed on the completed branch

## Recommended Parallelization

### Stage 1

Run mostly sequentially:
- Q00
- Q01
- Q02
- Q03
- Q04

### Stage 2

Can split across agents after Stage 1:
- Agent A: Q10 App shell host
- Agent B: Q13 Queue drawer shell

Then:
- Agent A or C: Q11 Project overview shell
- Agent D: Q20 App settings dialog host

### Stage 3

After Q11:
- Agent C: Q12 Document shell host
- Agent D: Q21 Project settings dialog host
- Agent E: Q30 Work home QML pane
- Agent F: Q31 Shared terms QML pane

### Stage 4

After Q12:
- Agent G: Q34 Document OCR QML pane
- Agent H: Q35 Document terms QML pane
- Agent I: Q36 Document translation QML pane
- Agent J: Q37 Document images QML pane
- Agent K: Q38 Document export QML pane

### Stage 5

Finish with:
- Agent L: Q22 Main window decomposition
- Agent M: Q40 old shell removal
- Agent N: Q41 packaging/i18n hardening
- Agent O: Q42 regression sweep

## First Implementation Slice Recommendation

The safest first implementation slice is:

1. Q01 QML bootstrap
2. Q02 viewmodel base
3. Q03 hybrid shell host
4. Q04 test harness
5. Q10 app shell host
6. Q20 app settings dialog host

That slice proves:

- QML can coexist with the current app
- app settings can leave the primary shell
- routing can move into a new shell model

without forcing immediate rewrites of `Work`, `Terms`, or document tools.
