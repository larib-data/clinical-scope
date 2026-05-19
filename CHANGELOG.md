# Changelog

All notable changes to this project will be documented in this file.

---

## [0.3.0] — 2026-05-19 *(Practice Release — internal validation only)*

> **Note:** This is a private practice release. Its purpose is to validate the
> end-to-end workflow: version bump → tag → CI → build artifacts → GitHub Release page.
> It is not intended for external users. The repository remains private.
> The first public release will be **v1.0.0**.

### CI & Build
- Add GitHub Actions CI workflow running `ruff` and `pytest` on Python 3.11 & 3.13 (#23)
- Add tag-triggered build workflow that attaches platform zips to the GitHub Release page (#25)
- Drop macOS Intel build; macOS ARM only going forward (#27)
- Fix PyInstaller path localization for GitHub Actions runners
- Update declared Python version range to match reality

### Features & Enhancements
- Add `clinical-scope` CLI entry point — after `pip install`, launch the app with a single command (#30)
- Add "Reload last patient options" button for repeated patient loads (#41)
- Symlink non-cached datasources (e.g. `philips_waves`) into the output folder for traceability (#44)
- Move display timezone from global constant to per-datasource option

### Bug Fixes
- Fix `quick_load` cache behaviour: un-ticking now correctly overwrites cached data (#40)

### Documentation
- Add `CONTRIBUTING.md` covering dev setup, tests, linting, and PR process (#36)

### Code Quality & Cleanup
- Centralize path localization for packaged builds
- Rename signal class from constants file for readability
- Remove example HTML visualizations and output files from the repository

---

## [0.2.2] — prior

Initial tracked release.
