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
# Timezone plots, annotations and inspect() reports are rendered in, absent a user setting.
DISPLAY_TIMEZONE = "Europe/Paris"
# Timezone a tz-naive datetime_start/datetime_end patient option is interpreted in on the
# load path. Equal to DISPLAY_TIMEZONE by convention, separate by construction: see ADR-0011.
NAIVE_BOUND_TZ = "Europe/Paris"
DATETIME_INDEX_NAME = "datetime_index"

QUALIFIED_NAME_SEPARATOR = "::"
OTHER_FILE_PREFIX = f"other{QUALIFIED_NAME_SEPARATOR}"

# Datasources dropped once 'other' gained per-file configuration: they parsed plain CSV/parquet
# and carried no format-specific logic. Their folders are still *detected* — only to tell the
# user where the data should move now. Values are the retired FOLDER_KEYWORDS, so a folder
# named "Philips Waves" is still recognized exactly as it used to be.
RETIRED_DATASOURCE_FOLDERS = {
    "philips_waves": ["philips", "waves"],
    "philips_numerics": ["philips", "numerics"],
    "syringe": ["syringe"],
}

# Safety pad added around parquet row-pushdown bounds: they are deliberately conservative-loose,
# since _filter_by_datetime remains the authoritative cut afterwards.
DATETIME_PUSHDOWN_BUFFER_SECONDS = 1.0

DEFAULT_NAME_VISUALIZATION = "visualization.html"
DEFAULT_NAME_DATABASE_OPTIONS = "database_options.json"
DEFAULT_NAME_PATIENT_OPTIONS = "patient_options.json"
DEFAULT_QUICK_LOAD = False
ANNOTATION_FILE_NAME = "annotations.json"
ANNOTATION_KEY = "annotations"
# Doubles as the HTML `pattern` attribute of the colour fields, which is implicitly anchored —
# hence `re.fullmatch` on the Python side, so both ends accept exactly the same strings.
HEX_COLOR_PATTERN = r"#?[0-9A-Fa-f]{6}"

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


class ParquetPushdownKind:
    """How a detected parquet datetime column can carry a row predicate (see io/parquet_pruning)."""

    TIMESTAMP = "timestamp"  # real timestamp column — bounds filter it directly
    EPOCH_NS = "epoch_ns"  # numeric nanoseconds since epoch — bounds convert to int first
    OTHER = "other"  # detected as the time axis, but no predicate is safe on it


class InspectionStatus:
    """``DataSourceInspection.status`` values (see datasource/inspection.py)."""

    OK = "ok"
    FILE_NOT_FOUND = "file_not_found"
    LOAD_ERROR = "load_error"
    FORMAT_ERROR = "format_error"


class PatientFolderScanStatus:
    """``PatientFolderScan.status`` values (see datasource/registry.py)."""

    OK = "ok"
    MISSING = "missing"  # nothing at that path
    IS_FILE = "is_file"  # a file where a patient folder was expected
    UNREADABLE = "unreadable"  # exists, but the OS refused to list it


class ApiType:
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

    # Per-datasource patient options are not listed here: each source declares its own in
    # its options.py, as PatientOptionsDataSourceRelative.


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
# Priority sorts subplots ascending, so an unset one must land after anything configured:
# large enough that no hand-written priority realistically reaches it.
DEFAULT_PLOT_PRIORITY = 10000
# Fixed rather than auto-scaled: colour range must stay comparable across patients for a
# trained eye reading it like a bedside monitor.
DEFAULT_SPECTROGRAM_DB_MIN = 0.0
DEFAULT_SPECTROGRAM_DB_MAX = 40.0

# Bounds for the size settings, so a typo can't produce an unrenderable figure.
SUBPLOT_HEIGHT_MIN, SUBPLOT_HEIGHT_MAX = 100, 2000
LEGEND_ENTRY_WIDTH_MIN, LEGEND_ENTRY_WIDTH_MAX = 60, 600
SPECTROGRAM_DB_BOUND_MIN, SPECTROGRAM_DB_BOUND_MAX = -100.0, 100.0

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

    # Widget-id prefix, mirroring PatientOptions.GLOBAL. Dash pattern-matching ids that stop
    # matching don't raise -- the callback just never fires -- so every Input naming one of
    # these widgets must compose it from here rather than spelling it out.
    PREFIX = "user_options"

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

    class InspectConfiguredColumnsOnly:
        ORDER = 3
        SECTION = UserOptionSection.APP_BEHAVIOR
        NAME = "inspect_configured_columns_only"
        API_TYPE = ApiType.BOOL
        DEFAULT = False
        DESCRIPTION = "Inspect: read only configured signals (parquet reads only)"

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

    class SpectrogramDbMin:
        ORDER = 11
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "spectrogram_db_min"
        API_TYPE = ApiType.FLOAT
        DEFAULT = DEFAULT_SPECTROGRAM_DB_MIN
        MIN = SPECTROGRAM_DB_BOUND_MIN
        MAX = SPECTROGRAM_DB_BOUND_MAX
        DESCRIPTION = "Spectrogram colour range fallback — minimum (dB)"

    class SpectrogramDbMax:
        ORDER = 12
        SECTION = UserOptionSection.PLOT_DEFAULTS
        NAME = "spectrogram_db_max"
        API_TYPE = ApiType.FLOAT
        DEFAULT = DEFAULT_SPECTROGRAM_DB_MAX
        MIN = SPECTROGRAM_DB_BOUND_MIN
        MAX = SPECTROGRAM_DB_BOUND_MAX
        DESCRIPTION = "Spectrogram colour range fallback — maximum (dB)"


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
    SPECTROGRAM = "spectrogram"
    PSD = "psd"
    FILES = "files"  # internal key: per-file options injected from other::filename top-level keys
    # Per-section trace styling (mode, line_width, ...) written by the user in a config file.
    # Same string as SourceOptions.TRACE_OPTIONS, the tier a module ships; the user's wins per key.
    TRACE_OPTIONS = "trace_options"

    # Trailing marker that turns a field_display entry into a prefix wildcard (e.g. "Local 1*").
    WILDCARD_SUFFIX = "*"

    KNOWN_SECTION_KEYS = frozenset(
        {
            SIGNALS,
            FIELD_DISPLAY,
            NUMERICS,
            ADDITIONAL_INFORMATIONS,
            GROUPED_FIELDS,
            LOOP,
            SPECTROGRAM,
            PSD,
            FILES,
            TRACE_OPTIONS,
        }
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

    # --- Per-spectrogram configuration (inside "spectrogram" → "<name>" dict) ---
    class SpectrogramConfig:
        SIGNAL = "signal"  # one raw name — no arithmetic, no pairs, no wildcards
        FREQ_RANGE = "freq_range"  # [min_hz, max_hz], required — no workable global default
        DB_RANGE = "db_range"  # [min_db, max_db], optional — falls back to a user option
        WINDOW_S = "window_s"  # optional override; derived from freq_min by default
        OVERLAP = "overlap"  # optional override; fixed at 50% by default

        KNOWN_KEYS = frozenset({SIGNAL, FREQ_RANGE, DB_RANGE, WINDOW_S, OVERLAP})

    # --- Per-PSD configuration (inside "psd" → "<name>" dict) ---
    class PsdConfig:
        # Plural where a spectrogram has a single SIGNAL: PSDs share a subplot, so one
        # entry overlays several. Freq/db range are shared axis properties of the whole
        # subplot, so they stay here; window_s/overlap/label are per-trace (see Entry)
        # since two traces sharing one channel need their own processing/legend.
        SIGNALS = "signals"
        FREQ_RANGE = "freq_range"  # [min_hz, max_hz], required — no workable global default
        DB_RANGE = "db_range"  # [min_db, max_db], optional — y-axis range; autoscales when unset

        KNOWN_KEYS = frozenset({SIGNALS, FREQ_RANGE, DB_RANGE})

        # --- One item of SIGNALS; a plain string is shorthand for {SIGNAL: <str>} ---
        class Entry:
            SIGNAL = "signal"
            WINDOW_S = "window_s"  # optional override; derived from freq_min by default
            OVERLAP = "overlap"  # optional override; fixed at 50% by default
            LABEL = "label"  # optional trace label; needed to tell apart 2 entries sharing a signal
            COLOR = "color"  # optional override; defaults to the source signal's own color
            LINE_DASH = "line_dash"  # optional override; defaults to the source signal's own

            KNOWN_KEYS = frozenset({SIGNAL, WINDOW_S, OVERLAP, LABEL, COLOR, LINE_DASH})

    # --- Datasource-level trace styling (inside "trace_options" dict) ---
    class TraceOptionsConfig:
        MODE = "mode"
        LINE_WIDTH = "line_width"
        LINE_DASH = "line_dash"
        OPACITY = "opacity"
        MARKER_SYMBOL = "marker_symbol"
        MARKER_SIZE = "marker_size"

        # Every name here must be a TraceOptions field: that dataclass is what actually
        # filters the block at read time, so a key absent there is silently dropped.
        # Used to warn on typos, not to gate -- see test_trace_options_known_keys_are_real.
        KNOWN_KEYS = frozenset({MODE, LINE_WIDTH, LINE_DASH, OPACITY, MARKER_SYMBOL, MARKER_SIZE})

    # --- Datasource-level numerics defaults ---
    class Numerics:
        PRIORITY = "priority"
        PERIOD_RESAMPLING = "period_resampling"

        DEFAULT_PERIOD_RESAMPLING = 1

    # --- Additional informations (timezone, etc.) ---
    class AdditionalInformations:
        # Per-datasource keys are defined in each datasource's options.py; only keys every
        # datasource shares live here, for the writers that are datasource-agnostic.
        TIMEZONE = "timezone"


class SourceOptions:
    """Keys a datasource module's own options.py may set — defaults, not user configuration."""

    # Trace styling shipped with the module; a user's DatabaseOptions.TRACE_OPTIONS wins per key.
    TRACE_OPTIONS = "trace_options"


class Spectral:
    """Defaults for spectral.py's STFT-based spectrogram computation."""

    # Cycles of the lowest frequency of interest a window must span, for the STFT to
    # resolve freq_min at all. 4-8 is the usual DSP range; 5 splits the difference.
    WINDOW_CYCLES = 5

    # Fixed by design, not user-configurable (see database_options spectrogram schema).
    OVERLAP_FRACTION = 0.5

    # Fraction of median Δt a step can deviate by and still count as "already uniform"
    # (skip interpolation). Kept tight since the reference EEG recording measured
    # jitter=0; revisit once validated against real hardware timestamp noise.
    JITTER_TOLERANCE = 0.05

    # Multiple of median Δt beyond which a step is a recording gap (masked as NaN in
    # the STFT output) rather than jitter (interpolated across).
    GAP_FACTOR = 3.0

    # Perceptually uniform and colorblind-safe, like the Okabe-Ito trace palette above.
    COLORSCALE = "Viridis"

    # Narrower than Plotly's default so a colorbar stays clear of neighboring stacked rows.
    COLORBAR_THICKNESS = 15

    # Clamp under the dB log, so a silent bin yields a floor value instead of -inf.
    POWER_FLOOR = 1e-20

    # Hover formats: precision here is fixed by the axis unit, not by the signal's own
    # y_significant_digits (that setting governs the source series, not Hz/dB).
    HOVER_DB_FORMAT = ".1f"
    # Spectrogram heatmap: Hz is the y-axis over a narrow zoomed range, one decimal reads well.
    HOVER_HEATMAP_FREQ_FORMAT = ".1f"
    # PSD: Hz spans the whole freq_range on the x-axis, so significant digits scale better.
    HOVER_PSD_FREQ_FORMAT = ".3g"


class PlotType:
    TIME_SERIES = "time_series"
    SPECTROGRAM = "spectrogram"
    PSD = "psd"
    LOOP = "loop"

    # Page order of the plot models (top to bottom); types not listed here go last.
    PAGE_ORDER = (
        TIME_SERIES,
        SPECTROGRAM,
        PSD,
        LOOP,
    )

    # --- Capability sets ---
    # Membership answers "does this plot type behave this way?", so a new plot type is a name
    # added to the sets that fit rather than a new branch inside each rendering function.

    # x-axis is time: shares a zoom range across subplots, localizes hovered x, and accepts
    # time-based annotations. Loop's x is another signal's values and PSD's is frequency.
    TIME_AXIS = (
        TIME_SERIES,
        SPECTROGRAM,
    )

    # Subplots pack side by side in a square grid instead of stacking one per row.
    GRID_LAYOUT = (LOOP,)

    # Traces carry a colorbar, which must be resized to sit against its own subplot row —
    # left alone, one colorbar spans the whole figure.
    HAS_COLORBAR = (SPECTROGRAM,)

    # Reads the user's hovermode and hover time format. Everything else keeps Plotly's default
    # ("closest"): a unified panel is meaningless with an independent x per point (loop, psd)
    # or an independent cell per pixel (spectrogram).
    UNIFIED_HOVER = (TIME_SERIES,)

    # Wrapped in a FigureResampler for dynamic downsampling on zoom/pan, and so has Plotly's
    # own zoom-in/out buttons disabled in favour of the resampler's range handling.
    RESAMPLED = (TIME_SERIES,)


# A plot type reaches its config through a database_options section of the same name, so the
# two constants must not drift apart.
for _plot_type, _section_key in (
    (PlotType.LOOP, DatabaseOptions.LOOP),
    (PlotType.SPECTROGRAM, DatabaseOptions.SPECTROGRAM),
    (PlotType.PSD, DatabaseOptions.PSD),
):
    if _plot_type != _section_key:
        msg = f"Plot type '{_plot_type}' must equal its database_options key '{_section_key}'."
        raise NotImplementedError(msg)
