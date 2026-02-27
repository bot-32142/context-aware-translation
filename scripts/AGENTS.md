<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# scripts

## Purpose
Build and packaging scripts for creating distributable versions of the application.

## Key Files
| File | Description |
|------|-------------|
| `build_ui.py` | PyInstaller build script for standalone UI executable (macOS app bundle, Windows exe, Linux executable) |
| `create_appimage.sh` | Linux AppImage packaging script; converts PyInstaller output to `.AppImage` with desktop integration |

## For AI Agents

### Working In This Directory

#### build_ui.py
- **Entry point**: `python scripts/build_ui.py` or `make build-ui`
- **Dependencies**: Requires `PyInstaller` installed
- **Behavior**:
  - Locates project root relative to script location
  - Cleans `build/` and `dist/` directories (optional with `--clean`)
  - Runs PyInstaller with `cat-ui.spec` from project root
  - Platform-aware output detection (macOS → `.app` bundle, Windows → `.exe`, Linux → executable)
  - Prints build summary with size details
- **Arguments**:
  - `--clean`: Remove build artifacts before building
  - `--debug`: Build with debug symbols (`--debug=all`)
  - `--no-build`: Clean only, skip build
- **Exit codes**: 0 = success, 1 = failure (missing PyInstaller or spec file)
- **Output**: Built artifacts in `dist/` directory

#### create_appimage.sh
- **Entry point**: `./scripts/create_appimage.sh [version] [platform_name]`
- **Arguments**:
  - `version` (optional): Release version string (default: `v0.0.0-dev`)
  - `platform_name` (optional): Platform identifier (default: `linux-x86_64`)
  - Example: `./scripts/create_appimage.sh v0.1.1 linux-x86_64`
- **Dependencies**: Requires PyInstaller output in `dist/CAT-UI/`
- **Behavior**:
  - Creates AppImage directory structure under `build/CAT-UI.AppDir`
  - Downloads and extracts `appimagetool` (cached to avoid re-downloading)
  - Moves PyInstaller output to `usr/bin/` within AppDir
  - Generates desktop entry (`cat-ui.desktop`) with metadata
  - Creates application icon (256×256 PNG, blue background with "CAT" text; falls back to minimal 1px PNG if Pillow unavailable)
  - Generates AppRun entry point script with environment setup
  - Builds final AppImage with compression
- **Output**: `.AppImage` file in `release/` directory
- **Pre-requisite**: Must run `build_ui.py` first to populate `dist/CAT-UI/`

### Common Workflows
- **Full standalone build**: `make build-ui && ./scripts/create_appimage.sh v0.1.0 linux-x86_64`
- **Clean rebuild**: `python scripts/build_ui.py --clean`
- **Debug build**: `python scripts/build_ui.py --debug`

<!-- MANUAL: -->
