# Warning

The package is not yet released on pypi or is public. The current readme is a prep for when it will be the case.

# ClinicalScope

<p align="center">
  <strong>Multi-source time-series signal visualization for research, mainly in ICU and Machine Learning</strong><br>
  <em>Format · Visualize · Annotate · Export — no code required</em>
</p>

<p align="center">
  <a href="https://github.com/larib-data/clinical-scope/actions/workflows/ci.yml">
    <img src="https://github.com/larib-data/clinical-scope/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://pypi.org/project/clinical-scope/">
    <img src="https://img.shields.io/pypi/v/clinical-scope" alt="PyPI version" />
  </a>
  <a href="https://pypi.org/project/clinical-scope/">
    <img src="https://img.shields.io/pypi/pyversions/clinical-scope" alt="Python versions" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0" />
  </a>
</p>

---

**ClinicalScope** is an open-source, browser-based dashboard for visualizing, annotating, and extracting time-series data. Its primary domain is ICU monitoring — loading recordings from multiple clinical devices simultaneously (Philips monitors, Servo-U ventilators, EIT systems, FluxMed, Mindray, syringe pumps) — but its annotation and extraction pipeline is designed for any time-series data, making it equally useful for machine learning workflows that require labeled datasets.

## Installation

### Pre-built application (recommended)

Download the latest release for your platform from the **[Releases page](https://github.com/larib-data/clinical-scope/releases/latest)**:

| Platform | File |
|---|---|
| Windows | `ClinicalScope-windows-x86_64.zip` |
| macOS (Apple Silicon) | `ClinicalScope-macOS-arm64.zip` |
| Linux | `ClinicalScope-linux-x86_64.zip` |

Unzip and run the `ClinicalScope` executable — no Python installation required. Each bundle includes the user guide PDF and a demo database to get started immediately.

### From PyPI (Python users)

```bash
pip install clinical-scope
clinical-scope          # opens http://127.0.0.1:8050
```

> Requires Python 3.11–3.13.

### From source (developers)

```bash
git clone https://github.com/larib-data/clinical-scope.git
cd clinical-scope
python -m venv .venv              # create a virtual environment
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e .
clinical-scope
```

For the full developer setup (tests, linting, adding a datasource), see [CONTRIBUTING.md](CONTRIBUTING.md).

## Demo

![ClinicalScope demo](docs/user_guide/images/demo.gif)

## Quickstart

1. **Download** — get the latest release from the [Releases page](https://github.com/larib-data/clinical-scope/releases/latest) and unzip it
2. **Run** — launch the `ClinicalScope` executable; your browser opens at `http://127.0.0.1:8050`
3. **Load config** — click **Default visualization (all sources)** to use built-in defaults, or upload a `database_options.json` / `.xlsx` config file
4. **Set data folder** — enter the path to your patient folder (or point to the bundled `demo_database/demo_patient/` to try it immediately)
5. **Process** — click **Process visualization**; interactive plots appear in the browser
6. **Annotate** — draw time events, windows, or point annotations, then click **Save**

## Documentation

The **[user guide](docs/user_guide/tutorial.md)** is the primary reference for everything beyond the Quickstart.

| Resource | Covers |
|---|---|
| [User guide](docs/user_guide/tutorial.md) | Data folder layout, `database_options` config files, annotation tools, inspection view, CLI scripts, Python API |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, running tests, linting, adding a new datasource |

## Supported Data Sources

| Data Source | Device / Format | Folder Keywords | File Types | Typical Signals |
|---|---|---|---|---|
| Philips Waves | Philips waveform | `philips`, `waves` | `.parquet`, `.csv` | ART, PAP, CO₂, respiratory pressure/volume |
| Philips Numerics | Philips parameters | `philips`, `numerics` | `.parquet`, `.csv` | Heart rate, SpO₂, FiO₂, blood pressure |
| EIT | PulmoVista `.asc` | `eit` | `.asc` | Global/local impedance, impedance percentages |
| FluxMed Signals | FluxMed waveforms | `fluxmed`, `signals` | `.parquet`, `.txt`, `.csv` | Respiratory waveforms |
| FluxMed Parameters | FluxMed parameters | `fluxmed`, `parameters` | `.parquet`, `.txt`, `.csv` | Respiratory parameters |
| Servo-U | Servo-U ventilator `.sta` | `servo` | `.sta` | Ventilator waveforms and settings |
| Mindray Scope | Mindray monitor | `mindray` | `.xml`, `.csv` | ECG, SpO₂, pressure waveforms |
| Mindray Respi Waves | Mindray respiratory | `mindray`, `resp`, `wave` | `.parquet`, `.csv` | High-frequency respiratory waveforms |
| Mindray Respi Numerics | Mindray respiratory | `mindray`, `resp`, `numeric` | `.parquet`, `.csv` | Vt, RR, PEEP, and more |
| Syringe | Syringe pump | `syringe` | `.parquet`, `.csv` | Infusion rates and volumes |
| Other (Generic) | Any CSV / Parquet | `other` | `.csv`, `.parquet` | Any time-series with a datetime column |

Each patient folder should contain one subfolder per data source. See the [user guide](docs/user_guide/tutorial.md) → *Patient Data & Supported Data Sources* for folder naming rules and configuration details.

## Standalone Data Processing

ClinicalScope can run the full `find → load → format` pipeline without opening the UI, either via Python or command-line scripts. Raw parquet caches are always written to `<data_folder>/clinical_scope_output/` automatically; pass `save_folder` to also save formatted output elsewhere.

### Python API

```python
from pathlib import Path
from clinical_scope import extract_datasource, extract_patient, batch_extract
from clinical_scope.config.parsing import load_database_options_from_path

db_options = load_database_options_from_path(Path("database_options.json"))

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
batch = batch_extract(["/data/Patient01", "/data/Patient02"], db_options)
```

Set `"quick_load": true` in `patient_options` to reuse previously cached parquet files on subsequent runs.

### CLI Scripts

All three scripts share the same pattern: a required `patient_folder` positional argument plus optional `--database-options`, `--patient-options`, and `--verbose` flags.

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
python scripts/visualization_patient_data.py /data/Patient01 --database-options db.json
```

Omit `--database-options` to use all available datasources with their defaults. Use `--patient-options opts.json` to pass datetime range, time shift, `quick_load`, etc.

## Contributing

Contributions are welcome — bug reports, new data sources, and documentation improvements. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, running tests, linting, and the PR process.

## Citation

If you use ClinicalScope in academic work, please cite:

```bibtex
@software{clinicalscope2026,
  author    = {Janin, Alexis},
  title     = {{ClinicalScope}: Interactive Visualization Dashboard for Clinical Physiological Signals},
  url       = {https://github.com/larib-data/clinical-scope},
  version   = {0.4.1},
  year      = {2026},
  % doi     = {10.5281/zenodo.XXXXXXX},  % TODO: fill after Zenodo deposit (#46)
}
```

A [`CITATION.cff`](CITATION.cff) file is also provided for GitHub's *Cite this repository* button.

## Disclaimer

### Research Use Only — Not a Medical Device

This software is provided exclusively for scientific research purposes. It is not a medical device within the meaning of Regulation (EU) 2017/745 (MDR) and has not undergone CE marking, conformity assessment, or any regulatory authorization (CE, FDA, or other).

It must not be used for the diagnosis, monitoring, treatment, or prevention of disease, nor for any clinical decision concerning a patient. The visualizations, annotations, and formats it produces are not validated for clinical purposes, and any use beyond research is the sole responsibility of the user, who must carry out their own validation.

### Personal Data and GDPR

This software processes physiological signals that may constitute health data — i.e. personal data falling within the special categories of Article 9 of Regulation (EU) 2016/679 (GDPR). By deploying or using this software on data, you act as the data controller and assume all corresponding obligations.

## License

ClinicalScope is licensed under the [Apache License 2.0](LICENSE).

Copyright © 2026 Assistance Publique – Hôpitaux de Paris. Developed by Alexis Janin.
