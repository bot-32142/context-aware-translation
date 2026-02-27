<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# macOS

## Purpose
macOS-specific installer configuration for distributing the application as a signed and notarized app bundle.

## Key Files
| File | Description |
|------|-------------|
| `entitlements.plist` | Apple security entitlements for PyInstaller-bundled app. Allows unsigned executable memory, library validation bypass, and JIT compilation for dependencies like numpy and torch. |

## For AI Agents
### Working In This Directory
- These files are used by CI/CD pipeline for building macOS releases
- The entitlements.plist is required for code signing and notarization of the packaged application

<!-- MANUAL: -->
