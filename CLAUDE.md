# Clinical Data Visualizer

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
python src/clinical_data_visualizer/dash_api/core_api.py
```
Opens at http://127.0.0.1:8050

### Scripts
```bash
# Extract data without plots
python scripts/process_patient_data.py patient /data/Patient01 --database-options db.json
python scripts/process_patient_data.py batch /data/patients --output-folder /out

# Inspect available columns per datasource
python scripts/inspect_patient_data.py /data/Patient01 --database-options db.json --output-csv out.csv

# Visualize (generates HTML)
python scripts/visualization_patient_data.py /data/Patient01 --database-options db.json
```

## Project Structure

```
src/clinical_data_visualizer/
├── dash_api/               # Dash web application
│   ├── core_api.py         # Main entry point, layout definition
│   ├── ui_components.py    # UI component builders
│   ├── callbacks/          # Dash callbacks (data, shape & loop handling)
│   ├── shape_manager.py    # Annotation shape management
│   ├── styles.py           # Shared style constants (modal styles, etc.)
│   ├── validation.py       # Input validation
│   ├── helper_api.py       # API helper functions
│   └── datetime_utils.py   # Datetime utilities
├── <datasource>/           # Each data source has its own module:
│   ├── __init__.py
│   ├── options.py          # Source-specific options/constants
│   └── find_load_format.py # Data loading & processing logic
├── datasource_base.py      # Abstract base class for datasources
├── datasource_list.py      # Registry of available datasources
├── database_options_parser.py  # Normalize new/legacy JSON formats
├── database_options_xlsx.py    # XLSX → dict conversion
├── inspection.py           # Data inspection models & CSV export
├── signal_container.py     # Signal, PlotGroup, PlotModel data models
├── wrapper.py              # Main processing logic (visualization, extraction, inspection)
├── constants.py            # Global constants and option classes
├── helper.py               # Utility functions
├── utilities.py            # Additional utilities
├── data_management.py      # Data management functions
└── logger_config.py        # Logging configuration
```

### Supported Data Sources
- `philips_waves` - Philips waveform data (high-frequency signals)
- `philips_numerics` - Philips numeric/parameter data
- `eit` - EIT PulmoVista impedance data
- `fluxmed_signals` - FluxMed waveforms
- `fluxmed_parameters` - FluxMed parameters
- `servo_u` - Servo-U ventilator data
- `mindray` - Mindray scope data
- `syringe` - Syringe pump data
- `other` - Generic data source (auto-discovers CSV/parquet files)

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
~/.clinical_data_visualizer/last_database_options.json
```
On next app start, a **"Reload last config"** button (grey) appears in the Database Options section, allowing one-click restore.

**Privacy**: this file contains only signal metadata (labels, colors, units, field mappings) — no patient data or PHI. Safe to store in the home directory.

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
- Database options section: upload button (blue), "Reload last config" button (grey, hidden when no cache), or "Default visualization" button (green)
- Patient options section: dynamically generated based on loaded database options
- Process button: orange, prominent, triggers visualization
- Shape controls: dropdown + Modify/Delete buttons (hidden until visualization succeeds)
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
- Shape controls start hidden (`display: none`)
- `process_visualization` callback returns 5 outputs including `shape-controls` style
- On success: `{"display": "block"}` shows dropdown + buttons
- On failure/no-data: `{"display": "none"}` keeps them hidden

## Architecture Notes

### Adding a New Data Source
1. Create a new module under `src/clinical_data_visualizer/<source_name>/`
2. Implement `options.py` with source-specific constants
3. Create `find_load_format.py` inheriting from `DataSourceBase`:
   - Implement `_find()`: Locate data files
   - Implement `_load()`: Parse raw data to DataFrame
   - Optionally override `_format()` and `_extract_signals()`
4. Register in `datasource_list.py` with `@add_main_module` decorator

### Data Flow
1. User uploads `database_options.json` (or `.xlsx`) in Dash UI
2. User configures `patient_options` (folder, time range, etc.)
3. `wrapper.main()` processes each enabled datasource
4. Each datasource: find → load → format → extract signals
5. Signals grouped into `PlotGroup` → assigned to `PlotModel`
6. Plotly figures rendered in Dash or exported to HTML

### Alternative Pipelines
- **Extraction only** (`wrapper.extract_patient` / `batch_extract`): find → load → format, returns DataFrames without visualization
- **Inspection** (`wrapper.inspect`): find → load → format, returns column metadata (`DataSourceInspection`) for each datasource
- **Python API**: `from clinical_data_visualizer import extract_datasource, extract_patient, batch_extract`

## Building / Deployment

The app can be packaged as a standalone executable using PyInstaller.

### Quick Build
```bash
# From project root, with venv activated
./src/clinical_data_visualizer/build_info/build.sh
```

### Manual Build
```bash
pyinstaller src/clinical_data_visualizer/build_info/core_api.spec --clean --distpath builded_app/macOS_arm
```

### Build Output
- Executable: `builded_app/macOS_arm/ClinicalVisuAppAlexis/`
- Spec file: `src/clinical_data_visualizer/build_info/core_api.spec`

See `src/clinical_data_visualizer/build_info/README.md` for detailed instructions.

## Logs

Logs are stored in `logs/` directory (gitignored):
- `logs/app/dash_api.log` - Dash application logs
- `logs/scripts/` - Script execution logs
