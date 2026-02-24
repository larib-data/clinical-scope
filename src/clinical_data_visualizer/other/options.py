import clinical_data_visualizer.constants as cst

EXPECTED_FOLDER_NAME = "other"
FOLDER_KEYWORDS = ["other"]
FILE_NAME_DATAFRAME_LOADED = "other.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

CANDIDATE_LIST_DATETIME_COLUMN = ["datetime", "timestamp", "time", "date", "date_time"]
SUPPORTED_EXTENSIONS = [".csv", ".parquet"]

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines",
        "line_width": 1.5,
        "line_dash": "solid",
        "opacity": 1.0,
    }
}

DEFAULT_DATABASE_OPTIONS = {}


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift (seconds)"

    class GroupByFile:
        NAME = "group_by_file"
        API_TYPE = cst.ApiType.BOOL
        DEFAULT = True
        MANDATORY = False
        DESCRIPTION = "Group signals by source file"
