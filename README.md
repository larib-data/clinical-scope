# Clinical Scope

Interactive visualization dashboard for clinical physiological signals built with Dash.

## Features

- Visualize time series of physiological signals from multiple clinical data sources
- Support for common clinical formats (Philips, Servo-U, FluxMed, EIT, Mindray, syringe pumps)
  plus a generic **"Other"** source that auto-discovers any CSV/Parquet file with a datetime column
- **Inspect** patient folders to preview columns, point counts, and time ranges before plotting
  (with CSV export)
- **Cross-datasource phase loops** via `global.loop` for combined pressure/volume/flow plots
- Live per-datasource progress feedback during processing and inspection
- Interactive annotations and shape drawing on plots
- Export visualizations to HTML

## Installation

1. Clone the repository:
```bash
git clone git@github.com:larib-data/clinical-scope.git
cd clinical-scope
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
python src/clinical_scope/dash_api/core_api.py
```

The application will open in your browser at `http://127.0.0.1:8050`.

### Workflow

**Option 1: Default Visualization (Quick Start)**
1. Click "Default visualization (all sources)" button
   - Automatically loads all available data sources with their default settings
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

### Inspecting Data

Before running a full visualization you can click the teal **"Inspect data"** button (or run
`scripts/inspect_patient_data.py`) to see which data sources were detected, what columns are
available, their point counts, and their time ranges — with a CSV export. See the tutorial
section *Processing the Visualization → Inspect Data* for details.

> **Note:** The "Default visualization" mode enables all registered data sources with their
> default display configurations — see the [tutorial](docs/user_guide/tutorial.md) section
> "Patient Data & Supported Data Sources" for the full list. You can still upload a custom
> `database_options.json` later to override this.

### Local Config Cache — Privacy Note

When a custom configuration file is uploaded successfully, it is automatically saved to:

```
~/.clinical_scope/last_database_options.json
```

**What this file should contains:** signal metadata only — display names, units, colors, field mappings, and groupings. **DO NOT include any patient data, file paths.**

To delete the cache, simply remove the file or the `~/.clinical_scope/` folder.

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
└── clinical_scope_output/                    # Auto-generated: cached data and outputs
```

### Data Source Folder Names

Folder names are **flexible** — they just need to contain the required keywords
(case-insensitive, any separator). A few examples:

| Data Source | Required Keywords | Recommended Name |
|-------------|-------------------|------------------|
| **Philips Waves** | `philips`, `waves` | `philips_waves` |
| **EIT (PulmoVista)** | `eit` | `eit` |
| **Other (Generic)** | `other` | `other` |

The complete list of data sources, their folder keywords, accepted file extensions, and
discovery modes is in the tutorial — see
[`docs/user_guide/tutorial.md`](docs/user_guide/tutorial.md) → *Patient Data & Supported Data Sources*.

**Single file** sources expect exactly one data file per folder. When multiple files are present,
the application resolves ambiguity automatically:

1. Only files with accepted extensions are considered (other files are ignored).
2. If the same stem exists in multiple formats (e.g., `data.csv` + `data.parquet`), the most
   preferred extension is kept (first in the list of accepted extensions).
3. If multiple stems remain, the application returns no match and logs a warning.

**All files** sources load every matching file in the folder and concatenate them. The
**Other** source is a special multi-file source: each file is treated as an independent
entry keyed by its stem (`other::<stem>` in `database_options`), so `waves.parquet` becomes
`other::waves`, `numerics.csv` becomes `other::numerics`, etc.

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
- The `clinical_scope_output/` folder is automatically created for caching processed data (`.parquet` files) and visualization outputs
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
└── clinical_scope_output/              # Created automatically
    ├── philips_waves.parquet
    └── eit.parquet
```

## Standalone Data Processing

The library provides three layered functions for preprocessing patient data (running
find → load → format) without opening the Dash UI.  Raw parquet caches are always
written to `<data_folder>/clinical_scope_output/` automatically.  Pass `save_folder` to also save
the formatted output.

### Python API

```python
from pathlib import Path
from clinical_scope import extract_datasource, extract_patient, batch_extract
from clinical_scope.helper import load_database_options_from_path

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
src/clinical_scope/
├── dash_api/               # Dash web application
│   ├── core_api.py         # Main entry point, layout definition
│   ├── ui_components.py    # UI component builders
│   ├── callbacks/          # Dash callbacks (data, annotation & loop handling)
│   ├── annotations/        # Annotation model, persistence, and rendering
│   ├── styles.py           # Shared style constants (modal styles, etc.)
│   ├── validation.py       # Input validation
│   └── helper_api.py       # API helper functions
├── datasource/             # Datasource framework
│   ├── base.py             # Abstract base class for datasources
│   ├── registry.py         # Registry of available datasources
│   ├── inspection.py       # Data inspection models & CSV export
│   ├── timing.py           # time_it decorator for performance logging
│   ├── formatting/         # Timezone normalization utilities
│   └── sources/            # One sub-package per data source
├── config/
│   └── parsing.py          # High-level config file loading (JSON & XLSX)
├── io/
│   └── file_utils.py       # File discovery and I/O helpers
├── database_options_parser.py  # Normalize new/legacy JSON formats
├── database_options_xlsx.py    # XLSX → dict conversion
├── signal_container.py     # Signal, PlotGroup, PlotModel data models
├── wrapper.py              # Main processing logic (visualization, extraction, inspection)
├── constants.py            # Global constants and option classes
└── logger_config.py        # Logging configuration
```

See [`CLAUDE.md`](CLAUDE.md) for a more detailed architecture overview and
[`docs/user_guide/tutorial.md`](docs/user_guide/tutorial.md) for the user-facing guide.
