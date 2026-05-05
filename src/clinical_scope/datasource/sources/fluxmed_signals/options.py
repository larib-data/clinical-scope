import clinical_scope.constants as cst

DATASOURCE_NAME = "fluxmed_signals"
EXPECTED_FOLDER_NAME = "fluxmed_signals"
FOLDER_KEYWORDS = ["fluxmed", "signals"]
FILE_KEYWORDS = ["signals", "signal", "fluxmed"]
FILE_EXTENSIONS = [".parquet", ".txt", ".csv"]
MULTI_FILE = False

FILE_NAME_DATAFRAME_LOADED = "fluxmed_signals.parquet"
DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

# Multilingual variants of the "Time" column header produced by FluxMed exports.
# Add new language variants here as needed; comparison is always case-insensitive.
TIME_HEADER_PREFIXES: list[str] = ["Time", "Tiempo", "Tempo", "Temps", "Zeit"]


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
