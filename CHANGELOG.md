# Changelog

All notable changes to this project will be documented in this file.

---

## [1.0.0] — 2026-06-24 *(First public release)*

> **Note:** First public, open-source release of ClinicalScope — installable from PyPI
> (`pip install clinical-scope`) and archived on Zenodo with a citable DOI. Supersedes
> the private 0.x practice releases (the 0.4.x tags were internal PyPI/release dry-runs).

### Packaging & Distribution
- Publish to PyPI and TestPyPI via dedicated GitHub Actions workflows (`publish-pypi.yml`)
- Archive releases on Zenodo with a concept DOI; add DOI badge and `doi` to `CITATION.cff`
- Ship Apache-2.0 `LICENSE`, `DISCLAIMER.txt`, and `CITATION.cff`
- Generate `THIRD_PARTY_LICENSES.txt` for the PyInstaller bundle from installed distributions plus a hand-maintained native-library map; encode the attribution policy as build tripwires (warn-only, see [ADR-0002](docs/adr/0002-warn-only-on-unresolved-license-attribution.md))
- Unify the build via `assemble_bundle.py`, a single post-build step shared by `build.sh` and the CI build workflow (eliminates bash/YAML drift); exclude GPL-3 `readline` from the bundle

### UX
- Greatly improve feedback when a patient folder path is wrong or misconfigured — the most common first-run mistake
- Improve placeholder management across input widgets

### Documentation
- Add `CONTEXT.md` domain glossary and initialize `docs/adr/` with the first ADRs
- Add and expand `docs/RELEASING.md` release checklist
- Expand the `/new-datasource` skill for adding device/format modules
- Prepare `README.md` for public release; refresh the demo GIF

### Tests
- Add `tests/unit/test_third_party_licenses.py` pinning the copyleft policy and native-lib map against real per-platform build output

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
