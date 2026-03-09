# UX Architecture

## Objective

Redesign the app from a tool-tab UI into a guided translation workspace without
changing the underlying ordered-document, context-tree, or task-engine model.

The app must present the workflow users actually have:
- an app owns reusable service connections and workflow profiles
- a `Project` contains an ordered stack of `Documents`
- earlier documents shape later context
- users move the stack forward through explicit actions
- concurrency and conflicts exist, but they are secondary UI

## Locked Product Model

User-facing nouns:
- `Project`: current `book`
- `Document`: current ordered document unit
- `Context Frontier`: the furthest document whose OCR/context state is valid for
  downstream work
- `Terms`: the shared glossary for the current project
- `App Setup`: global service connections, workflow profiles, and provider wizard
- `Project Setup`: project-specific language, preset, and workflow profile selection
- `Action`: a user-triggered operation such as reading text, building terms,
  translating, reinserting text, or exporting
- `Issue`: something that needs attention, such as a blocker or failed action

Not user-facing on default surfaces:
- task types
- handler names
- resource claims
- endpoint terminology
- context-tree implementation details
- model-level configuration

## Shell Model

The redesign has two shells.

### App Shell

Purpose:
- let users create or open projects
- hold global reusable service configuration
- host the provider-first setup wizard

App-level destinations:
- `Projects`
- `App Setup`

### Project Shell

Purpose:
- let users process one ordered document stack
- expose the shared Terms surface for that project
- expose project-specific setup and routing

Project-level destinations:
- `Work`
- `Terms`
- `Setup`

Secondary global surface:
- `Queue Drawer`

Document-scoped tools live under `Work` inside a document workspace. This
replaces the current feature-tab model where `Import`, `OCR Review`,
`Glossary`, `Translate`, `Reembedding`, and `Export` are siblings.

## Screen Roles

### Projects

This is outside the project shell.

Purpose:
- list existing projects
- create a new project
- open a project
- surface whether app setup is incomplete before the user enters a project

### App Setup

This is outside the project shell.

Purpose:
- create and edit reusable service connections
- run a provider-first setup wizard
- generate a recommended workflow profile from available providers
- let users edit shared workflow profiles when needed
- treat workflow profiles as user-facing wrappers over the existing step-based config payload
- expose raw endpoint controls only for custom providers or explicit advanced edits

### Work

This is the default project home screen.

Purpose:
- show the ordered document stack
- show the context frontier
- show what is blocked
- let each document row surface one primary action
- let users open a document workspace for detailed work

Core elements:
- project header
- context / blocker strip
- ordered document list
- row-level primary actions

The row action should usually route the user into the correct document tab
rather than directly executing work.

### Document Workspace

This is a nested surface under `Work`.

Purpose:
- hold document-scoped tools in one place
- keep OCR, Terms, Translation, Images, and Export close to the current document

Sections inside the document workspace:
- `Overview`
- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

### Terms

This is the only shared glossary surface inside a project.

Purpose:
- provide the canonical project-wide Terms table
- support shared term review, translation, filtering, import, and export
- stay visually close to the current table UI

Document `Terms` is a filtered view of this same data, not a separate glossary.

### Project Setup

This is the `Setup` destination inside a project.

Purpose:
- choose target language and project preset
- choose which workflow profile the project uses
- optionally customize a project-specific workflow profile when needed
- deep-link to `App Setup` when global connections are missing or insufficient

### Queue Drawer

This is the concurrency and task-monitoring surface.

Purpose:
- show running, queued, blocked, failed, and completed actions
- support retry/cancel/delete
- explain blocking reasons without requiring users to understand engine internals

The queue drawer is always secondary. It must never become the default shell.

## Complexity Control Model

There is no global Simple/Pro mode for the entire product.

Instead:
- `Work`, `Terms`, and document workspace keep one stable UX model
- `Setup` carries most of the complexity management
- advanced controls appear as collapsible sections, drawers, or detail panels
- default surfaces stay plain-language and low-noise

Advanced controls are allowed when they add real control, especially in:
- `App Setup`
- `Project Setup`
- `Queue` details
- document-level rerun and diagnostics panels


## Setup Implementation Principle

Setup is a UX reframing over the existing step-based config/profile backend.

The backend model stays the same in substance:
- saved provider connections
- saved step-based config payloads
- shared profiles and project-specific config

The UX renames and organizes that model as:
- `Connections`
- `Workflow Profiles`
- `Project Setup` choosing a shared profile or a project-specific profile

The setup wizard generates a concrete saved workflow profile. It does not create
a separate routing abstraction.

## Setup Model

### App Setup owns
- reusable provider connections
- API keys and secrets
- known-provider defaults
- custom base URLs
- shared workflow profiles
- step-level connection and model routing inside workflow profiles

### Project Setup owns
- target language
- project quality preset
- selected workflow profile
- optional project-specific workflow profile when necessary

### Precedence rule

For each workflow step:
1. project-specific workflow profile
2. shared workflow profile
3. missing

## Core Interaction Rules

These behaviors are fixed and must be reflected clearly in the UX.

- Document order is canonical.
- The context frontier is visible and user-readable.
- OCR is always explicit-user-run.
- Manga translation is always explicit-user-run.
- Build Terms is explicit.
- `Build Terms` is owned by document `Terms`.
- Term edits do not auto-trigger translation.
- OCR edits do not auto-trigger translation.
- Image reinsertion is always explicit.
- Expensive downstream work is never silently scheduled after manual edits.
- Users must always see why work is blocked.
- Setup must distinguish clearly between app-level and project-level changes.

## Action Hierarchy

The app should always favor explicit, scoped actions over global wizard-like
controls.

Primary project actions are row- or document-scoped:
- `Open`
- `Open OCR`
- `Open Terms`
- `Open Translation`
- `Open Images`
- `Export`

Shared Terms actions:
- `Translate pending`
- `Review`
- `Filter noise`
- `Import`
- `Export`

Setup actions:
- `Open App Setup`
- `Use recommended profile`
- `Use shared profile`
- `Edit workflow profile`
- `Customize for this project`
- `Edit project profile`
- `Test connection`
- `Advanced`

Direct-execution rule:
- `Work` should mostly navigate users to the correct document tab
- `Export` is the main exception and may remain a direct row action
- direct export should open a small export dialog or sheet, not a separate
  top-level screen

## Blocked-State Taxonomy

Every blocked state shown in the UI must map to one of these categories:
- `Needs setup`
- `Needs earlier document first`
- `Already running elsewhere`
- `Needs review`
- `Nothing to do`

The app should never show internal conflict language first. Technical detail
can exist behind a details affordance.

## Home-Screen Logic

The Work screen should act like an editorial operations desk.

For each document row, the UI should answer:
- where is this document in the order
- what its current state is
- whether it is blocked
- what the one primary action is

For the project overall, the UI should answer:
- how far the context frontier has advanced
- which document is currently blocking progress
- whether project setup is sufficient
- whether the missing piece is app-level setup or project-level setup

## Scope Boundary

Phase 0 locks:
- nouns
- app shell vs project shell
- top-level IA
- document-workspace role
- setup model
- screen roles
- interaction rules
- blocked-state taxonomy

Phase 0 does not lock:
- visual style
- component layouts below the screen-role level
- implementation sequence
