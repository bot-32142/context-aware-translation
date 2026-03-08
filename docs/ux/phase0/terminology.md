# Terminology and Copy Matrix

## Copy Principles

- Default surfaces use outcome language, not implementation language.
- Advanced sections may expose technical labels, but should keep plain-language
  aliases nearby.
- The same concept should not be renamed differently on different screens.
- Blocked and error messages must describe what the user should do next.
- Setup copy must distinguish clearly between app-level and project-level scope.

## Primary Vocabulary

| Internal / Current Term | Default UI | Advanced Details | Notes |
| --- | --- | --- | --- |
| Book | Project | Project | `Project` is the canonical user-facing term |
| Document | Document | Document | Keep this stable |
| OCR | Read text from images | OCR / Read text from images | `OCR` can appear in advanced details |
| Glossary | Terms | Glossary / Terms | `Terms` is the locked user-facing label |
| Build Glossary | Build Terms | Build glossary / Build Terms | Meaning is term extraction + occurrence mapping |
| Glossary Translation | Translate terms | Glossary translation | Keep user focus on outcome |
| Review Terms | Review terms | Glossary review | |
| Translation | Translate | Translation | |
| Manga Translation | Translate manga pages | Manga translation | Use page language on default surfaces |
| Image Reembedding | Put text back into images | Image reembedding | Avoid `reembedding` on default surfaces |
| Batch Translation | Async cloud batch | Batch translation | Only expose in advanced details where useful |
| Profile | Service setup | Profile | Prefer `service setup` in setup UI |
| Endpoint | Service connection | Endpoint | `Endpoint` belongs in advanced sections |
| Model | Recommended model | Model | Hide model choice by default |
| Context Tree | Context memory | Context tree | Hide on default surfaces |
| Claim Conflict | Blocked by another running action | Claim conflict | Hide on default surfaces |
| Task | Background action | Task | `Task` should not be a primary noun |
| Global Setup | App Setup | App Setup | Reusable connections and defaults |
| Project Config | Project Setup | Project Setup | Project-specific routing and language |

## Screen Names

Locked app-level labels:
- `Projects`
- `App Setup`

Locked project-level labels:
- `Work`
- `Terms`
- `Setup`

Global utility surface:
- `Queue`

Document workspace labels:
- `Overview`
- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

Avoid using current feature-tab names as top-level navigation labels.

## Status Language

Use the same status labels everywhere unless the context strongly requires more
detail.

Primary statuses:
- `Ready`
- `Running`
- `Blocked`
- `Failed`
- `Done`
- `Cancelled`

Secondary qualifiers:
- `Needs setup`
- `Waiting on earlier documents`
- `Needs review`
- `No work remaining`

## Blocker Copy Rules

Preferred blocker phrasing:
- `Finish App Setup to continue.`
- `Finish Project Setup to continue.`
- `Set up image text reading to continue.`
- `Finish reading text in earlier documents first.`
- `Another action is already changing this document.`
- `Review this page before continuing.`
- `There is nothing left to do here.`

Avoid on default surfaces:
- `task claims conflict`
- `validate_run failed`
- `missing ocr_config`
- `handler rejected action`
- `resource lock`

These can appear in diagnostics or advanced details.

## Dominant CTA Labels

Use these exact high-level CTA labels as defaults:
- `Fix setup`
- `Open App Setup`
- `Use app defaults`
- `Override for this project`
- `Use recommended setup`
- `Advanced`

Use these operation CTAs:
- `Read text`
- `Translate`
- `Build Terms`
- `Put text back into images`
- `Export`
- `Open`
- `Open OCR`
- `Open Terms`
- `Open Translation`
- `Open Images`

Document CTAs:
- `Save`
- `Retry`
- `Rerun`
- `Retranslate`
- `Test connection`

## Banned Terms on Default Surfaces

These terms should not appear as primary UI labels on default surfaces:
- `endpoint`
- `profile`
- `claim`
- `context tree`
- `reembedding`
- `handler`
- `batch task`
- `queued task`
- `payload`
- `glossary`

They may appear only in:
- advanced settings
- debug details
- queue internals behind a details affordance

## Label Rules by Surface

Default surfaces:
- plain verbs
- short outcome-focused labels
- no implementation nouns unless unavoidable

Advanced sections:
- may show exact operation names
- may show technical detail when it adds control
- should still keep user-readable summaries on high-traffic surfaces
