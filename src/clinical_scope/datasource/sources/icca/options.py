import clinical_scope.constants as cst

DATASOURCE_NAME = "icca"
EXPECTED_FOLDER_NAME = "icca"
FOLDER_KEYWORDS = ["icca"]
FILE_KEYWORDS = [
    "pthighdensityanesthesiadata",
    "highdensityanesthesia",
    "anesthesia",
    "icca",
]
FILE_EXTENSIONS = [".csv"]
# ICCA can export these too; the loader rejects them by name rather than as "unknown".
FILE_EXTENSIONS_PLANNED = [".xml", ".json"]
MULTI_FILE = False

FILE_NAME_DATAFRAME_LOADED = "icca_loaded.parquet"

# utcmeasurementTime is recorded in UTC (naive); localize to UTC by default.
DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

# Raw column names in the ICCA PtHighDensityAnesthesiaData export.
COLUMN_ATTRIBUTE_ID = "attributeId"
COLUMN_TIME = "utcmeasurementTime"
COLUMN_VALUE = "valueNumber"
# Where a non-numeric measurement keeps its value instead of COLUMN_VALUE.
COLUMNS_VALUE_NON_NUMERIC = ["valueString", "valueDateTime", "utcValueDateTime"]

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
