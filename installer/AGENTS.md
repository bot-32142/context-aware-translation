<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# installer

## Purpose
Platform-specific packaging configurations for distributing the application across macOS and Windows via the CI/CD release pipeline.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `macos/` | macOS code signing entitlements and DMG packaging configuration |
| `windows/` | Windows release packaging notes for direct zip distribution of the PyInstaller app folder |

## Key Files

| File | Purpose |
|------|---------|
| `macos/entitlements.plist` | Apple entitlements for code signing (dylib, executable signing during release build) |

## For AI Agents

### Working In This Directory
- These configurations are used exclusively by GitHub Actions (`.github/workflows/release.yml`) to build and sign platform-specific releases
- macOS: entitlements are applied during code signing of .dylib/.so files and the app bundle; the DMG is created with `create-dmg` and notarized with `xcrun notarytool`
- Windows: the signed PyInstaller output folder is zipped directly into the release artifact; there is no separate installer wrapper
- Changes here directly impact the release pipeline behavior

### Modifying Packaging Configs
- **entitlements.plist**: Update only if adding new app capabilities (network, file access, etc.) that require Apple sandbox permissions
- **Windows packaging**: Update `.github/workflows/release.yml` if artifact naming, signing, or zip-assembly behavior changes

### Release Build Integration
- macOS builds: entitlements are applied while signing embedded binaries and the app bundle before DMG creation/notarization
- Windows builds: `signtool` signs the PyInstaller executable and bundled native modules, then the `dist/CAT-UI` folder is archived into a versioned `.zip`
- Both platforms: final release artifacts are created in GitHub Actions; test certificate-less builds locally with unsigned artifacts

<!-- MANUAL: -->
