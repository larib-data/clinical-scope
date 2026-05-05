import clinical_scope.constants as cst

DATASOURCE_NAME = "syringe"
EXPECTED_FOLDER_NAME = "syringe"
FOLDER_KEYWORDS = ["syringe"]
FILE_KEYWORDS = ["syringe", "seringues", "syr", "sringe", "srynge", "sr"]
FILE_EXTENSIONS = [".parquet", ".csv"]
MULTI_FILE = False
FILE_NAME_DATAFRAME_LOADED = "syringe.parquet"

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
