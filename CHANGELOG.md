# Changelog

All notable changes to `webOS Sidecar` will be documented here.

## Unreleased

### Added

- cross-platform launcher entrypoints for macOS, Linux, Windows PowerShell, and Windows Command Prompt
- shared `launch.py` bootstrap so every platform uses the same validation and browser-open flow
- new `webOS Sidecar` SVG logo and refreshed favicon
- README badges and emoji-marked quickstart sections for platforms and the stack

### Changed

- updated the dashboard and README with platform-specific quickstart guidance
- added a validation-only launcher mode via `python launch.py --check`

## v0.2.0 - 2026-03-22

### Added

- `webOS Sidecar` project identity, repo metadata, and publishable README
- Litefin-aware source presets and curated app picks in the dashboard
- Mermaid diagrams for flow and project structure
- local Node compatibility shim for the LG CLI on Node 25
- `.nvmrc` pin for Node 22
- MIT license

### Changed

- normalized LG Key Server passphrases to uppercase before saving
- improved device cards so they show SSH key and passphrase state
- improved install preflight so missing credentials fail early with clear troubleshooting
- improved release resolver guidance for Litefin multi-build webOS releases

### Fixed

- fixed the Key Server case-sensitivity issue that caused valid TV codes like `074A14` to fail when saved as lowercase
- fixed the LG CLI install crash on Node 25 caused by missing `util.isDate`
- fixed stale local SSH key reuse between repeated TV link attempts
- fixed dashboard refresh behavior so TV auth state stays visible after retries

## v0.1.0 - 2026-03-21

### Added

- initial FastAPI + static dashboard wrapper
- LG TV device save and key-link flow
- GitHub release resolver for `.ipk` assets
- package upload and zip-to-`.ipk` packaging support
- install verification and troubleshooting surface
