# Phase 1: Setup

## Objective

Make setup understandable for non-technical users without throwing away the
existing step-based config/profile backend.

This phase reframes setup as:

- `App Settings` for reusable connections and shared workflow profiles
- `Project Settings` for target language, preset, and choosing either a shared
  workflow profile or a project-specific workflow profile

Both settings surfaces are dialogs or panes, not primary shell pages.

## User Problem

Today the user has to understand too much too early:

- which provider they want
- where credentials should live
- which models should be used for each workflow step
- whether a setting is app-wide or project-specific
- how raw config sections map to actual product behavior

The redesigned setup must answer only:

- what services the user already has
- what reusable connections are available
- which workflow profile will be used
- whether this project uses a shared profile or a project-specific profile

## Scope

Phase 1 covers:

- app settings dialog and pane
- provider-first setup wizard
- connection management
- capability testing as feedback only
- recommended workflow profile generation
- workflow profile editing
- project settings dialog and pane
- shared-profile vs project-profile model
- advanced setup sections for custom endpoints and explicit model edits

Phase 1 does not cover:

- queue behavior
- document workspace design
- shared terms design
- workflow execution UI outside setup
- backend storage redesign

## Core Model

### Reused backend model

The existing step-based config/profile backend remains the source of truth.

The UX reframes it as:

- **Connection**: saved provider credentials/settings
- **Workflow Profile**: user-facing wrapper over the existing step-based config payload
- **Shared Workflow Profile**: reusable app-level profile
- **Project-Specific Workflow Profile**: project-local profile derived from or independent of a shared profile

The wizard generates a concrete workflow profile. It does not introduce a new
routing abstraction.

### App Settings owns

- reusable service connections
- API keys and secrets
- known-provider defaults
- custom OpenAI-compatible base URLs
- shared workflow profiles
- step-level connection/model routing inside workflow profiles

### Project Settings owns

- target language
- project preset
- selected workflow profile
- optional project-specific workflow profile when needed

### Precedence

For each workflow step:

1. project-specific workflow profile
2. shared workflow profile
3. missing

## Capability Model

Setup still exposes capabilities, but capabilities are summary-only.

Required user-facing capabilities:

- `Translation`
- `Image text reading`
- `Image editing`

Optional secondary capability:

- `Reasoning and review`

Capabilities are used for:

- readiness summaries
- test feedback
- blocker messaging

Capabilities are not the primary editing surface.

Workflow profiles are used for:

- choosing which connection/model runs each step
- generating recommended defaults
- project-specific customization

## App Settings

### Purpose

`App Settings` is where users tell the app what services they have and manage
the shared setup reused across projects.

It should feel reusable and global:

- set it up once
- reuse it across projects
- edit only when connections or workflow profiles change

### Core Pane: App Settings

Required areas:

- connection summary
- workflow profile summary
- lightweight capability summary
- `Run setup wizard` CTA
- `Add connection` CTA
- `Workflow profiles` section
- collapsed `Advanced` section for custom-provider details only

### Provider-First Wizard

The wizard should ask what the user already has, not how they want to design a
profile.

Wizard steps:

1. choose providers already available
2. enter API keys
3. test capabilities
4. review recommended workflow profile
5. save app settings

Wizard output:

- saved connections
- a concrete shared workflow profile with explicit step -> connection + model choices

### Provider Cards

Known providers should have dedicated cards:

- `Gemini`
- `OpenAI`
- `DeepSeek`
- `Anthropic`
- `OpenAI-compatible / Custom`

Rules:

- known providers ask for API key first
- known providers do not expose base URL in the normal flow
- known providers auto-pick concrete models by default
- custom provider exposes base URL and model fields
- provider cards may include small helper text about what each provider is good at

### Capability Testing

Tests must answer what the configured services can do, not only whether they are
reachable.

Test results should map to:

- `Translation`
- `Image text reading`
- `Image editing`
- `Reasoning and review` when relevant

This capability output is feedback and readiness only. It is not the main setup
editing UI.

### Recommended Workflow Profile

After testing, the app must generate a recommended workflow profile.

Example:

- `OCR / text extraction -> Gemini / gemini-3-flash-preview`
- `Build terms -> DeepSeek / deepseek-chat`
- `Summary / context building -> DeepSeek / deepseek-chat`
- `Term translation -> DeepSeek / deepseek-chat`
- `Translation review / reasoning -> OpenAI / gpt-4.1-mini`
- `Document translation -> OpenAI / gpt-4.1-mini`
- `Manga text detection -> Gemini / gemini-3-flash-preview`
- `Manga translation -> Gemini / gemini-3-flash-preview`
- `Image reinsertion -> Gemini / gemini-3.1-flash-image-preview`

The user should then choose one of:

- `Use recommended profile`
- `Edit workflow profile`
- `Advanced`

### Workflow Profile Editor

Workflow profiles are the main advanced-friendly setup surface.

The editor should use the existing real step map, not a capability map.

Required rows:

- `Extractor`
- `Summarizer`
- `Glossary translator`
- `Translator`
- `Reviewer`
- `OCR`
- `Image reembedding`
- `Manga translator`
- `Translator batch`

Required columns:

- `Step`
- `Connection`
- `Model`

## Project Settings

### Purpose

`Project Settings` answers:

- what language is this project translating into
- what quality preset should it use
- which workflow profile is active
- does this project need a custom profile or can it reuse a shared one

### Core Pane: Project Settings

Required areas:

- target language
- project preset
- selected workflow profile summary
- workflow step summary
- `Use shared profile` / `Customize for this project` actions
- `Open App Settings` deep link when a required shared connection or profile is missing
- save action

### Project Settings Profile Selection

Project settings should show:

- the currently selected shared workflow profile
- whether a project-specific profile exists
- a short explanation of which profile will win
- a route summary for important workflow steps

Advanced controls may remain behind a secondary editor or expandable route
detail surface.

### Interaction Rules

- app settings changes remain global
- project settings changes remain local to the active project
- missing global dependencies deep-link to app settings instead of sending the
  user to a separate shell page
- saving project settings returns the user to `Work`

## Minimum States

App settings needs at least:

- no connections yet
- connections saved but no profile
- recommended profile ready
- shared profiles present
- custom provider advanced section open
- wizard in progress / review / saved

Project settings needs at least:

- no valid shared profile available
- shared profile selected
- project-specific profile selected
- missing dependency that requires app settings
- save completed

## Acceptance Criteria

- Users can understand the difference between app-wide reusable setup and project-specific setup.
- App settings supports both quick-start wizard flows and advanced workflow-profile editing.
- Project settings clearly supports either a shared workflow profile or a project-specific workflow profile.
- Settings remain secondary surfaces, not main navigation destinations.
