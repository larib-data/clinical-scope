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
        r"^(?i:readme)(\..+)?$",  # documentation, not device data (readme.txt collides with
        # fluxmed's .txt signal files, so extension alone can't tell them apart)
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
CACHED_DATABASE_OPTIONS_FILE_NAME = "last_database_options.json"  # signal metadata only, no PHI
USER_OPTIONS_FILE_NAME = "user_options.json"  # global user options of the person at the keyboard

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
    CHOICE = "choice"
    TIMESTAMP = "timestamp"
    DAY = "day"
    TIMEZONE = "timezone"
    PATH_FOLDER = "path_folder"
    PATH_FILE = "path_file"


class PatientOptions:
    GLOBAL = "global"

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

    class DatetimeStart:
        ORDER = 3
        NAME = "datetime_start"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time start filter"
        PLACEHOLDER = PLACEHOLDER_TIMESTAMP

    class DatetimeEnd:
        ORDER = 4
        NAME = "datetime_end"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time end filter"
        PLACEHOLDER = PLACEHOLDER_TIMESTAMP

    class QuickLoad:
        ORDER = 5
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


class TraceDefaults:
    """Per-trace rendering defaults, used when neither database nor source options set them."""

    MODE = "lines"  # "lines", "markers" or "lines+markers"
    LINE_WIDTH = 2.0
    LINE_DASH = "solid"
    OPACITY = 1.0


class Colorway:
    """Fallback trace palettes, applied only where database_options sets no per-signal color."""

    OKABE_ITO = "okabe_ito"
    TOL_MUTED = "tol_muted"
    PLOTLY = "plotly"

    # Okabe & Ito (2008): eight hues distinguishable under the common colour-vision deficiencies.
    PALETTE_OKABE_ITO = (
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#0072B2",
        "#D55E00",
        "#CC79A7",
        "#000000",
    )
    # Paul Tol's "muted" qualitative scheme: colourblind-safe, lower saturation for dense traces.
    PALETTE_TOL_MUTED = (
        "#CC6677",
        "#332288",
        "#DDCC77",
        "#117733",
        "#88CCEE",
        "#882255",
        "#44AA99",
        "#999933",
    )

    # None = leave Plotly's own colorway in place.
    PALETTES: ClassVar[dict[str, tuple[str, ...] | None]] = {
        OKABE_ITO: PALETTE_OKABE_ITO,
        TOL_MUTED: PALETTE_TOL_MUTED,
        PLOTLY: None,
    }

    CHOICES = (
        (OKABE_ITO, "Colorblind-safe (Okabe-Ito)"),
        (TOL_MUTED, "Colorblind-safe, muted (Tol)"),
        (PLOTLY, "Plotly default"),
    )


class PlotTemplate:
    """Plotly layout templates offered as a display fallback."""

    LIGHT = "plotly"  # Plotly's own default
    DARK = "plotly_dark"

    CHOICES = (
        (LIGHT, "Light"),
        (DARK, "Dark"),
    )


class HoverMode:
    """Plotly ``layout.hovermode`` values offered for time-series figures."""

    X_UNIFIED = "x unified"  # one tooltip per x position, all traces listed
    CLOSEST = "closest"  # one tooltip for the nearest point only

    CHOICES = (
        (X_UNIFIED, "Unified (all traces at that time)"),
        (CLOSEST, "Closest point only"),
    )


class HoverTimeFormat:
    """``xaxis.hoverformat`` strings for the time-series hover header (d3-time-format)."""

    TIME_ONLY = "%H:%M:%S.%3f"
    DATE_TIME = "%Y-%m-%d %H:%M:%S.%3f"

    CHOICES = (
        (TIME_ONLY, "Time only (14:23:05.123)"),
        (DATE_TIME, "Date + time (2024-01-01 14:23:05.123)"),
    )


class HtmlExport:
    """``include_plotlyjs`` modes for the HTML export."""

    CDN = "cdn"  # script tag to a CDN — a blank page on a machine with no network
    INLINE = True  # plotly.js embedded in the file (~3.5 MB), opens offline
    OMIT = False  # rely on a copy written earlier in the same file


# --- Plot display fallbacks: defaults a user option may override (ADR-0005) -----------------------
DEFAULT_SUBPLOT_HEIGHT = 300
DEFAULT_LOOP_SUBPLOT_HEIGHT = 600
DEFAULT_LOOPS_PER_ROW = 2
DEFAULT_LEGEND_ENTRY_WIDTH_MAX = 220
DEFAULT_Y_SIGNIFICANT_DIGITS = 4
DEFAULT_COLORWAY = Colorway.OKABE_ITO
DEFAULT_PLOT_TEMPLATE = PlotTemplate.LIGHT
DEFAULT_HOVERMODE = HoverMode.X_UNIFIED
DEFAULT_HOVER_TIME_FORMAT = HoverTimeFormat.TIME_ONLY

# Bounds for the size settings, so a typo can't produce an unrenderable figure.
SUBPLOT_HEIGHT_MIN, SUBPLOT_HEIGHT_MAX = 100, 2000
LEGEND_ENTRY_WIDTH_MIN, LEGEND_ENTRY_WIDTH_MAX = 60, 600

LOOPS_PER_ROW_CHOICES = ((1, "1"), (2, "2"), (3, "3"))
Y_SIGNIFICANT_DIGITS_CHOICES = ((2, "2"), (3, "3"), (4, "4"), (6, "6"))


class UserOptionSection:
    """Headers grouping the settings modal; each UserOptions field declares one via SECTION."""

    APP_BEHAVIOR = "App behavior"
    PLOT_DEFAULTS = "Plot defaults"

    # Order the headers appear in; fields are then ordered by ORDER within their own section.
    ORDER = (
        APP_BEHAVIOR,
        PLOT_DEFAULTS,
    )


class UserOptions:
    """
    Global options of the person at the keyboard (``~/.clinical_scope/user_options.json``).

    Two kinds only: app behaviour (habits) and display fallbacks. They are **not** defaults
    for patient_options fields, and they never override database_options — see ADR-0005.
    Sections are laid out by SECTION_ORDER; ORDER numbers a field inside its own section.
    """

    SECTION_ORDER = UserOptionSection.ORDER

    class SaveHtmlOnProcess:
        ORDER = 1
        SECTION = UserOptionSection.APP_BEHAVIOR
        NAME = "save_html_on_process"
        API_TYPE = ApiType.BOOL
        DEFAULT = False
        DESCRIPTION = "Save a full-resolution HTML export on each Process"

    class SelfContainedHtml:
        ORDER = 2
        SECTION = UserOptionSection.APP_BEHAVIOR
        NAME = "self_contained_html"
        API_TYPE = ApiType.BOOL
        DEFAULT = False
        DESCRIPTION = "Embed Plotly in the HTML export (opens offline, ~3.5 MB heavier)"

    class DisplayTimezone:
        ORDER = 1
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "display_timezone"
        API_TYPE = ApiType.TIMEZONE
        DEFAULT = DISPLAY_TIMEZONE
        MANDATORY = False
        DESCRIPTION = "Display timezone (IANA name) — also governs the datetime filter fields"
        PLACEHOLDER = "e.g. Europe/Paris"

    class DefaultSubplotHeight:
        ORDER = 2
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "default_subplot_height"
        API_TYPE = ApiType.INT
        DEFAULT = DEFAULT_SUBPLOT_HEIGHT
        MIN = SUBPLOT_HEIGHT_MIN
        MAX = SUBPLOT_HEIGHT_MAX
        DESCRIPTION = "Height of each time-series subplot (px)"

    class LoopSubplotHeight:
        ORDER = 3
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "loop_subplot_height"
        API_TYPE = ApiType.INT
        DEFAULT = DEFAULT_LOOP_SUBPLOT_HEIGHT
        MIN = SUBPLOT_HEIGHT_MIN
        MAX = SUBPLOT_HEIGHT_MAX
        DESCRIPTION = "Height of each loop subplot (px, square)"

    class LoopsPerRow:
        ORDER = 4
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "loops_per_row"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_LOOPS_PER_ROW
        CHOICES = LOOPS_PER_ROW_CHOICES
        DESCRIPTION = "Loop subplots per row"

    class LegendEntryWidth:
        ORDER = 5
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "legend_entry_width"
        API_TYPE = ApiType.INT
        DEFAULT = DEFAULT_LEGEND_ENTRY_WIDTH_MAX
        MIN = LEGEND_ENTRY_WIDTH_MIN
        MAX = LEGEND_ENTRY_WIDTH_MAX
        DESCRIPTION = "Maximum width of one legend entry (px)"

    class FallbackColorway:
        ORDER = 6
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "colorway"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_COLORWAY
        CHOICES = Colorway.CHOICES
        DESCRIPTION = "Palette for signals with no color in the config"

    class Template:
        ORDER = 7
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "plot_template"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_PLOT_TEMPLATE
        CHOICES = PlotTemplate.CHOICES
        DESCRIPTION = "Plot theme"

    class HoverTimeFormatOption:
        ORDER = 8
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "hover_time_format"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_HOVER_TIME_FORMAT
        CHOICES = HoverTimeFormat.CHOICES
        DESCRIPTION = "Hover: x-axis time format"

    class HoverModeOption:
        ORDER = 9
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "hovermode"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_HOVERMODE
        CHOICES = HoverMode.CHOICES
        DESCRIPTION = "Hover: panel style"

    class YSignificantDigits:
        ORDER = 10
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "y_significant_digits"
        API_TYPE = ApiType.CHOICE
        DEFAULT = DEFAULT_Y_SIGNIFICANT_DIGITS
        CHOICES = Y_SIGNIFICANT_DIGITS_CHOICES
        DESCRIPTION = "Hover: significant digits of the y value"


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
