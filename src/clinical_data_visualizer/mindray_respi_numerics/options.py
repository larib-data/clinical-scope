import clinical_data_visualizer.constants as cst

# Options for folder and file naming of the MindRay Respi Numerics datasource
EXPECTED_FOLDER_NAME = "mindray_respi_numerics"
FOLDER_KEYWORDS = ["mindray", "resp", "numeric"]
KEYWORD_FILE = (
    ""  # Empty string matches any file; extension filtering is done by FILE_EXTENSION_LIST
)
FILE_EXTENSION_LIST = [".parquet", ".csv"]

FILE_NAME_DATAFRAME_LOADED = "mindray_respi_numerics_loaded.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

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

DEFAULT_DATABASE_OPTIONS = {}


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = "timezone"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
