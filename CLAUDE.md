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
  plot_assembly.py      Signals + database_options → PlotGroups (grouping, derived plots)
  signal_container.py   Signal / PlotGroup / PlotModel data models
  signal_reference.py   resolve a config string to the Signal(s) it names
  constants.py          global constants + option schema classes
  user_options.py       UserOptions schema as data: traversal, defaults, validate()
  validation.py         ValidationIssue — what every config validator returns
  plot_types/
    base.py             PlotTypeDefinition + RenderSpec; the defaults ARE time_series
    registry.py         AVAILABLE definitions, BUILDERS, PAGE_ORDER, definition_for()
    <name>/             one package per type: definition.py (config) + plot.py (render)
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

**Signal references** in `grouped_fields` and in any plot type's section resolve via a 3-mode lookup in `signal_reference.resolve_signal_references`: qualified `datasource::raw_name` → display name → raw-name fallback.

**Config scope is desugared once, and grouping joins on signal identity** ([ADR-0013](docs/adr/0013-signal-references-are-qualified-before-assembly.md)). `assemble_plot_groups` is called once, after the datasource loop, and its first step rewrites every per-datasource reference as a qualified global one — downstream, local scope does not exist. An `other::<stem>` section is one namespace deeper and desugars in the same pass; `other` injects nothing a config file states, only the group-per-file it derives from the columns that loaded. Both config spellings stay valid; the desugaring is a property of the code, not of the file format. A signal is left out of the default one-plot-per-signal pass only when a group took *that object*, never when something merely shares its `raw_name` (unique only within a datasource).

**A plot type is a module.** Everything that varies by plot type lives in `plot_types/<name>/`; nothing outside the package branches on plot type or hardcodes a section key (asserted by `tests/plot_types/test_boundaries.py`). Each package has two halves, split by what they may import:
- `definition.py` — what the type *is*: `NAME`/`SECTION_KEY`, the six capability flags, config keys, `validate()`, `map_refs()`, xlsx sheet + row interpretation. Imports nothing but `validation`.
- `plot.py` — the render half: `build()`, the maths, the rendering it installs. Imports `signal_container`, numpy and plotly.

**Everything a plot type knows travels on the object.** A Signal carries its definition (`plot_options.definition`) and its `RenderSpec`, so every render site reads `definition.GRID_LAYOUT` rather than asking a registry whether `"loop"` is in a set. That is why `signal_container` imports nothing from `plot_types` but `base` (asserted by `test_boundaries.py`), and why the data model never knows the roster. `registry.definition_for(name)` is the single exception: a plot type that crossed a Dash store as JSON has only its name left, and an unregistered one resolves to `Unknown`, which has every capability off. **"Schema" is not the word here** — the file holds identity and rendering capabilities as well as config grammar, and the codebase already spends `schema` on `UserOptions` classes and the Dash widget registry.

`time_series` is registered but has no package: every default in `PlotTypeSchema` is its behaviour, and `DERIVED` is the types with a `SECTION_KEY`. **Adding a plot type is a package plus two adjacent lines in `registry.py` — `AVAILABLE` and `BUILDERS`** — nothing in `database_options_parser.py`, `database_options_xlsx.py`, `plot_assembly.py` or `signal_container.py` changes, and no datasource imports `plot_types` at all. Two things still cost more, and both are the general mechanism rather than the plot type: a **user display setting** is a `UserOptions` class in `constants.py` plus a `DisplayFallbacks` field (as `loops_per_row` and `spectrogram_db_range` are), and an **axis payload of its own** is a field on `Data` (as `point_time_axis` and `spectrogram_freq_axis` are). Forgetting a half is an import-time crash, never a config that validates and renders nothing (`tests/plot_types/test_fake_plot_type.py` registers a fourth type and drives it through all six paths).

`wrapper.main`/`inspect` call an optional `progress_callback(current, total, name)` between datasources, which drives the UI progress bar.

## Datasources

Registered in `datasource/registry.py` (`DataSource.AVAILABLE`); the canonical list plus folder/file-naming rules live in the [tutorial](docs/user_guide/tutorial.md) → *Patient Data & Supported Data Sources*. A patient folder holds one subfolder per source.

**A module is justified only by format-specific parsing** ([ADR-0008](docs/adr/0008-datasource-modules-need-format-specific-parsing.md)). Plain CSV/parquet with a datetime column belongs in `other/`, configured per file under an `other::<stem>` key — that scope carries its own `time_shift`, timezone, grouping and trace style, so a module would add machinery and no capability.

**`_load` transcribes; `_format` interprets** ([ADR-0010](docs/adr/0010-load-transcribes-format-interprets.md)). `_load`'s output *is* the parquet cache, so it must be reproducible from the source file alone — no option resolved inside it. Mechanically: no `DATA_SOURCE_DEFAULT_TIMEZONE`, no `apply_timezone_to_dataframe` in any `_load`.

**Datetime bounds are qualified at the boundary** ([ADR-0011](docs/adr/0011-datetime-bounds-are-qualified-at-the-boundary.md)). The UI turns naive form text into a tz-aware instant at Submit, using the user's `display_timezone` — *that* is what makes the Settings timezone govern the time window. The load path only ever localizes a bound that is still naive (script or hand-edited file), and does so with `cst.NAIVE_BOUND_TZ`, never a user option, so `extract_*` output does not depend on who is at the keyboard. `cst.NAIVE_BOUND_TZ` and `cst.DISPLAY_TIMEZONE` are separate literals on purpose; do not alias them.

**Adding one**: use the `/new-datasource` skill — it is authoritative for the module layout, `options.py` constants, the loader, registration (Other stays last), example data, tests, snapshots, and the tutorial table.

## Config files

Field-by-field reference is in the [tutorial](docs/user_guide/tutorial.md). The three tiers:
- **`database_options`** (`.json` or `.xlsx`) — per-source signal config: `field_display`, `signals` (labels/units/colors), `grouped_fields`, and one section per derived plot type (`loop`, `spectrogram`, `psd`); a `global` section takes the same keys, resolved across datasources. Uploading one in the UI caches it to `~/.clinical_scope/last_database_options.json` (signal metadata only, no PHI).
- **`patient_options`** (`.json`) — per-run settings: `data_folder`, `datetime_start`/`datetime_end`, `quick_load`, and per-source options (`time_shift`, `day`, …).
- **`user_options`** (`~/.clinical_scope/user_options.json`) — the third tier: per-person app behaviour + display fallbacks, edited only in the Settings modal. **Never overrides `database_options`** ([ADR-0005](docs/adr/0005-user-options-are-fallbacks.md)). A new display setting = a `UserOptions` schema class (with `SECTION`) + a field on `DisplayFallbacks` (`signal_container.py`) + one read site; the carrier is threaded from `wrapper.main` down to both `Signal` and `PlotModel` construction, so no signature grows. Values are held to the schema by `user_options.validate()` at every boundary that accepts one, and only `dash_api` may read the file ([ADR-0014](docs/adr/0014-user-options-are-validated-at-the-boundary.md)).

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
- **CI** (`.github/workflows/ci.yml`) — runs on push to `main` and PRs to `main` (skipped on drafts). Two jobs so lint cannot gate tests: `lint` (ruff, once) and `test` (pytest on Python 3.11 & 3.13).

## Code style

Ruff (`ruff check .`, `ruff format .`), capped to the 0.16.x line by the `dev` extra — upgrade procedure in [CONTRIBUTING.md](CONTRIBUTING.md). Line length 100 (Python only — Markdown prose is not column-wrapped), double quotes, target Python 3.12 (3.9+ compatible), D213 docstrings (summary on second line).

Keep inline comments concise — one line where possible; explain the non-obvious *why*, **not** the *what*. Reserve longer prose for docstrings.

Shared literal values (option keys, orderings, defaults) belong in `constants.py`, not inline in modules — even when only one module uses them today. The exception is a value one registered module *owns*: a datasource's option keys live in its `options.py`, a plot type's name, section key and config keys in its `definition.py`, and each registry owns the ordering across its own members. That is a `src/` rule: tests assert **independent literals** (`== 300`, not `== cst.DEFAULT_SUBPLOT_HEIGHT`), since a test that restates the constant it exercises can never fail.

## Logs

Gitignored under `logs/`: `logs/app/dash_api.log` (app), `logs/scripts/` (scripts).

## Agent docs & skills

- **Issue tracker** — GitHub Issues via the GitHub MCP server (`larib-data/clinical-scope`), not the `gh` CLI; see `docs/agents/issue-tracker.md`.
- **Triage labels** — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`; see `docs/agents/triage-labels.md`.
- **Domain docs** — single-context repo: `CONTEXT.md` (domain glossary) + `docs/adr/` at root; see `docs/agents/domain.md`.
- **Doc audience** — `README.md` / `docs/user_guide/tutorial.md` are clinician-facing: state behavior, not implementation; never link to `docs/adr/`, `CONTEXT.md`, or CLAUDE.md from them.
- **Tutorial PDF** — the standalone bundle ships `tutorial.md` as a PDF, and nothing regenerates it: `assemble_bundle.py` copies whatever is committed. A commit touching `tutorial.md` must run `./docs/user_guide/build_pdf.sh` and commit the regenerated PDF alongside it.
- **Project skills** (`.claude/skills/`, invoke with `/name`):

| Skill | When to use |
|---|---|
| `/grilling` | Stress-test a plan or decision before building — one question at a time, until it is settled |
| `/new-datasource` | Add a new medical device / file format as a datasource module |
| `/new-plot-type` | Add a new way of drawing signals — first deciding whether it is a plot type at all |
| `/organize-patient-folder` | Reorganize a dump of clinical files into the per-datasource folder structure |
| `/generate-database-options` | Generate a `database_options` config by inspecting a patient folder |
| `/anonymize-timeseries` | De-identify clinical timeseries files so they can be committed as example data |
