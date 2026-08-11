# Changelog

All notable changes to this project will be documented in this file.

---

## [Unreleased]

### Removed — **breaking**
- Drop the `philips_waves`, `philips_numerics` and `syringe` datasources. They performed no format-specific parsing — a plain `read_csv` / `read_parquet` — so they were the generic `other` source with extra machinery. Now that each file inside `other/` carries its own configuration and its own `time_shift`, they no longer earn a module.

  **To migrate:** move the files into the patient's `other/` subfolder, then rename their `database_options` and `patient_options` sections from `philips_waves` / `philips_numerics` / `syringe` to `other::<filename-without-extension>`. A folder still named after a removed source is now reported with a warning instead of being loaded. Three details to check while migrating:
  - **Syringe timestamps.** The old source defaulted to `Europe/Paris`; `other` defaults to UTC. Add `"additional_informations": {"timezone": "Europe/Paris"}` to the section, or timestamps shift by an hour or two.
  - **Marker traces.** Syringe and Philips numerics drew `lines+markers`. Restore it with the new per-file `trace_options` block (see the user guide).
  - **Signal names and plot order.** Signals inside `other/` are named `<stem>::<column>`, so cross-source `grouped_fields` and `loop` entries need the qualified form (`other::waves::art`). `other` also renders last by default; use per-signal `priority` to restore a specific order.

### Added
- Per-file `trace_options` in an `other::<stem>` section (`mode`, `line_width`, `line_dash`, `opacity`), so one file can be drawn with markers while its neighbours stay plain lines.
- Files read from `other/` are now symlinked into `clinical_scope_output/`, extending the traceability guarantee previously limited to `philips_waves`.

### Fixed
- A folder holding both `data.csv` and `data.parquet` no longer loads the same data twice under colliding names — one file per stem is kept, preferring parquet.
- Global groups authored in the Excel format now emit qualified references for `other::<stem>` signals, which previously could not resolve.

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
