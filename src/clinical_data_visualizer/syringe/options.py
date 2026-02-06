import clinical_data_visualizer.constants as cst

EXPECTED_FOLDER_NAME = "syringe"
FOLDER_KEYWORDS = ["syringe"]
KEYWORD_FILE = "syringe"
FILE_NAME_DATAFRAME_LOADED = "syringe.parquet"
ORDERED_PREFERED_RAW_FILES_EXTENSION = [".parquet", ".csv"]

CANDIDATE_LIST_DATETIME_COLUMN = ["time", "datetime", "date_time", "date"]

DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines+markers",
        "line_width": 2.0,
        "line_dash": "solid",
        "opacity": 1.0,
        "marker_symbol": None,
        "marker_size": None,
        "fill_color": None,
        "fill_pattern": None,
    }
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
