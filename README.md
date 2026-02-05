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

1. Upload a `database_options.json` file specifying which data sources to use
2. Configure patient options (data folder, time range, signals to display, etc.)
3. Click "Process visualization" to generate the interactive plots
4. Use the drawing tools to annotate time points or regions of interest

## Project Structure

```
src/clinical_data_visualizer/
├── dash_api/           # Dash web application
│   ├── core_api.py     # Main entry point
│   ├── ui_components.py
│   └── ...
├── philips_waves/      # Philips waveform data source
├── philips_numerics/   # Philips numeric data source
├── servo_u/            # Servo-U ventilator data source
├── fluxmed_signals/    # FluxMed signal data source
├── fluxmed_parameters/ # FluxMed parameter data source
├── eit/                # EIT data source
├── mindray/            # Mindray data source
├── syringe/            # Syringe pump data source
├── signal_container.py # Data model for signals and plots
├── wrapper.py          # Main processing logic
└── constants.py        # Configuration constants
```
