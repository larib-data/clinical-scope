import clinical_scope.constants as cst

DATASOURCE_NAME = "mindray_scope"
EXPECTED_FOLDER_NAME = "mindray_scope"
FOLDER_KEYWORDS = ["mindray", "scope"]
FILE_KEYWORDS = []
FILE_EXTENSIONS = [".xml", ".csv"]
MULTI_FILE = True

FILE_NAME_DATAFRAME_LOADED = "mindray_scope_waves.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"


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
