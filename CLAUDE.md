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

**Adding one**: use the `/new-datasource` skill — it is authoritative for the module layout, `options.py` constants, the loader, registration (Other stays last), example data, tests, snapshots, and the tutorial table.

## Config files

Field-by-field reference is in the [tutorial](docs/user_guide/tutorial.md). The two-file split:
- **`database_options`** (`.json` or `.xlsx`) — per-source signal config: `field_display`, `data` (labels/units/colors), `grouped_fields`, `loop`; plus `global.grouped_fields`. Uploading one in the UI caches it to `~/.clinical_scope/last_database_options.json` (signal metadata only, no PHI).
- **`patient_options`** (`.json`) — per-run settings: `data_folder`, `datetime_start`/`datetime_end`, `quick_load`, and per-source options (`time_shift`, `day`, …).

Reference configs in `example/option_files/`.

## UI (Dash)

- Layout in `core_api.py`; input widgets built by a schema-driven factory in `ui_components.py` (`API_TYPE` → widget); style tokens in `styles.py`; callbacks in `callbacks/`.
- Conventions (not enforced by tooling):
  - **Button color = action role**: orange = primary (Process), teal = Inspect, blue/grey/green = secondary (upload config / reload last / default-viz).
  - The patient-options form is a 2-column grid that **auto-grows per datasource** — adding a source needs no layout edit.
  - The annotation toolbar stays hidden until a visualization succeeds.

## Testing

```bash
pytest                                                   # full suite
pytest tests/datasource/ -m "not snapshot"               # fast structural only
pytest tests/datasource/ --update-snapshots -m snapshot  # regenerate golden files after data change
```

Full command reference in `tests/README.md`.

- **Example data** — `example/demo_database/` is the shipped self-contained demo (xlsx config + `demo_patient/`, all sources, intentionally truncated); `example/example_patients/` holds edge-case patients used only by tests. **Don't replace these with full-size originals**; after changing example data, regenerate snapshots.
- **Fixtures** — datasource tests share `formatted_df` at `scope="module"` and only read DataFrames (never mutate).
- **CI** (`.github/workflows/ci.yml`) — runs on push to `main` and PRs to `main` (skipped on drafts); Python 3.11 & 3.13; steps `ruff format --check`, `ruff check`, `pytest`.

## Code style

Ruff (`ruff check src/`, `ruff format src/`). Line length 100 (Python only — Markdown prose is not column-wrapped), double quotes, target Python 3.12 (3.9+ compatible), D213 docstrings (summary on second line).

Keep inline comments concise — one line where possible; explain the non-obvious *why*, **not** the *what*. Reserve longer prose for docstrings.

## Logs

Gitignored under `logs/`: `logs/app/dash_api.log` (app), `logs/scripts/` (scripts).

## Agent docs & skills

- **Issue tracker** — markdown files under `.scratch/`; see `docs/agents/issue-tracker.md`.
- **Triage labels** — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`; see `docs/agents/triage-labels.md`.
- **Domain docs** — single-context repo: `CONTEXT.md` (domain glossary) + `docs/adr/` at root; see `docs/agents/domain.md`.
- **Project skills** (`.claude/skills/`, invoke with `/name`):

| Skill | When to use |
|---|---|
| `/new-datasource` | Add a new medical device / file format as a datasource module |
| `/organize-patient-folder` | Reorganize a dump of clinical files into the per-datasource folder structure |
| `/generate-database-options` | Generate a `database_options` config by inspecting a patient folder |
| `/anonymize-timeseries` | De-identify clinical timeseries files so they can be committed as example data |
