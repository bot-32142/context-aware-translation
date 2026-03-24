<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# windows

## Purpose
Windows-specific release packaging notes for distributing the application as a portable zip archive.

## For AI Agents
### Working In This Directory
- These files are used by CI/CD pipeline for building Windows releases
- Windows releases are assembled directly in `.github/workflows/release.yml`
- The workflow signs `dist/CAT-UI/CAT-UI.exe` plus bundled `.dll`/`.pyd` files, then archives `dist/CAT-UI` into a versioned `.zip`
- There is no NSIS installer, desktop shortcut creation, or Add/Remove Programs entry in the current release flow

<!-- MANUAL: -->
