import clinical_scope.constants as cst

DATASOURCE_NAME = "other"
EXPECTED_FOLDER_NAME = "other"
FOLDER_KEYWORDS = ["other"]
FILE_KEYWORDS = []
# Parquet first: when a folder holds both extensions for one stem, the parquet wins the
# stem dedup, and only it supports row/column pushdown at read time.
FILE_EXTENSIONS = [".parquet", ".csv"]
MULTI_FILE = True
ALLOW_QUICK_LOAD = False
CREATE_SOURCE_SYMLINK = True
FILE_NAME_DATAFRAME_LOADED = "other.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = cst.DatabaseOptions.AdditionalInformations.TIMEZONE


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
