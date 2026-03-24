<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# scripts

## Purpose
Build and packaging scripts for creating distributable versions of the application.

## Key Files
| File | Description |
|------|-------------|
| `build_ui.py` | PyInstaller build script for standalone UI executable artifacts |

## For AI Agents

### Working In This Directory

#### build_ui.py
- **Entry point**: `python scripts/build_ui.py`, `make build-ui`, or `make build-macos-app` on macOS
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

### Common Workflows
- **Clean rebuild**: `python scripts/build_ui.py --clean`
- **Debug build**: `python scripts/build_ui.py --debug`
- **Local macOS app bundle**: `make build-macos-app`

<!-- MANUAL: -->
