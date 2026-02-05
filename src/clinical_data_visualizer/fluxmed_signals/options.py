import clinical_data_visualizer.constants as cst

KEYWORD_FOLDER = "fluxmed"
KEYWORD_FILE = "signals"

FILE_NAME_DATAFRAME_LOADED = "fluxmed_signals.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = "timezone"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
