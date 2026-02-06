import clinical_data_visualizer.constants as cst

EXPECTED_FOLDER_NAME = "fluxmed_parameters"
FOLDER_KEYWORDS = ["fluxmed", "parameters"]
KEYWORD_FOLDER = "fluxmed"
KEYWORD_FILE = "parameters"

FILE_NAME_DATAFRAME_LOADED = "fluxmed_param.parquet"

DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines+markers",
        "line_width": 2.0,
        "line_dash": "solid",
        "opacity": 1.0,
        "marker_symbol": None,
        "marker_size": None,
    },
    "plot_options": {
        "fill_color": None,
        "fill_pattern": None,
    },
}


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = "timezone"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
