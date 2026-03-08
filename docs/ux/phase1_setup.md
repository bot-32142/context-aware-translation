# Phase 1: Setup

## Objective

Make setup understandable for non-technical users without removing the ability
to manage endpoints, models, and custom providers.

This phase replaces config-first setup with a two-layer model:
- `App Setup` for reusable connections and defaults
- `Project Setup` for per-project language, preset, and routing selection

## User Problem

Today the user has to understand too much too early:
- which provider they want
- which features require which endpoint
- where credentials should live
- whether a setting is app-wide or project-specific
- which models should be used for each capability

The redesigned setup must answer only:
- what services the user already has
- what the app can do with them
- which defaults will be used
- what, if anything, this project overrides

## Scope

Phase 1 covers:
- `App Setup` landing page
- provider-first setup wizard
- connection management
- capability testing
- recommended default routing generation
- `Project Setup` landing page
- app-default vs project-override model
- advanced setup sections for endpoints and models

Phase 1 does not cover:
- queue behavior
- document workspace design
- shared Terms design
- workflow execution UI outside setup

## Core Model

### App Setup owns
- reusable service connections
- API keys and secrets
- known-provider defaults
- custom OpenAI-compatible base URLs
- recommended model defaults
- default routing for each capability

### Project Setup owns
- target language
- project preset
- whether the project uses app defaults
- project-specific capability overrides when needed

### Precedence

For each capability:
1. project override
2. app default
3. missing

## Capability Model

Setup must expose capabilities, not engine internals.

Required user-facing capabilities:
- `Translation`
- `Image text reading`
- `Image editing`

Optional secondary capability:
- `Reasoning and review`

Each capability has these states:
- `Ready`
- `Missing`
- `Partial`
- `Unsupported for this workflow`

## App Setup

### Purpose

`App Setup` is where users tell the app what services they have.

It should feel reusable and global:
- set it up once
- reuse it across projects
- edit only when providers or defaults change

### Core Screen: App Setup Landing

Required areas:
- connection summary
- capability coverage summary
- default routing summary
- `Run setup wizard` CTA
- `Add connection` CTA
- collapsed `Advanced` section

### Core Screen: Provider-First Wizard

The wizard should ask what the user already has, not how they want to design a
profile.

Wizard steps:
1. choose providers already available
2. enter API keys
3. test capabilities
4. review recommended routing
5. save app defaults

### Provider Cards

Known providers should have dedicated cards:
- `Gemini`
- `OpenAI`
- `DeepSeek`
- `Anthropic`
- `OpenAI-compatible / Custom`

Rules:
- known providers ask for API key first
- known providers hide base URL by default
- custom provider exposes base URL and default models
- provider cards may include small helper text about what each provider can be
  used for

### Capability Testing

Tests must answer what the provider can do, not only whether it is reachable.

Test results should map to:
- `Translation`
- `Image text reading`
- `Image editing`

### Recommended Routing

After testing, the app must generate a recommended default routing summary.

Example:
- `Translation -> DeepSeek`
- `Image text reading -> Gemini`
- `Image editing -> Gemini`

The user should then choose one of:
- `Use recommended setup`
- `Adjust routing`
- `Advanced`

### Advanced in App Setup

Advanced should be collapsed by default.

It may reveal:
- exact endpoint/base URL
- model names
- per-capability model mapping
- connection metadata
- fallback behavior if that becomes part of setup

## Project Setup

### Purpose

`Project Setup` answers:
- what language this project targets
- which quality preset it uses
- whether it inherits app defaults or overrides them

### Core Screen: Project Setup Landing

Required areas:
- target language
- project preset
- capability cards
- `Use app defaults` summary
- per-capability `Override for this project` affordance
- `Open App Setup` deep link when a global connection is missing
- collapsed `Advanced` section

### Project Capability Cards

Each capability card should show:
- current status
- current source: app default, project override, or missing
- current selected connection
- whether the project is inheriting app defaults
- CTA:
  - `Use app defaults`
  - `Override for this project`
  - `Open App Setup`

### Project Setup Interaction Rules

- default behavior is inherit app defaults
- overrides are opt-in
- project setup should not expose raw endpoint editing by default
- if the needed connection does not exist globally, route the user to
  `App Setup`
- saving project setup returns the user to `Work`

## Interaction Rules

- provider choice comes before endpoint/model choice
- known-provider setup is key-first, not endpoint-first
- default setup should avoid raw model choice unless auto-selection failed
- the app must always explain whether a missing piece is app-level or
  project-level
- setup should not imply that every project needs custom routing
- advanced sections should expand in place, not switch the entire app into a
  different mode

## Component Design Package

Components that need dedicated design:
- app setup landing shell
- provider card
- provider selection grid
- API key entry panel
- connection test result row
- capability coverage matrix
- recommended routing card
- project setup shell
- project capability card
- inherit / override control
- advanced setup section
- success / failure state panels

## Required States

App Setup needs at least:
- no connections
- one known provider configured
- mixed providers configured
- capability coverage partial
- fully ready
- custom provider configured
- test failed

Project Setup needs at least:
- app defaults available
- app defaults missing
- inherit all
- one capability overridden
- project blocked by missing setup
- project fully ready

## Design Tasks

1. Wireframe the `App Setup` landing page.
2. Wireframe the provider-first wizard.
3. Define the provider card states.
4. Define capability testing copy and result states.
5. Define the recommended routing summary.
6. Wireframe the `Project Setup` page.
7. Define inherit-vs-override interactions.
8. Define the advanced setup sections for custom endpoints and model overrides.
9. Prototype the first-run flow from project -> app setup wizard -> project setup -> work.

## Acceptance Criteria

- A user can set up common providers without learning endpoints first.
- A user can understand what the app can and cannot do from capability tests.
- App-wide connections and project-specific choices are visibly distinct.
- The app can generate a default routing map from supplied providers.
- Advanced endpoint/model management exists, but does not block normal setup.
