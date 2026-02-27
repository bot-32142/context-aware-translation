<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# installer

## Purpose
Platform-specific installer configurations for distributing the application across macOS and Windows via the CI/CD release pipeline.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `macos/` | macOS code signing entitlements and DMG packaging configuration |
| `windows/` | Windows NSIS installer script for creating signed .exe setup files |

## Key Files

| File | Purpose |
|------|---------|
| `macos/entitlements.plist` | Apple entitlements for code signing (dylib, executable signing during release build) |
| `windows/cat-ui.nsi` | NSIS script that creates the Windows installer executable |

## For AI Agents

### Working In This Directory
- These configurations are used exclusively by GitHub Actions (`.github/workflows/release.yml`) to build and sign platform-specific releases
- macOS: entitlements are applied during code signing of .dylib/.so files and the app bundle; the DMG is created with `create-dmg` and notarized with `xcrun notarytool`
- Windows: the NSIS script receives version, source directory, and output file paths as parameters; the resulting .exe is signed with `signtool`
- Changes here directly impact the release pipeline behavior

### Modifying Installer Configs
- **entitlements.plist**: Update only if adding new app capabilities (network, file access, etc.) that require Apple sandbox permissions
- **cat-ui.nsi**: Update installer UI, registry entries, or file handling; the script is invoked with `/DAPP_VERSION`, `/DSOURCE_DIR`, `/DOUTPUT_FILE` parameters

### Release Build Integration
- macOS builds: entitlements applied at lines 143, 151, 157 of release.yml
- Windows builds: NSIS invoked at line 265 of release.yml with paths and version injected
- Both platforms: code signing and notarization happen after installer creation; test certificate-less builds locally with unsigned artifacts

<!-- MANUAL: -->
