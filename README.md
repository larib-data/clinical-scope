# Goal of the toolbox

* Create nice looking, interactive plots of physiological signals

# Installation

It is recommended to use a virtual Python environment for the installation and use of Toolboxvisualizaton. The installation procedure is the following (note that other installation procedure could be used, in particular using conda):

* open the terminal application

* go to your favorite code folder, e.g. 
```bash
cd ~/Codes
```

* clone the code
```bash
git clone git@gitlab.inria.fr:anaestassist/toolboxvisualization.git
mv toolboxvisualization ToolboxVisualization
```

* create a python virtual environment
```bash
cd ~/Codes
python3 -m venv my_virtual_env
```

* activate the virtual environment
```bash
source my_virtual_env/bin/activate
```

* install the package in editable mode and its dependencies (also in conda python environment)
```bash
python -m pip install -e ~/Codes/ToolboxVisualization
```

# API

## Time series visualizaton

Inputs: json files with the following keys
   - "data_info_list" : list of dictionaries with the following keys
       - "path" : path of data file
       - [optional] "path_static": path of static data file
       - [optional] "name" : legend of output
   - "label_correspondence" : dictionaries of correspondence between output csv file headers and displayed
           physiological quantities names. {"helen_output_field" : "displayed_name"}. In the rest of the option 
           file, the quantities are designated with their "displayed name" as defined in label_correspondence
   - "output_path" : path of the html files created by this script
   - "time_series_display_list" : list of two elements lists, corresponding to the pairs of physiological quantities that have to be ploted one vs the other.
   - [optional] "header"
   - [optional] "pv_loop"
       - "label": dictionary
           - "pressure": str, label of pressure in data
           - "volume": str, label of volume in data
           - [optional] "espvr", label of espvr in data, only used if static data provided
           - [optional] "edpvr", label of edpvr in data, only used if static data provided
       - "range": dictionnary, for plot axes limits
           - "velocity": list of 2 floats
           - "pressure": list of 2 floats
       - "figsize": dictionary
           - "height": int
           - "width": int
   - [optional] "pu_loop"
       - "label": dictionary
           - "pressure": str, label of pressure in data
           - "velocity": str, label of velocity in data
       - "range": dictionnary, for plot axes limits
           - "velocity": list of 2 floats
           - "pressure": list of 2 floats
       - "figsize": dictionary
           - "height": int
           - "width": int
       - [optional] "levelset_value_list": list of float for levelset plot
       - [optional] "time_selection": dict, to select a specific time window
           - "time_label": str
           - "time_start": float
           - "time_end": float
       - [optional] "unit_conversion": dict(str: float) ('data_label': convertion factor)
       - [optional] "unit_info": dict(str: str) ('data_label': 'unit')

## Digital twin dashboard

* The module `digital_twin_visualizaton.py` gives the tools to create a dashboard displaying element of the digital twin of a patient for a group of subsequences (of course, all subsequences must relate to a single patient).

Main option file: json file with the following keys
  - "path_data_patient": path of patient data file
  - "path_param": path of subsequence data file
  - "data_info_list_subsequence": list of dictionaries; each dictionary gives information about one of the subsequence considered. The dictionaries have the following keys:
      - "path_data_simu": path to subsequence waveform simulation results
      - "path_data_simu_static": path to subsequence static simulation results
      - "path_data_obs": path to subsequence data
      - [optional] "path_venous_return_curves": path to a csv file with the points of the venous return curve
      - [optional] "path_cardiac_output_curves": path to a csv file with the points of the cardiac output curve
      - [optional] "path_working_point": path to a csv file with the working point
      - [optional] "path_observed_points": path to a csv file with the points observed
      - "name": (str) display name of the subsequence
      - "subsequence_id": (int)
      - "time_start": (float) subsequence relative start time (relative to patient float time)
      - "time_end": (float) subsequence relative start time (relative to patient float time)
  - [optional] "data_info_global": dictionary containing global information, above the level of a subsequence. Currently it can have:
      - [optional] "path_observed_venous_function_points": path to a csv file containing points that should belong to the same venous return function, independently of subsequence. Data from this file will be grouped by label, if any.
      - [optional] "path_observed_cardiac_function_points": path to a csv file containing points that should belong to the same cardiac output function, independently of subsequence. Data from this file will be grouped by label, if any.
  - "path_output": path to output. NB: must be html file
  - "path_opt_display": path to json file specifying display options

Display option file: json file specifying display options
   - "data": dictionary of general data options with the following keys:
      - "label_correspondence": dictionary of correspondence between simulation output file headers (waveform and parameters) and displayed names. {"helen_output_field" : "displayed_name"}. In the rest of the option file, the quantities are designated with their "displayed name" as defined in label_correspondence
      - "label_correspondence_obs": dictionary of correspondence between simulation output file headers and displayed physiological quantities names. {"obs_file_field" : "displayed_name"}
      - "unit_conversion": dictionary giving the multiplicative correspondence factor for is signal {"<signal_name>": <conversion_coef>}
      - "unit_info": dictionary giving the unit of each signal in str format {"<signal_name>": (str) <unit>}
  - [optional] "waveforms": dictionary of waveforms display options with the following keys:
      - "time_series_display_list": list of two elements lists, corresponding to the pairs of physiological quantities that have to be ploted one vs the other.
      - "width": width of figure in dashboard
      - "height": height of figure in dashboard
  - [optional] "numerics": dictionary of numerics display options with the following keys:
      - "time_series_display_list": list of two elements lists, corresponding to the pairs of physiological quantities that have to be ploted one vs the other.
      - "width": width of figure in dashboard
      - "height": height of figure in dashboard
      - "period_avg": (float) averaging period for the computation of numerics
      - "time_step": (float) sampling period in observation data
      - "period_resampling": (float) period of signal resampling for final display
  - [optional] "pv_loop": dictionary of pv loop display options with the following keys:
      - "label": dictionary
          - "pressure": str, label of pressure in data
          - "volume": str, label of volume in data
          - [optional] "espvr", label of espvr in data, only used if static data provided
          - [optional] "edpvr", label of edpvr in data, only used if static data provided
      - "range": list of two float, for plot axes limits
          - "volume"
          - "pressure"
  - [optional] "pu_loop": dictionary of pu loop display options with the following keys:
      - "label": dictionary
          - "pressure": str, label of pressure in data
          - "velocity": str, label of velocity in data
      - "range": list of two float, for plot axes limits
          - "velocity"
          - "pressure"
      - [optional] "levelset_value_list": list of float for levelset plot
  - [optional] "param_gauge": dictionary of parameter gauges display options with the following keys:
      - "param_list": list of str, list of parameter to display in gauge format
      - "range": dictionary of range for each parameter : {"<param_name>": [<min_value>, < max_value>]}
  - [optional] "starling_guyton": dictionary of option that will be used if some files to be plotted in the starling guyton space have been given:
      - [optional] "natural_display_variable": __plot title option__: x-axis assumed in the files given for the starling-guyton space. If it is "right_at_mean_dia_press" or "left_at_sys_press" it will display an associated plot title, to help readability of the plot if the precise atrium pressure used is known. If nothing or something else is given, the title will be basic and won't precise anything about the variable origin.
      - [optional] "display_plot": [default]: false. If true, the starling-guyton plot will also be displayed individually
      - [optional] "path_save": [default]: None. Path to a html file. If given, the plot will indivually be saved at the location specified
      - [optional] "height": [default]: 600. Height of the starling-guyton plot
      - [optional] "width": [default]: 1200. Width of the starling-guyton plot
      - [optional] "display_plot", bool (default: false). If true, the starling-guyton plot will also be displayed individually.
      - [optional] "path_save", str | Path, (default: None). Path to a html file. If given, the starling-guyton plot will individually be saved at the location specified.
      - [optional] "height", float (default: 600). Height of the starling-guyton plot
      - [optional] "width", float (default: 1200). Width of the starling-guyton plot
      - [optional] "range": dictionary containing the plot display bounds:
          - [optional]: "pressure": list: [x_axis_low_bound, x_axis_high_bound]
          - [optional]: "flux": list: [y_axis_low_bound, y_axis_high_bound]

# Examples

## Time series visualizaton

* An example if provided in `example/basic_display`
* It can be run through `example/basic_display/run_basic_display.py`, using options defined in `example/basic_display/opt_visu_dt.json`.

## Digital twin dashboard

* An example is provided in `example/digital_twin_display`.
* The code creating the example digital twin output file can be run through `run_example_digital_twin_display.py`.

# Scripts

## Patient data visualizaton

To visualize some patient data, one can use the script `scripts/script_visualization_patient_data.py` with the path of the desired parquet file.

Options for this script are:
 * `--path_data_file`: str.
 * [optional] `--json_option_display`: str. Path to additional options for visualization (allows to select which signal to display, rename, adjust units, etc...)
 * [optional] `--do_pu_loop`: BooleanOptionalAction. Display pu-loop separately. Information about the pu-loop (such as pressure and flux labels) should be in the option display given above.
