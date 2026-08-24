# Changelog

All notable changes to this project will be documented in this file.

---

## [Unreleased]

_Nothing yet._

---

## [1.1.0] — 2026-08-24

> **Note:** The first release since v1.0.0 went public. It carries one breaking change (three datasources removed, with a migration path below), two new plot types, a new per-person settings tier, and a substantial reduction in load time and memory for large recordings.

> **Upgrading:** this release changes what the `clinical_scope_output/` parquet cache contains, and nothing detects a cache written by an older version. After updating, un-tick **"Re-use data if already loaded once"** (`quick_load`) for one run per patient so the cache is rewritten; leaving a stale cache in place gives EIT recordings without their `%Local` columns, and timestamps carrying whatever timezone the old run stamped in.

### Removed — **breaking**
- Drop the `philips_waves`, `philips_numerics` and `syringe` datasources. They performed no format-specific parsing — a plain `read_csv` / `read_parquet` — so they were the generic `other` source with extra machinery. Now that each file inside `other/` carries its own configuration and its own `time_shift`, they no longer earn a module.

  **To migrate:** move the files into the patient's `other/` subfolder, then rename their `database_options` and `patient_options` sections from `philips_waves` / `philips_numerics` / `syringe` to `other::<filename-without-extension>`. A folder still named after a removed source is now reported with a warning instead of being loaded. Three details to check while migrating:
  - **Syringe timestamps.** The old source defaulted to `Europe/Paris`; `other` defaults to UTC. Add `"additional_informations": {"timezone": "Europe/Paris"}` to the section, or timestamps shift by an hour or two.
  - **Marker traces.** Syringe and Philips numerics drew `lines+markers`. Restore it with the new per-file `trace_options` block (see the user guide).
  - **Signal names and plot order.** Signals inside `other/` are named `<stem>::<column>`, so cross-source `grouped_fields` and `loop` entries need the qualified form (`other::waves::art`). `other` also renders last by default; use per-signal `priority` to restore a specific order.

### Added
- **Spectrogram plot type.** A time–frequency view for high-rate signals (EEG, pressure waveforms), configured per signal with a window length, overlap and dB range. It renders the same samples a different way — it does not label or score them ([ADR-0006](docs/adr/0006-no-clinical-analysis.md)).
- **PSD plot type.** Power spectral density over the visible window; several PSDs share one subplot so bands can be compared side by side.
- **`.edf` datasource.** Reads European Data Format recordings, the usual container for EEG and polysomnography exports.
- **`user_options`, a third configuration tier.** Per-person app behaviour and display fallbacks, edited in the Settings modal and stored at `~/.clinical_scope/user_options.json`. It only ever supplies values `database_options` left unset — it never overrides them ([ADR-0005](docs/adr/0005-user-options-are-fallbacks.md)).
- **Per-file configuration for `other/`.** Each file gets its own `other::<stem>` section carrying its own `time_shift`, timezone, grouping and trace style, so unrelated CSVs in one folder stop sharing a single configuration.
- **Output redirection.** `save_path` / `save_folder` write results outside the patient folder, so a read-only input directory no longer blocks a run ([ADR-0003](docs/adr/0003-output-root-redirection.md)).
- Per-file `trace_options` in an `other::<stem>` section (`mode`, `line_width`, `line_dash`, `opacity`, `marker_symbol`, `marker_size`), so one file can be drawn with markers while its neighbours stay plain lines.
- Files read from `other/` are now symlinked into `clinical_scope_output/`, extending the traceability guarantee previously limited to `philips_waves`.

### Changed
- **`datetime_start` / `datetime_end` are stored as timezone-aware instants** rather than wall-clock text, so a window means the same moment regardless of the machine reading it.
- **Display timezone moved into `user_options`.** It is now a per-person setting in the Settings modal, and the patient-options datetime fields re-render in the chosen zone as soon as it changes.
- **Datetime columns are auto-detected by both name and content.** A column is only accepted as the time axis once its values parse as timestamps, so a `date`-ish name over unparseable data no longer hijacks the axis ([ADR-0004](docs/adr/0004-validate-datetime-column-candidates.md)).
- **Loading transcribes, formatting interprets.** No loader resolves configuration any more, so the parquet cache is reproducible from the source file alone and can never freeze a setting from the run that wrote it ([ADR-0010](docs/adr/0010-load-transcribes-format-interprets.md)). Timestamps land in the cache naive and are localized afterwards; the resulting instants are unchanged.
- **A `mindray_scope` folder mixing `.csv` and `.xml` now fails with both file names** instead of being silently rescued by a default timezone. The two carry incompatible time information — naive wall-clock in one, an explicit offset in the other — so the old rescue could shift a recording by an hour without saying so.
- Plot types are ordered with time series first, so the familiar view leads.
- Reloading patient options now falls back to the default for any entry the saved file omits, instead of leaving it blank.
- A patient folder that yields nothing now says which folders were searched and why each was skipped.
- CLI scripts that produce no output explain what was missing rather than exiting quietly.
- `example/` is split by audience, with the demo configuration promoted to the canonical reference; every demo datasource now starts at a common time, so the default view opens with all sources overlapping.

### Fixed
- **Spectrogram and PSD magnitudes are now a true one-sided power spectral density** (`unit²/Hz`), following `scipy.signal.welch`'s windowing, normalisation and detrending. Previously the magnitude tracked window length — a noise floor climbing 3 dB per doubling — so two windows of the same signal could not be compared and an absolute dB range slid out from under the data.
- Applying a timezone no longer mutates the caller's DataFrame index in place.
- A folder holding both `data.csv` and `data.parquet` no longer loads the same data twice under colliding names — one file per stem is kept, preferring parquet.
- Global groups authored in the Excel format now emit qualified references for `other::<stem>` signals, which previously could not resolve.
- The bundled EEG example no longer ships channels that were pure artefact.

### Performance
- **Columns are selected and pruned before loading.** Only the columns a run actually needs are read from disk, cutting load time and peak memory on wide recordings; `inspect` prunes at read too. Redundant deep copies were removed and the deduplicate-then-sort step unified across every path that used both.
- **EIT percentage columns are now selectable.** `%Local N` ratios are derived at load time, so a `field_display` naming them matches real columns: a configured EIT read goes from all 71 columns to 9 of 75.
- Column pruning now applies to any cache this library wrote, not only those whose stored index is a timestamp — a non-temporal index previously fell back to reading every column.
- A second read of the same file is skipped when no time window narrows it.
- Parquet datetime-column detection reads metadata instead of the column body.

### Documentation
- Eight new ADRs: output-root redirection (0003), datetime-column validation (0004), user-options-as-fallbacks (0005), the no-clinical-analysis scope boundary (0006), read-time pruning as an optimization rather than a filter (0007), the format-specific-parsing criterion for datasource modules (0008), `other::<stem>` as a configuration scope (0009), and the load-transcribes / format-interprets split (0010).
- `CONTRIBUTING.md` now states what belongs in the library — ClinicalScope derives for display, it does not interpret — and when a new datasource needs a module of its own rather than a slot in `other/`.

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
