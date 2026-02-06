import clinical_data_visualizer.constants as cst

EXPECTED_FOLDER_NAME = "servo_u"
FOLDER_KEYWORDS = ["servo"]
KEYWORD_FOLDER = "servo u"
KEYWORD_EXTENSION = ".sta"

FILE_NAME_DATAFRAME_LOADED = "servo_u.parquet"

DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

REFERENCE_TIME_FIELD = "Log start"  # or "PC Time"
COLUMN_RELATIVE_TIME = "Time(ms)"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
