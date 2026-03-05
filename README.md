# Clinical Data Visualizer

Interactive visualization dashboard for clinical physiological signals built with Dash.

## Features

- Visualize time series of physiological signals from multiple data sources
- Support for various clinical data formats (Philips, Servo-U, FluxMed, EIT, etc.)
- Interactive annotations and shape drawing on plots
- Export visualizations to HTML

## Installation

1. Clone the repository:
```bash
git clone git@gitlab.inria.fr:ajanin/clinicaldatavisualizer.git
cd clinicaldatavisualizer
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install the package:
```bash
pip install -e .
```

## Usage

Run the Dash application:
```bash
python src/clinical_data_visualizer/dash_api/core_api.py
```

The application will open in your browser at `http://127.0.0.1:8050`.

### Workflow

**Option 1: Default Visualization (Quick Start)**
1. Click "Default visualization (all sources)" button
   - Automatically loads all 9 data sources with default settings
   - No `database_options.json` file needed
2. Configure patient options (data folder, time range, etc.)
3. Click "Process visualization" to generate the interactive plots
4. Use the drawing tools to annotate time points or regions of interest

**Option 2: Reload Last Config (Daily Workflow)**
1. If a custom config was previously uploaded, a grey **"Reload last config"** button appears automatically on startup
2. Click it to instantly restore the last used configuration — no file browsing needed
3. Configure patient options and click "Process visualization"

**Option 3: Custom Configuration**
1. Upload a `database_options.json` (or `.xlsx`) file specifying which data sources to use and their display settings
2. Configure patient options (data folder, time range, signals to display, etc.)
3. Click "Process visualization" to generate the interactive plots
4. Use the drawing tools to annotate time points or regions of interest

> **Note:** The "Default visualization" mode enables all available data sources (philips_waves, philips_numerics, eit, fluxmed_signals, fluxmed_parameters, servo_u, mindray_scope, mindray_respi_waves, mindray_respi_numerics, syringe, other) with their default display configurations. You can still upload a custom `database_options.json` later to override this.

### Local Config Cache — Privacy Note

When a custom configuration file is uploaded successfully, it is automatically saved to:

```
~/.clinical_data_visualizer/last_database_options.json
```

**What this file should contains:** signal metadata only — display names, units, colors, field mappings, and groupings. **DO NOT include any patient data, file paths.**

To delete the cache, simply remove the file or the `~/.clinical_data_visualizer/` folder.

## Patient Data Folder Organization

Each patient's data folder must be organized with **one subfolder per data source**. The application expects specific folder names for each type of clinical data.

### Required Folder Structure

```
Patient1/                        # Root patient folder (configure in patient_options)
├── philips_waves/               # Philips waveform data (.parquet files)
├── philips_numerics/            # Philips numeric/parameter data
├── eit/                         # EIT PulmoVista data (.asc files)
├── fluxmed_signals/             # FluxMed waveform data
├── fluxmed_parameters/          # FluxMed parameter data
├── servo_u/                     # Servo-U ventilator data (.sta files)
├── mindray_scope/               # Mindray scope data (.xml or .csv files)
├── mindray_respi_waves/         # Mindray respiratory waveforms (.parquet or .csv)
├── mindray_respi_numerics/      # Mindray respiratory parameters (.parquet or .csv)
├── syringe/                     # Syringe pump data
├── other/                       # Generic data (.csv or .parquet files)
└── tdv_visu/                    # Auto-generated: cached data and outputs
```

### Data Source Folder Names

Folder names are **flexible** - they just need to contain the required keywords (case-insensitive, any separator):

| Data Source | Required Keywords | Recommended Name | Example Alternatives |
|-------------|-------------------|------------------|---------------------|
| **Philips Waves** | `philips`, `waves` | `philips_waves` | `Philips-Waves`, `waves_philips`, `PHILIPS WAVES` |
| **Philips Numerics** | `philips`, `numerics` | `philips_numerics` | `Philips-Numerics`, `numerics-philips` |
| **EIT (PulmoVista)** | `eit` | `eit` | `EIT`, `EIT_Data` |
| **FluxMed Signals** | `fluxmed`, `signals` | `fluxmed_signals` | `FluxMed-Signals`, `signals_fluxmed` |
| **FluxMed Parameters** | `fluxmed`, `parameters` | `fluxmed_parameters` | `FluxMed_Parameters`, `parameters-fluxmed` |
| **Servo-U** | `servo` | `servo_u` | `Servo-U`, `SERVO`, `servo_data` |
| **Mindray Scope** | `mindray` | `mindray_scope` | `mindray`, `Mindray`, `MINDRAY` |
| **Mindray Respi Waves** | `mindray`, `resp`, `wave` | `mindray_respi_waves` | `mindray_resp_waves` |
| **Mindray Respi Numerics** | `mindray`, `resp`, `numeric` | `mindray_respi_numerics` | `mindray_resp_numerics` |
| **Syringe Pumps** | `syringe` | `syringe` | `Syringe`, `syringe_pumps` |
| **Other (Generic)** | `other` | `other` | `Other`, `OTHER` |

**File Types:**
- Philips Waves: `.parquet` files
- Philips Numerics: Files with "numerics" in filename
- EIT: `.asc` files
- FluxMed: Files with "signals" or "parameters" in filename
- Servo-U: `.sta` files
- Mindray Scope: `.xml` or `.csv` files
- Mindray Respi Waves: `.parquet` or `.csv` files
- Mindray Respi Numerics: `.parquet` or `.csv` files
- Syringe: Files with "syringe" in filename
- Other: `.csv` or `.parquet` files (auto-discovers with datetime column detection)

### Folder Naming Rules

✅ **Valid naming:**
- All required keywords must be present in the folder name
- Case-insensitive: `fluxmed_parameters`, `FluxMed_Parameters`, `FLUXMED-PARAMETERS` all work
- Any separator: `_`, `-`, space, or none
- Any order: `fluxmed_parameters` or `parameters_fluxmed` both work

❌ **Invalid naming:**
- Missing keywords: `fluxmed` alone won't match `fluxmed_parameters` (missing "parameters")
- Partial keywords: `flux` won't match (must be complete word "fluxmed")

### Notes

- **Only include folders for available data sources** - empty folders are fine but not required
- The `tdv_visu/` folder is automatically created for caching processed data (`.parquet` files) and visualization outputs
- Using the recommended names provides the best performance (exact match is checked first)

### Example

If you only have Philips waves and EIT data:

```
/path/to/patients/Patient001/
├── philips_waves/
│   └── waves_data.parquet
├── eit/
│   ├── recording_001.asc
│   └── recording_002.asc
└── tdv_visu/              # Created automatically
    ├── philips_waves.parquet
    └── eit.parquet
```

## Standalone Data Processing

The library provides three layered functions for preprocessing patient data (running
find → load → format) without opening the Dash UI.  Raw parquet caches are always
written to `<data_folder>/tdv_visu/` automatically.  Pass `save_folder` to also save
the formatted output.

### Python API

```python
from pathlib import Path
from clinical_data_visualizer import extract_datasource, extract_patient, batch_extract
from clinical_data_visualizer.helper import load_database_options_from_path

db_options = load_database_options_from_path(Path("example/option_files/database_options.json"))

# 1. Single datasource subfolder (auto-detects type from folder name)
df = extract_datasource(
    Path("/data/Patient01/philips_waves"),
    database_options_specific=db_options.get("philips_waves"),
    patient_options={"datetime_start": "2024-01-15 08:00:00"},
    save_path="/output/philips_waves.parquet",   # optional
)

# 2. All datasources for one patient
results = extract_patient(
    Path("/data/Patient01"),
    db_options,
    patient_options={"datetime_start": "2024-01-15 08:00:00"},
    save_folder="/output/Patient01",             # optional
)
# results = {"philips_waves": DataFrame | None, "eit": DataFrame | None, ...}

# 3. Multiple patients — pass a root directory or an explicit list
batch = batch_extract(
    Path("/data"),                               # root whose subdirs are patients
    db_options,
    save_folder="/output",                       # optional; each patient gets a subfolder
)
# batch = {"Patient01": {"philips_waves": DataFrame, ...}, "Patient02": {...}, ...}

# Explicit list variant
batch = batch_extract(
    ["/data/Patient01", "/data/Patient02"],
    db_options,
)
```

Set `"quick_load": true` in `patient_options` to reuse previously cached parquet files
on subsequent runs.

### Scripts

All three scripts share the same CLI pattern: a required `patient_folder` positional
argument, with optional `--database-options`, `--patient-options` and `--verbose` flags.

```bash
# Extract (find + load + format) without plots
python scripts/process_patient_data.py patient /data/Patient01 --verbose
python scripts/process_patient_data.py patient /data/Patient01 --database-options db.json
python scripts/process_patient_data.py batch /data/patients --output-folder /out

# Inspect available columns per datasource
python scripts/inspect_patient_data.py /data/Patient01 --verbose
python scripts/inspect_patient_data.py /data/Patient01 --database-options db.json --output-csv out.csv

# Visualize (generates HTML)
python scripts/visualization_patient_data.py /data/Patient01 --verbose
python scripts/visualization_patient_data.py /data/Patient01 --database-options db.json --debug --verbose
```

Omit `--database-options` to use all available datasources with their defaults.
Use `--patient-options opts.json` to pass datetime range, time shift, quick_load, etc.

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
├── signal_container.py     # Data model for signals and plots
├── wrapper.py              # Main processing logic
├── constants.py            # Configuration constants
├── helper.py               # Utility functions
├── utilities.py            # Additional utilities
├── data_management.py      # Data management functions
└── logger_config.py        # Logging configuration
```
