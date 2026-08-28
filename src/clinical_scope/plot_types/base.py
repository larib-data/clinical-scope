"""
What a plot type is, independently of any one of them.

A plot type is a module: everything that varies by plot type lives in that type's package,
and nothing outside ``plot_types/`` branches on plot type. Each package has two halves, split
by what they are allowed to import:

* ``schema.py`` -- the config half. Name, config keys, validation, reference rewriting, xlsx
  sheet, and the capability flags. Imports nothing but ``validation``, so reading or checking
  a configuration never loads a plotting library.
* ``plot.py`` -- the render half. Builds Signals, does the maths, installs the rendering.
  Imports ``signal_container``, numpy and plotly.

Everything a plot type knows travels *on the object*. A Signal carries its schema, which
answers every capability question, and its :class:`RenderSpec`, which says how to draw it --
so no render site ever looks a plot type up by name. ``registry.schema_for`` marks the one
boundary where a name is all there is: a plot type that has been through a Dash store.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from clinical_scope.validation import ValidationIssue

if TYPE_CHECKING:  # never executed, so naming Signal here closes no import cycle
    import pandas as pd

    from clinical_scope.signal_container import Signal


@dataclass(frozen=True)
class RenderSpec:
    """
    How a derived Signal wants to be drawn, installed by its ``build()`` at construction.

    Pushed rather than pulled: ``to_plotly_trace`` cannot reach for the plot type's own
    module (the import cycle above), so the plot type hands it the answer instead. A
    time_series Signal installs nothing -- Signal's own defaults *are* its behaviour.
    """

    hover_template: str | None = None
    hover_customdata: Any = None
    # Signal -> plotly trace. Set only by a type whose trace is not a Scatter at all (a
    # spectrogram is a go.Heatmap); every other type tunes the hover of a shared Scatter.
    trace_factory: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class CellReader:
    """
    The xlsx reader's cell coercions, lent to a schema for the length of one sheet.

    Passed in rather than imported: the reader imports every schema to find its sheet, so a
    schema importing the reader back would close a cycle. It also states the seam -- the
    reader owns how a cell is read, the plot type owns what a row means.
    """

    is_empty: Callable[[Any], bool]
    to_float: Callable[[Any], float | None]
    parse_groups: Callable[[Any], list[str]]

    def text(self, row: Any, column: str) -> str:
        """One cell as a stripped string, empty when the column is absent."""
        return str(row.get(column, "")).strip()

    def pair(self, row: Any, low: str, high: str) -> tuple[list[float] | None, bool]:
        """
        Read a two-column bound as ``[low, high]``, and say whether only one half was given.

        Both spectral sheets spell the same rule: a half-written pair is a mistake worth
        reporting, never a bound worth guessing the other end of.
        """
        low_value = self.to_float(row.get(low, ""))
        high_value = self.to_float(row.get(high, ""))
        if low_value is not None and high_value is not None:
            return [low_value, high_value], False
        return None, low_value is not None or high_value is not None


@dataclass(frozen=True)
class PlotBuilder:
    """
    A derived plot type's top half, as ``plot.py`` exports it.

    *build* takes every loaded signal, the configured entry's name and its config, and
    returns the Signal it describes -- or several, to overlay on one subplot. *refusals*
    names the exceptions it raises as a deliberate, reportable "no" rather than a bug.
    """

    build: Callable[[list["Signal"], str, Any], "Signal | list[Signal]"]
    refusals: tuple[type[Exception], ...] = ()


class SourceSignalNotFoundError(Exception):
    """Raised by a builder when a signal its config names isn't among the loaded signals."""


class PlotTypeArityError(Exception):
    """Raised by a builder given the wrong number of signal references."""


class PlotTypeSchema:
    """
    One plot type's leaf half: what it is called, how it behaves, how its config is spelled.

    Every default here is time_series's behaviour, so a derived type declares only its
    deltas. Subclassed once per package; the class itself, not an instance, is what the
    registry holds -- as with ``DataSourceBase``.
    """

    NAME: str

    # The ``database_options`` section that configures this type, equal to NAME. None for a
    # type that is not configured at all: time_series is every signal that loaded, not an entry.
    SECTION_KEY: str | None = None

    # --- Capabilities -----------------------------------------------------------------------
    # A flag answers "does this plot type behave this way?", so a new plot type is a handful of
    # booleans rather than a new branch inside each rendering function.

    # x-axis is time: subplots share a zoom range, the hovered x is localized, and time-based
    # annotations are accepted. A loop's x is another signal's values, a PSD's is frequency.
    TIME_AXIS = True

    # Reads the user's hovermode and hover time format. Everything else keeps Plotly's default
    # ("closest"): a unified panel is meaningless with an independent x per point (loop, psd)
    # or an independent cell per pixel (spectrogram).
    UNIFIED_HOVER = True

    # Wrapped in a FigureResampler for dynamic downsampling on zoom/pan, and so has Plotly's
    # own zoom-in/out buttons disabled in favour of the resampler's range handling.
    RESAMPLED = True

    # Subplots pack side by side in a square grid instead of stacking one per row.
    GRID_LAYOUT = False

    # Traces carry a colorbar, which must be resized to sit against its own subplot row --
    # left alone, one colorbar spans the whole figure.
    HAS_COLORBAR = False

    # Every drawn point carries the instant it was recorded even though x is not time, as
    # hover customdata and on ``data.point_time_axis``. The UI offers a time slider over the
    # plot, and a point annotation on it records a timestamp.
    POINT_TIMESTAMPS = False

    # --- Config ------------------------------------------------------------------------------
    # ``entries``, ``entry`` and ``config`` below are typed Any on purpose: they are raw user
    # JSON, of whatever shape the file happened to hold. Narrowing them is validate()'s job.

    # Keys one configured entry may set; empty when an entry is not a dict of options at all.
    KNOWN_KEYS: frozenset[str] = frozenset()

    # Optional xlsx sheet this type is authored in, and the columns it cannot be read without.
    SHEET_NAME: str | None = None
    SHEET_REQUIRED_COLUMNS: frozenset[str] = frozenset()

    @classmethod
    def validate(cls, entries: Any, path_prefix: str) -> list[ValidationIssue]:
        """
        Check this type's whole config section; *entries* is its raw, unvalidated value.

        *path_prefix* names the section's owner (a datasource, or ``other.files.<stem>``);
        every issue's path extends it, so a reader can find the entry in their own file.
        """
        section_path = f"{path_prefix}.{cls.SECTION_KEY}"
        if entries is None:
            return []
        if not isinstance(entries, dict):
            return [
                ValidationIssue(
                    severity="error",
                    path=section_path,
                    message=f"Must be a dict, got {type(entries).__name__}",
                )
            ]
        issues: list[ValidationIssue] = []
        for entry_name, entry in entries.items():
            issues.extend(cls.validate_entry(entry, f"{section_path}.{entry_name}"))
        return issues

    @classmethod
    def validate_entry(cls, entry: Any, path: str) -> list[ValidationIssue]:  # noqa: ARG003
        """Check one configured entry. Override; the base type has no entries to check."""
        return []

    @classmethod
    def map_refs(cls, config: Any, map_ref: Callable[[str], str]) -> Any:  # noqa: ARG003
        """
        Return *config* with every signal reference in it rewritten through *map_ref*.

        One walk per config shape, reused by both callers that scope references: assembly
        qualifies a per-datasource reference as ``datasource::raw_name`` (ADR-0013), and
        ``other`` scopes a per-file one as ``<stem>::<column>``. They differ only in the leaf
        operation, so only *map_ref* differs. Never raises on a malformed config -- it is
        returned untouched, for validation to report and assembly to skip as one bad plot.
        """
        return config

    @classmethod
    def read_sheet(
        cls,
        rows: "pd.DataFrame",  # noqa: ARG003
        cells: CellReader,  # noqa: ARG003
    ) -> dict[str, dict[str, Any]]:
        """
        Interpret this type's xlsx sheet as ``{datasource: {entry_name: config}}``.

        The reader transcribes and this decides what a row means, so the spreadsheet columns
        and the JSON keys -- one schema in two spellings -- cannot drift apart. *rows* is the
        sheet as a DataFrame, *cells* the reader's cell-value coercions.
        """
        return {}


class TimeSeries(PlotTypeSchema):
    """
    The substrate: every loaded signal, drawn against time.

    Degenerate on purpose -- no config section, no capability delta, no package, because
    every default above is already its behaviour. Registered all the same, so that nothing
    downstream has to special-case the one plot type that is not configured.
    """

    NAME = "time_series"


class Unknown(PlotTypeSchema):
    """
    A plot type name nothing recognises -- a typo, or a figure built before a type was removed.

    Every capability off, deliberately *not* the time_series defaults: a name the app cannot
    place should render nothing plausible rather than something that looks almost right.
    """

    NAME = ""
    TIME_AXIS = False
    UNIFIED_HOVER = False
    RESAMPLED = False
    GRID_LAYOUT = False
    HAS_COLORBAR = False
    POINT_TIMESTAMPS = False


# The roster of capability flags, so a seventh is declared in exactly one place. ``registry``
# checks Unknown turns every one of them off; a flag added here and missed there would be
# silently on for a name the app does not know.
CAPABILITIES: tuple[str, ...] = (
    "TIME_AXIS",
    "UNIFIED_HOVER",
    "RESAMPLED",
    "GRID_LAYOUT",
    "HAS_COLORBAR",
    "POINT_TIMESTAMPS",
)

FREQ_RANGE_BOUNDS = 2


def check_freq_range(freq_range: Any, path: str) -> list[ValidationIssue]:
    """
    Check the required ``freq_range`` both spectral plot types take.

    Shared because it is the same axis rule, not because the two types are related: a
    frequency band is ``[min, max]`` whatever is plotted against it.
    """
    if freq_range is not None and (
        isinstance(freq_range, list)
        and len(freq_range) == FREQ_RANGE_BOUNDS
        and all(isinstance(bound, (int, float)) for bound in freq_range)
    ):
        return []
    return [
        ValidationIssue(
            severity="error",
            path=f"{path}.freq_range",
            message=f"Must be a required 2-element list of numbers, got {freq_range!r}",
        )
    ]


def require_time_series(signal: "Signal") -> None:
    """Refuse to derive a plot from anything but a raw time-series."""
    if signal.trace_options.plot_options.schema is not TimeSeries:
        msg = f"Input signal must be of type '{TimeSeries.NAME}'."
        raise ValueError(msg)
