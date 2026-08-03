from typing import ClassVar

FOLDER_NAME_OUTPUT = "clinical_scope_output"

# Filesystem cruft to ignore when scanning a folder for real data files (each entry a regex).
JUNK_FILENAME_PATTERNS = frozenset(
    {
        r"^\..*",  # dotfiles: macOS .DS_Store/._*, git .gitkeep, Linux .directory/.Trash-*
        r"^Thumbs\.db$",  # Windows thumbnail cache
        r"^desktop\.ini$",  # Windows folder-view settings
        r"^System Volume Information$",  # Windows restore-point folder
        r"^\$RECYCLE\.BIN$",  # Windows recycle bin folder
    }
)

LIBRARY_TZ = "UTC"
DISPLAY_TIMEZONE = "Europe/Paris"

# Safety pad added around parquet row-pushdown bounds (issue #57): bounds are deliberately
# conservative-loose, since _filter_by_datetime remains the authoritative cut afterwards.
DATETIME_PUSHDOWN_BUFFER_SECONDS = 1.0

DEFAULT_NAME_VISUALIZATION = "visualization.html"
DEFAULT_NAME_DATABASE_OPTIONS = "database_options.json"
DEFAULT_NAME_PATIENT_OPTIONS = "patient_options.json"
DEFAULT_QUICK_LOAD = False
ANNOTATION_FILE_NAME = "annotations.json"
ANNOTATION_KEY = "annotations"

# Signal-free, no-PHI app state cached under the user's home (~/<CLINICAL_SCOPE_DIR_NAME>/).
CLINICAL_SCOPE_DIR_NAME = ".clinical_scope"
CACHED_DB_OPTIONS_FILE_NAME = "last_database_options.json"  # signal metadata only, no PHI
USER_OPTIONS_FILE_NAME = "user_options.json"  # per-user global preferences

PLACEHOLDER_TIMESTAMP = "YYYY-MM-DD HH:MM:SS"
PLACEHOLDER_DAY = "YYYY-MM-DD"


class DatetimeColumnDetection:
    """Tiered name search + content validation for auto-detecting a datetime column (ADR 0004)."""

    EXACT_NAMES: ClassVar[list[str]] = [
        "datetime_utc",
        "datetime",
        "date_datetime",
        "time_datetime",
        "timestamp",
        "date_time",
        "date",
    ]

    # Substring buckets, highest to lowest confidence; each entry a regex pattern string.
    # "time"/its translations exclude timeout/timezone/timestamp-style false positives.
    SUBSTRING_TIERS: ClassVar[list[str]] = [
        r"datetime",
        r"timestamp",
        r"date",
        r"utc",
        r"time(?!out|zone|stamp)",
        r"tiempo|tempo|temps|zeit",
    ]

    MIN_VALID_FRACTION = 0.9  # parseable with year in [MIN_YEAR, MAX_YEAR]
    MIN_SORTED_FRACTION = 0.9  # consecutive non-decreasing (tolerates device buffering jitter)
    MIN_YEAR, MAX_YEAR = 1990, 2100

    # Bounded-sample sizing for schema-only parquet detection
    SAMPLE_MIN_GROUPS = 2  # floor when the file has ≥2 groups: two places guard against a fluke
    SAMPLE_MAX_GROUPS = 20  # upper bound on row groups sampled (budget/file size may cut it)
    SAMPLE_ROWS_PER_BLOCK = 100_000  # rows validated per group (head slice of each)
    SAMPLE_MAX_ROW_DECODED = 1_000_000  # cap on rows decoded, but always ≥ 2 groups (below)


class ApiType:
    # To know how type should be interpreted in the API
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    TIMESTAMP = "timestamp"
    DAY = "day"
    TIMEZONE = "timezone"
    PATH_FOLDER = "path_folder"
    PATH_FILE = "path_file"


class PatientOptions:
    class PathDataFolder:
        ORDER = 1
        NAME = "data_folder"
        API_TYPE = ApiType.PATH_FOLDER
        DEFAULT = ""
        MANDATORY = True
        DESCRIPTION = "Patient folder (not a file)"
        PLACEHOLDER = "e.g. /path/to/patient_007  — the folder, not a .parquet file"

    class OutputRoot:
        ORDER = 2
        NAME = "output_root"
        API_TYPE = ApiType.PATH_FOLDER
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Output root (empty to write inside the patient folder)"
        # Output goes to <output_root>/<patient_folder_name>/clinical_scope_output/.
        PLACEHOLDER = "e.g. /clinical_scope_output — needed if input folder is read-only"

    class DisplayTimezone:
        ORDER = 3
        NAME = "display_timezone"
        API_TYPE = ApiType.TIMEZONE
        DEFAULT = DISPLAY_TIMEZONE
        MANDATORY = False
        DESCRIPTION = "Display timezone (IANA name)"
        PLACEHOLDER = "e.g. Europe/Paris"

    class DatetimeStart:
        ORDER = 4
        NAME = "datetime_start"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time start filter"
        PLACEHOLDER = PLACEHOLDER_TIMESTAMP

    class DatetimeEnd:
        ORDER = 5
        NAME = "datetime_end"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time end filter"
        PLACEHOLDER = PLACEHOLDER_TIMESTAMP

    class QuickLoad:
        ORDER = 6
        NAME = "quick_load"
        API_TYPE = ApiType.BOOL
        DEFAULT = True
        MANDATORY = False
        DESCRIPTION = "Re-use data if already loaded once"

    # class DataSourceRelative:
    # See local file 'src/clinical_scope/xxx/options.py'
    # Field 'PatientOptionsDataSourceRelative'
    # For each datasource possible additional informations
    # pass


# Subplot heights (px). Time-series default is user-tunable via UserOptions; loops stay square.
DEFAULT_SUBPLOT_HEIGHT = 300
DEFAULT_LOOP_SUBPLOT_HEIGHT = 600


class UserOptions:
    class SaveHtmlOnProcess:
        ORDER = 1
        NAME = "save_html_on_process"
        API_TYPE = ApiType.BOOL
        DEFAULT = False
        DESCRIPTION = "Save a full-resolution HTML export on each Process"

    class DefaultSubplotHeight:
        ORDER = 2
        NAME = "default_subplot_height"
        API_TYPE = ApiType.INT
        DEFAULT = DEFAULT_SUBPLOT_HEIGHT
        MIN = 100
        MAX = 2000
        DESCRIPTION = "Default height of each time-series subplot (px)"


class DatabaseOptions:
    """
    Constants for the database_options dict structure.

    Mirrors the JSON/XLSX schema::

        {
            "global": {"grouped_fields": {...}},
            "<datasource_name>": {
                "signals": {"<raw_name>": {"label": ..., "unit": ..., ...}},
                "field_display": [...],
                "numerics": {"period_resampling": ..., "priority": ...},
                "grouped_fields": {...},
                "loop": {...},
                "additional_informations": {"timezone": ...},
            },
        }
    """

    NAME = "database_options"
    API_TYPE = ApiType.PATH_FILE
    DEFAULT = ""
    MANDATORY = True
    DESCRIPTION = "Path to database options (.json)"
    EXTENSION = ".json"

    GLOBAL = "global"

    # --- Datasource section keys ---
    SIGNALS = "signals"
    FIELD_DISPLAY = "field_display"
    NUMERICS = "numerics"
    ADDITIONAL_INFORMATIONS = "additional_informations"
    GROUPED_FIELDS = "grouped_fields"
    LOOP = "loop"
    FILES = "files"  # internal key: per-file options injected from other::filename top-level keys

    # Trailing marker that turns a field_display entry into a prefix wildcard (e.g. "Local 1*").
    WILDCARD_SUFFIX = "*"

    KNOWN_SECTION_KEYS = frozenset(
        {SIGNALS, FIELD_DISPLAY, NUMERICS, ADDITIONAL_INFORMATIONS, GROUPED_FIELDS, LOOP, FILES}
    )

    # --- Per-signal configuration (inside "signals" → "<raw_name>" dict) ---
    class SignalConfig:
        LABEL = "label"
        UNIT = "unit"
        UNIT_CONVERSION = "unit_conversion"
        RANGE = "range"
        PERIOD_RESAMPLING = "period_resampling"
        PRIORITY = "priority"
        COLOR = "color"
        VISIBLE = "visible"
        LINE_DASH = "line_dash"
        HOVER_TEMPLATE = "hover_template"

        DEFAULT_LABEL = None  # default = raw_name
        DEFAULT_UNIT = "-"
        DEFAULT_UNIT_CONVERSION = 1.0

        KNOWN_KEYS = frozenset(
            {
                LABEL,
                UNIT,
                UNIT_CONVERSION,
                RANGE,
                PERIOD_RESAMPLING,
                PRIORITY,
                COLOR,
                VISIBLE,
                LINE_DASH,
                HOVER_TEMPLATE,
            }
        )

    # --- Datasource-level numerics defaults ---
    class Numerics:
        PRIORITY = "priority"
        PERIOD_RESAMPLING = "period_resampling"

        DEFAULT_PERIOD_RESAMPLING = 1

    # --- Additional informations (timezone, etc.) ---
    class AdditionalInformations:
        # Per-datasource keys defined in each datasource's options.py
        pass


class SourceOptions:
    TRACE_OPTIONS = "trace_options"


class PlotType:
    TIME_SERIES = "time_series"
    LOOP = "loop"

    # Page order of the plot models (top to bottom); types not listed here go last.
    PAGE_ORDER = (
        TIME_SERIES,
        LOOP,
    )


if PlotType.LOOP != DatabaseOptions.LOOP:
    msg = "No idea if that would work. Error here to warn you"
    raise NotImplementedError(msg)
