<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# windows

## Purpose
Windows-specific installer configuration for distributing the application as an executable installer.

## Key Files
| File | Description |
|------|-------------|
| `cat-ui.nsi` | NSIS (Nullsoft Scriptable Install System) installer script. Generates CAT-UI-setup.exe with Start Menu shortcuts, Desktop shortcuts, and Add/Remove Programs registry entries. Expects build parameters: /DAPP_VERSION, /DSOURCE_DIR (PyInstaller output), /DOUTPUT_FILE. |

## For AI Agents
### Working In This Directory
- These files are used by CI/CD pipeline for building Windows releases
- The NSIS script is invoked by the build system with version and output path parameters

<!-- MANUAL: -->
