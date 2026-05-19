# Clinical Scope

Interactive visualization dashboard for clinical physiological signals built with Dash/Plotly.

## Environment Setup

```bash
# Activate the virtual environment
source /Users/alexis/Codes/clinical_visu_venv/bin/activate

# Install the package in editable mode
pip install -e .
```

## Running the Application

### Dash Web Application (Interactive)
```bash
python src/clinical_scope/dash_api/core_api.py
```
Opens at http://127.0.0.1:8050

### Scripts
```bash
# Extract data without plots
python scripts/process_patient_data.py patient /data/Patient01 --database-options db.json
python scripts/process_patient_data.py batch /data/patients --output-folder /out

# Inspect available columns per datasource (no plots built)
python scripts/inspect_patient_data.py /data/Patient01 --database-options db.json --output-csv out.csv

# Visualize (generates HTML)
python scripts/visualization_patient_data.py /data/Patient01 --database-options db.json
```

Common flags across scripts: `--database-options`, `--patient-options`, `--output-csv`
(inspect only), `--verbose`, `--debug`. Omit `--database-options` to enable all registered
datasources with their defaults.

## Project Structure

```
src/clinical_scope/
├── dash_api/               # Dash web application
│   ├── core_api.py         # Main entry point, layout definition
│   ├── ui_components.py    # UI component builders
│   ├── callbacks/          # Dash callbacks (data, annotation & loop handling)
│   ├── annotations/        # Annotation model, persistence, and rendering
│   │   ├── model.py        # Annotation dataclass, AnnotationType, color palette
│   │   ├── io.py           # Save/load annotations.json
│   │   └── renderer.py     # Plotly shape/annotation rendering logic
│   ├── styles.py           # Shared style constants (modal styles, etc.)
│   ├── validation.py       # Input validation
│   └── helper_api.py       # API helper functions
├── datasource/             # Datasource framework
│   ├── base.py             # Abstract base class for datasources
│   ├── registry.py         # Registry of available datasources
│   ├── inspection.py       # Data inspection models & CSV export
│   ├── timing.py           # time_it decorator for performance logging
│   ├── formatting/
│   │   └── timezone.py     # Timezone normalization utilities
│   └── sources/            # One sub-package per data source:
│       └── <source_name>/
│           ├── __init__.py
│           ├── options.py          # Source-specific options/constants
│           └── find_load_format.py # Data loading & processing logic
├── config/
│   └── parsing.py          # High-level config file loading (JSON & XLSX)
├── io/
│   └── file_utils.py       # File discovery and I/O helpers
├── database_options_parser.py  # Normalize new/legacy JSON formats
├── database_options_xlsx.py    # XLSX → dict conversion
├── hover_formatters.py     # Hover tooltip formatting helpers
├── signal_container.py     # Signal, PlotGroup, PlotModel data models
├── wrapper.py              # Main processing logic (visualization, extraction, inspection)
├── constants.py            # Global constants and option classes
└── logger_config.py        # Logging configuration
```

### Supported Data Sources

> Canonical doc: `docs/user_guide/tutorial.md` → *Patient Data & Supported Data Sources*.
> Live registry: `src/clinical_scope/datasource/registry.py::DataSource.AVAILABLE`.

- `philips_waves` — Philips waveform data (high-frequency signals).
- `philips_numerics` — Philips numeric/parameter data.
- `eit` — EIT PulmoVista impedance data (`.asc`).
- `fluxmed_signals` — FluxMed respiratory waveforms.
- `fluxmed_parameters` — FluxMed respiratory parameters.
- `servo_u` — Servo-U ventilator data (`.sta`).
- `mindray_scope` — Mindray scope waveforms (`.xml` or `.csv`); folder keyword `mindray`.
- `mindray_respi_waves` — Mindray respiratory high-frequency waveforms.
- `mindray_respi_numerics` — Mindray respiratory numeric parameters.
- `syringe` — Syringe pump data.
- `other` — Generic: auto-discovers CSV/parquet files; per-file config via `other::<stem>` keys (e.g. `other::waves`); `inspect()` returns one entry per file.

## Configuration Files

### patient_options.json
Patient-specific settings:
- `data_folder`: Path to patient data
- `datetime_start`/`datetime_end`: Time range filter
- `quick_load`: Reuse cached parquet files
- Per-datasource options (e.g., `time_shift`, `day`)

### database_options.json
Data source configuration:
- `global.grouped_fields`: Cross-source signal grouping
- Per-datasource: `field_display`, `data` (labels, units, colors), `grouped_fields`, `loop`

See `example/option_files/` for reference configurations.

### Local Config Cache
When a custom `database_options` file (JSON or XLSX) is successfully uploaded via the UI, it is automatically saved to:
```
~/.clinical_scope/last_database_options.json
```
On next app start, a **"Reload last config"** button (grey) appears in the Database Options section, allowing one-click restore.

**Privacy**: this file contains only signal metadata (labels, colors, units, field mappings) — no patient data or PHI. Safe to store in the home directory.

## Testing

```bash
pytest                                               # full suite
pytest tests/datasource/ -m "not snapshot"           # fast structural only
pytest tests/datasource/ --update-snapshots -m snapshot  # regenerate golden files after data change
```

See `tests/README.md` for full command reference.

### Example data
- `example/demo_database/` — self-contained demo shipped with the app: `database_options.xlsx` + `demo_patient/` (all 11 datasources, intentionally truncated). Mirrors real-world usage: upload the xlsx as config, point the data folder at `demo_patient/`.
- `example/example_patients/` — edge-case test patients (`Patient_difficult_format`, `Patient_other`); used only by tests.

Do not replace files with full-size originals. After changing example data, regenerate snapshots with `--update-snapshots`.

### Fixture scoping
Datasource test files use `scope="module"` for `formatted_df` (shared between `TestFormat` and `TestSnapshot`).
Tests only read DataFrames — they do not mutate them.

### CI (GitHub Actions)
Workflow: `.github/workflows/ci.yml` — triggers on push to `main` and PRs targeting `main` (skipped on draft PRs).
Matrix: Python 3.11 and 3.13. Steps: `ruff format --check`, `ruff check`, `pytest`.

## Code Style

- **Linter/Formatter**: Ruff (`ruff check`, `ruff format`)
- **Line length**: 100 characters
- **Target Python**: 3.12 (compatible with 3.9+)
- **Quote style**: Double quotes
- **Docstrings**: D213 style (summary on second line)

Run linting:
```bash
ruff check src/
ruff format src/
```

## UI Architecture

### Layout Structure (`core_api.py`)
The Dash app layout follows this hierarchy:
- Root container: centered, max-width 1400px, 20px/32px padding
- Database options section: Upload config file (blue), "Reload last config" (grey, hidden when no cache), "Default visualization" (green)
- Patient options section: dynamically generated based on loaded database options (auto-sized 2-column grid — adding a datasource produces a card with no layout edit needed)
- Action row: Process button (orange, primary) + Inspect button (teal)
- Progress bar: per-datasource, color-matched to the active action (orange for viz, teal for inspect); hidden when no action is running
- Annotation toolbar: type buttons (Time Event, Time Window, Point) + group management + Save/Exit — hidden until visualization succeeds
- Inspection modal: full-screen overlay, opened by Inspect button (close button in header)
- Visualization container: rendered plots with annotation tools

### UI Component Generation (`ui_components.py`)
- `dash_widget_factory()`: Creates input widgets based on schema class API_TYPE (BOOL, INT, FLOAT, TIMESTAMP, PATH_FILE, PATH_FOLDER)
- `build_ui_and_schema_registry()`: Builds UI from nested schema classes with special handling:
  - Consecutive TIMESTAMP fields (e.g., datetime_start + datetime_end) render side-by-side in a flex row
  - All other fields render vertically with 8px bottom margin
  - Returns both UI components and schema registry for validation

### Styling Patterns
**Button Colors:**
- Blue `#007bff`: Secondary actions (Upload config file)
- Grey `#6c757d`: Secondary actions (Reload last config)
- Green `#28a745`: Secondary actions (Default visualization)
- Orange `#fd7e14`: Primary action (Process visualization, larger/bold)
- Teal `#17a2b8`: Inspect data

**Card Components:**
- Border: `1px solid #dee2e6`
- Background: `#f8f9fa`
- Border radius: `6px`
- Padding: `12px` or `12px 16px`

**Section Headers:**
- H3: Bottom border `2px solid #dee2e6`, padding-bottom 8px, margin-bottom 12px
- H5: Used for datasource cards in 2-column grid

### Dynamic UI Generation (`data_callbacks.py`)
The `build_patient_options_ui` callback creates the patient options form:
1. **Global options**: Rendered in a card (data_folder, datetime_start/end side-by-side, quick_load)
2. **Specific options**: Per-datasource cards in a 2-column CSS grid
   - Only generates UI for datasources present in database_options
   - Each datasource gets its own card with H5 header
   - Grid: `gridTemplateColumns: 1fr 1fr`, `gap: 12px`

### Visibility Management
- Annotation toolbar starts hidden (`display: none`)
- `process_visualization` callback returns 6 outputs; one controls `annotation-toolbar` style
- On success: `{"display": "flex"}` shows the toolbar
- On failure/no-data: `{"display": "none"}` keeps it hidden

### Progress Reporting (`data_callbacks.py`)
- Shared state: module-level `PROCESS_PROGRESS` dict with keys `running`, `current`, `total`, `current_datasource`, `mode` (`"visualize"` or `"inspect"`).
- Written by `wrapper.main()` / `wrapper.inspect()` via a `progress_callback(current, total, name)` signature.
- Read every 500 ms by `poll_process_progress`, driven by a `dcc.Interval` enabled at action start and disabled when the callback returns.
- Bar width formula: `pct = int((current - 1) / total * 100)` — **completed** count, not in-progress. Keeps the bar from showing 100% while the last datasource is still being processed.
- Colour picked from `_PROGRESS_BAR_COLOR[mode]`: orange (`#fd7e14`) for visualize, teal (`#17a2b8`) for inspect. Label prefix from `_PROGRESS_BAR_LABEL[mode]`: "Visualizing" / "Inspecting".

### Inspection Modal (`data_callbacks.py`)
- Full-screen overlay pattern (`INSPECTION_MODAL_STYLE_SHOWN` / `_HIDDEN` in `styles.py`).
- Populated by `inspect_data` callback after `wrapper.inspect()` returns a `list[DataSourceInspection]`.
- Status badges colour-coded: `ok` green, `file_not_found` orange, `load_error` / `format_error` red.
- Results are JSON-serialised via `inspection.results_to_json` / `results_from_json` for `dcc.Store`, then re-hydrated for the CSV export flow.
- CSV download uses `dcc.Download`; column layout is derived from `ColumnInfo.DISPLAY_HEADERS` + `ColumnInfo.display_values()` (single source of truth shared with `inspection.to_text_summary()`).

## Architecture Notes

### Adding a New Data Source

**Authoritative workflow**: use `.claude/skills/new-datasource/SKILL.md`. The skill covers every
step (module, options, loader, registration, example data, tests, snapshots, docs) and enforces
the exact patterns used by the existing sources. The summary below is for quick reference only —
follow the skill for real work.

1. Create a new module under `src/clinical_scope/datasource/sources/<source_name>/` (`__init__.py`,
   `options.py`, `find_load_format.py`).
2. `options.py` must define `DATASOURCE_NAME`, `EXPECTED_FOLDER_NAME`, `FOLDER_KEYWORDS`,
   `FILE_KEYWORDS`, `FILE_EXTENSIONS` (ordered by preference), `MULTI_FILE`,
   `FILE_NAME_DATAFRAME_LOADED`, source-specific constants (timezone, `source_options`).
   Optional opt-in: `class DatabaseOptionsAdditionalInformations: TIMEZONE = "timezone"` to
   enable per-datasource timezone override via `additional_informations.timezone` (silently
   ignored when the class is absent).
3. `find_load_format.py` subclasses `DataSourceBase` with `OPTIONS_MODULE = options_naming`.
   Default `_find()`/`_format()`/`_extract_signals()`/`inspect()` cover the common path —
   typically you only implement `_load()`. `DataSourceBase._make_inspection(...)` is the base
   helper for `inspect()`; `OtherDataSource.inspect()` calls it once per file.
4. Register in `datasource/registry.py` with `@add_main_module` (keep `Other` last).
5. **Update docs**:
   - `docs/user_guide/tutorial.md` → *Patient Data & Supported Data Sources* (canonical table).
   - `CLAUDE.md` → *Supported Data Sources* bullet list above.
   - `README.md` → only if it enumerates datasources (currently it defers to the tutorial).
   - `example/option_files/*.json` if they enumerate all sources.

### Data Flow
1. User uploads `database_options.json` (or `.xlsx`) in Dash UI (or passes it to a script).
2. User configures `patient_options` (folder, time range, `quick_load`, etc.).
3. `wrapper.main()` processes each enabled datasource, calling the optional
   `progress_callback(current, total, name)` as it moves from one to the next.
4. Each datasource runs `find → load → format → extract signals`.
5. Signals grouped into `PlotGroup` → assigned to `PlotModel`; global `grouped_fields` and
   `global.loop` entries are resolved via the 3-mode lookup in `_resolve_signal_references`
   (qualified `datasource::raw_name` → display name → raw name fallback).
6. Plotly figures rendered in Dash or exported to HTML.

### Alternative Pipelines
All three share `find → load → format` and diverge only at signal extraction / output:
- **Visualization** (`wrapper.main`) — build `Signal`s → `PlotGroup`s → `PlotModel`s → figures.
- **Extraction only** (`wrapper.extract_patient` / `batch_extract` / `extract_datasource`) —
  stop at `format`, return the formatted DataFrame(s). Uses `save_path`/`save_folder` for
  explicit output; independent of the in-patient `clinical_scope_output/` cache.
- **Inspection** (`wrapper.inspect`) — stop at `format`, return a `list[DataSourceInspection]`
  describing columns, point counts, and time ranges. `OtherDataSource.inspect()` returns **one
  entry per file** (named `other::<stem>`); the wrapper handles both single and list returns.
- **Python API**: `from clinical_scope import extract_datasource, extract_patient, batch_extract`.

## Building / Deployment

The app can be packaged as a standalone executable using PyInstaller.

### Quick Build
```bash
# From project root, with venv activated
./src/clinical_scope/build_info/build.sh
```

### Build Output
- Executable: `builded_app/macOS_arm/ClinicalScope/`
- Spec file: `src/clinical_scope/build_info/core_api.spec`

See `src/clinical_scope/build_info/README.md` for detailed instructions.

## Logs

Logs are stored in `logs/` directory (gitignored):
- `logs/app/dash_api.log` - Dash application logs
- `logs/scripts/` - Script execution logs

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Project skills

Repo-specific skills live under `.claude/skills/`. Invoke with `/skill-name`.

| Skill | When to use |
|---|---|
| `/new-datasource` | Add a new medical device / file format as a datasource module |
| `/organize-patient-folder` | Reorganize a dump of clinical files into the correct per-datasource folder structure |
| `/generate-database-options` | Generate a `database_options.json` config by inspecting available signals in a patient folder |
