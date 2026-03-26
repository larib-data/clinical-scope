import clinical_data_visualizer.constants as cst

DATASOURCE_NAME = "mindray_respi_waves"
EXPECTED_FOLDER_NAME = "mindray_respi_waves"
FOLDER_KEYWORDS = ["mindray", "resp", "wave"]
FILE_KEYWORDS = [
    "respi_wave",
    "resp_wave",
    "mindray_resp",
    "mndry_resp",
    "mndry_wave",
    "resp",
    "wave",
    "mindray",
    "mndry",
]
FILE_EXTENSIONS = [".parquet", ".csv"]
MULTI_FILE = False

FILE_NAME_DATAFRAME_LOADED = "mindray_respi_waves_loaded.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines",
        "line_width": 1.0,
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
