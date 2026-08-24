# Clinical Scope

Interactive dashboard for visualizing, annotating, and extracting multi-source clinical time-series signals (ICU monitors, ventilators, EIT, …), built with Dash/Plotly.

## Setup & run

```bash
pip install -e .        # in your virtualenv
clinical-scope          # launches the Dash app at http://127.0.0.1:8050
```

CLI scripts (extract / inspect / visualize) and the Python API are documented in [README.md](README.md) and the [user guide](docs/user_guide/tutorial.md). Packaging to a standalone executable lives in `src/clinical_scope/build_info/` (`build.sh` + README).

## Where things live

```
src/clinical_scope/
  wrapper.py            main pipeline — visualize / extract / inspect
  signal_container.py   Signal / PlotGroup / PlotModel data models
  constants.py          global constants + option schema classes
  datasource/
    base.py             DataSourceBase — find/load/format/extract/inspect template
    registry.py         registered sources (DataSource.AVAILABLE; keep Other last)
    inspection.py       DataSourceInspection / ColumnInfo + CSV export
    sources/<name>/     one package per source: options.py + find_load_format.py
  config/parsing.py     load database_options (.json / .xlsx) → dict
  dash_api/
    core_api.py         app entry point + layout
    ui_components.py    schema-driven widget factory
    styles.py           style tokens
    callbacks/          Dash callbacks (data, annotation, loop)
    annotations/        annotation model, io (annotations.json), renderer
```

## Architecture

**Pipeline** (every datasource): `find → load → format → extract_signals`. A datasource subclasses `DataSourceBase` and usually only implements `_load()`; the base covers the rest.

**Three pipelines** share `find → load → format` and diverge at the end:
- **Visualize** (`wrapper.main`) — Signals → PlotGroups → PlotModels → Plotly figures.
- **Extract** (`wrapper.extract_patient` / `batch_extract` / `extract_datasource`, also `from clinical_scope import extract_datasource, extract_patient, batch_extract`) — stop at `format`, return DataFrame(s). `save_path`/`save_folder` write explicit output, independent of the per-patient `clinical_scope_output/` parquet cache (always written; reused when `quick_load` is set).
- **Inspect** (`wrapper.inspect`) — stop at `format`, return `list[DataSourceInspection]` (columns, point counts, time ranges). `OtherDataSource.inspect()` returns **one entry per file** (`other::<stem>`); the wrapper handles single-or-list returns.

**Signal references** in `grouped_fields` and `global.loop` resolve via a 3-mode lookup in `_resolve_signal_references`: qualified `datasource::raw_name` → display name → raw-name fallback.

`wrapper.main`/`inspect` call an optional `progress_callback(current, total, name)` between datasources, which drives the UI progress bar.

## Datasources

Registered in `datasource/registry.py` (`DataSource.AVAILABLE`); the canonical list plus folder/file-naming rules live in the [tutorial](docs/user_guide/tutorial.md) → *Patient Data & Supported Data Sources*. A patient folder holds one subfolder per source.

**A module is justified only by format-specific parsing** ([ADR-0008](docs/adr/0008-datasource-modules-need-format-specific-parsing.md)). Plain CSV/parquet with a datetime column belongs in `other/`, configured per file under an `other::<stem>` key — that scope carries its own `time_shift`, timezone, grouping and trace style, so a module would add machinery and no capability.

**`_load` transcribes; `_format` interprets** ([ADR-0010](docs/adr/0010-load-transcribes-format-interprets.md)). `_load`'s output *is* the parquet cache, so it must be reproducible from the source file alone — no option resolved inside it. Mechanically: no `DATA_SOURCE_DEFAULT_TIMEZONE`, no `apply_timezone_to_dataframe` in any `_load`.

**Adding one**: use the `/new-datasource` skill — it is authoritative for the module layout, `options.py` constants, the loader, registration (Other stays last), example data, tests, snapshots, and the tutorial table.

## Config files

Field-by-field reference is in the [tutorial](docs/user_guide/tutorial.md). The three tiers:
- **`database_options`** (`.json` or `.xlsx`) — per-source signal config: `field_display`, `signals` (labels/units/colors), `grouped_fields`, `loop`; plus `global.grouped_fields`. Uploading one in the UI caches it to `~/.clinical_scope/last_database_options.json` (signal metadata only, no PHI).
- **`patient_options`** (`.json`) — per-run settings: `data_folder`, `datetime_start`/`datetime_end`, `quick_load`, and per-source options (`time_shift`, `day`, …).
- **`user_options`** (`~/.clinical_scope/user_options.json`) — the third tier: per-person app behaviour + display fallbacks, edited only in the Settings modal. **Never overrides `database_options`** ([ADR-0005](docs/adr/0005-user-options-are-fallbacks.md)). A new display setting = a `UserOptions` schema class (with `SECTION`) + a field on `DisplayFallbacks` (`signal_container.py`) + one read site; the carrier is threaded from `wrapper.main` down to both `Signal` and `PlotModel` construction, so no signature grows.

Reference configs: `example/demo_database/database_options.{xlsx,json}` — the canonical example, in both formats, runnable against `demo_patient/` and covering **every** datasource it ships. **The `.json` is generated from the `.xlsx`**; edit the spreadsheet and regenerate. `tests/unit/test_example_assets.py` enforces both the coverage and the parity, and prints the regeneration one-liner. `example/option_files/patient_options_example.json` covers the other tier, for library users who never launch the app and so never get an app-written one.

## UI (Dash)

- Layout in `core_api.py`; input widgets built by a schema-driven factory in `ui_components.py` (`API_TYPE` → widget); style tokens in `styles.py`; callbacks in `callbacks/`.
- Conventions (not enforced by tooling):
  - **Button color = action role**: orange = primary (Process), teal = Inspect, blue/grey/green = secondary (upload config / reload last / default-viz).
  - The patient-options form is a 2-column grid that **auto-grows per datasource** — adding a source needs no layout edit.
  - The annotation toolbar stays hidden until a visualization succeeds.
  - Widgets that feed the **next** Process update live (edit and the next Submit picks it up); anything rendering the **last** Process reads its own cached snapshot instead (`LOOP_DATA_CACHE`, annotation `modal_data`). `display_timezone` is a `user_options` field (Settings modal, live by construction) that governs how the patient-options datetime fields display — the datetime-window re-render callback (issues #68/#69) is the one widget with this live cross-field wiring.

## Testing

```bash
pytest                                                   # full suite
pytest tests/datasource/ -m "not snapshot"               # fast structural only
pytest tests/datasource/ --update-snapshots -m snapshot  # regenerate golden files after data change
```

Full command reference in `tests/README.md`.

- **Test data** — `example/` holds only user-facing material; test-only fixtures live in `tests/data/` (`patients/`, `option_files/`), alongside the goldens in `tests/expected_results/`. The one deliberate crossing: `example/demo_database/demo_patient/` is the shipped demo *and* the main fixture (`patient_full_path`), so the suite fails if the demo breaks. **Don't replace either with full-size originals**; after changing test or demo data, regenerate snapshots.
- **Fixtures** — datasource tests share `formatted_df` at `scope="module"` and only read DataFrames (never mutate).
- **CI** (`.github/workflows/ci.yml`) — runs on push to `main` and PRs to `main` (skipped on drafts); Python 3.11 & 3.13; steps `ruff format --check`, `ruff check`, `pytest`.

## Code style

Ruff (`ruff check src/`, `ruff format src/`). Line length 100 (Python only — Markdown prose is not column-wrapped), double quotes, target Python 3.12 (3.9+ compatible), D213 docstrings (summary on second line).

Keep inline comments concise — one line where possible; explain the non-obvious *why*, **not** the *what*. Reserve longer prose for docstrings.

Shared literal values (option keys, plot types, orderings, defaults) belong in `constants.py`, not inline in modules — even when only one module uses them today. That is a `src/` rule: tests assert **independent literals** (`== 300`, not `== cst.DEFAULT_SUBPLOT_HEIGHT`), since a test that restates the constant it exercises can never fail.

## Logs

Gitignored under `logs/`: `logs/app/dash_api.log` (app), `logs/scripts/` (scripts).

## Agent docs & skills

- **Issue tracker** — GitHub Issues via the GitHub MCP server (`larib-data/clinical-scope`), not the `gh` CLI; see `docs/agents/issue-tracker.md`.
- **Triage labels** — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`; see `docs/agents/triage-labels.md`.
- **Domain docs** — single-context repo: `CONTEXT.md` (domain glossary) + `docs/adr/` at root; see `docs/agents/domain.md`.
- **Doc audience** — `README.md` / `docs/user_guide/tutorial.md` are clinician-facing: state behavior, not implementation; never link to `docs/adr/`, `CONTEXT.md`, or CLAUDE.md from them.
- **Project skills** (`.claude/skills/`, invoke with `/name`):

| Skill | When to use |
|---|---|
| `/new-datasource` | Add a new medical device / file format as a datasource module |
| `/organize-patient-folder` | Reorganize a dump of clinical files into the per-datasource folder structure |
| `/generate-database-options` | Generate a `database_options` config by inspecting a patient folder |
| `/anonymize-timeseries` | De-identify clinical timeseries files so they can be committed as example data |
