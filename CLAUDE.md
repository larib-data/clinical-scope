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

### Script Mode (HTML Export)
```bash
python scripts/script_visualization_patient_multiple_data_sources.py <patient_options.json> <database_options.json> [--debug]
```

## Project Structure

```
src/clinical_data_visualizer/
├── dash_api/               # Dash web application
│   ├── core_api.py         # Main entry point, layout definition
│   ├── ui_components.py    # UI component builders
│   ├── callbacks/          # Dash callbacks (data & shape handling)
│   └── shape_manager.py    # Annotation shape management
├── <datasource>/           # Each data source has its own module:
│   ├── __init__.py
│   ├── options.py          # Source-specific options/constants
│   └── find_load_format.py # Data loading & processing logic
├── datasource_base.py      # Abstract base class for datasources
├── datasource_list.py      # Registry of available datasources
├── signal_container.py     # Signal, PlotGroup, PlotModel data models
├── wrapper.py              # Main processing logic
├── constants.py            # Global constants and option classes
├── helper.py               # Utility functions
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
1. User uploads `database_options.json` in Dash UI
2. User configures `patient_options` (folder, time range, etc.)
3. `wrapper.main()` processes each enabled datasource
4. Each datasource: find → load → format → extract signals
5. Signals grouped into `PlotGroup` → assigned to `PlotModel`
6. Plotly figures rendered in Dash or exported to HTML

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
