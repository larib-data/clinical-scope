import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import clinical_scope.constants as cst
from clinical_scope import hover_formatters, spectral
from clinical_scope.datasource.formatting.timezone import (
    change_ndarray_timezone,
    loop_time_to_display_strings,
    resolve_display_timezone,
    to_float_seconds,
)
from clinical_scope.io.file_utils import get_column_name_from_pattern
from clinical_scope.io.paths import get_visualization_path

logger = logging.getLogger(__name__)

MAX_ALLOWED_UNITS = 2


def get_unique_or_raise(
    values: list[Any],
    attribute_name: str,
    context: str = "",
) -> Any:
    """
    Ensure all values are identical in a list.

    Raise ValueError if not. Returns the unique value (or None if list empty).
    """
    unique_values = list(set(values))
    if len(unique_values) > 1:
        msg = (
            f"We can't combine {context} with different '{attribute_name}' attributes. "
            f"Given: {unique_values}"
        )
        raise ValueError(msg)
    return unique_values[0] if unique_values else None


def compute_average_priority(items: list[Any]) -> float:
    """Compute average plot_priority, defaulting missing to 10000."""
    return float(np.mean([getattr(item, "plot_priority", 10000) or 10000 for item in items]))


def merge_y_ranges(
    signals: list["Signal"],
    unit_name: str,
) -> list[float] | None:
    """Merge y_axis_range for signals with the same unit."""
    ranges = [
        signal.trace_options.plot_options.y_axis_range
        for signal in signals
        if signal.trace_options.plot_options.y_unit_name == unit_name
        and signal.trace_options.plot_options.y_axis_range is not None
    ]
    if not ranges:
        return None
    return [min(bound[0] for bound in ranges), max(bound[1] for bound in ranges)]


@dataclass(frozen=True)
class DisplayFallbacks:
    """
    Display defaults coming from user options, threaded through the render layer.

    One carrier for every "applies where database_options is silent" value (ADR-0005): a new
    setting costs a field here plus its read site, not a new argument on Signal or PlotModel.
    Built once per run by ``wrapper.main``; the field defaults reproduce the look the app had
    before any of this was settable, so a bare ``DisplayFallbacks()`` is always safe.
    """

    subplot_height: int = cst.DEFAULT_SUBPLOT_HEIGHT
    loop_subplot_height: int = cst.DEFAULT_LOOP_SUBPLOT_HEIGHT
    loops_per_row: int = cst.DEFAULT_LOOPS_PER_ROW
    legend_entry_width: int = cst.DEFAULT_LEGEND_ENTRY_WIDTH_MAX
    y_significant_digits: int = cst.DEFAULT_Y_SIGNIFICANT_DIGITS
    colorway: str = cst.DEFAULT_COLORWAY
    template: str = cst.DEFAULT_PLOT_TEMPLATE
    hovermode: str = cst.DEFAULT_HOVERMODE
    hover_time_format: str = cst.DEFAULT_HOVER_TIME_FORMAT
    display_timezone: str = cst.DISPLAY_TIMEZONE
    spectrogram_db_range: tuple[float, float] = (
        cst.DEFAULT_SPECTROGRAM_DB_MIN,
        cst.DEFAULT_SPECTROGRAM_DB_MAX,
    )

    @classmethod
    def from_user_options(cls, user_options: dict[str, Any] | None) -> "DisplayFallbacks":
        """
        Read the display tenants of *user_options*; missing or unusable values keep defaults.

        An absent key is the normal case (a settings file predating the option), so it stays
        silent. A value that is present but discarded is logged — the settings modal already
        validates, so it only happens to a hand-edited ``user_options.json``.
        """
        options = user_options or {}
        schema = cst.UserOptions

        def bounded_number(field_schema: Any, cast: Callable[[Any], Any] = int) -> int | float:
            if field_schema.NAME not in options:
                return field_schema.DEFAULT
            try:
                value = cast(options[field_schema.NAME])
            except (TypeError, ValueError):
                logger.warning(
                    "user_options['%s'] = %r is not a number; using %s",
                    field_schema.NAME,
                    options[field_schema.NAME],
                    field_schema.DEFAULT,
                )
                return field_schema.DEFAULT
            clamped = max(field_schema.MIN, min(field_schema.MAX, value))
            if clamped != value:
                logger.warning(
                    "user_options['%s'] = %s is outside [%s, %s]; using %s",
                    field_schema.NAME,
                    value,
                    field_schema.MIN,
                    field_schema.MAX,
                    clamped,
                )
            return clamped

        def ordered_bounds(min_schema: Any, max_schema: Any) -> tuple[float, float]:
            # Each bound is in range on its own yet the pair can still be inverted, which
            # reaches Plotly as zmin > zmax and renders an unreadable scale.
            low = bounded_number(min_schema, cast=float)
            high = bounded_number(max_schema, cast=float)
            if low >= high:
                logger.warning(
                    "user_options['%s'] = %s is not below '%s' = %s; using [%s, %s]",
                    min_schema.NAME,
                    low,
                    max_schema.NAME,
                    high,
                    min_schema.DEFAULT,
                    max_schema.DEFAULT,
                )
                return (min_schema.DEFAULT, max_schema.DEFAULT)
            return (low, high)

        def one_of(field_schema: Any) -> Any:
            if field_schema.NAME not in options:
                return field_schema.DEFAULT
            value = options[field_schema.NAME]
            allowed = [choice_value for choice_value, _ in field_schema.CHOICES]
            if value not in allowed:
                logger.warning(
                    "user_options['%s'] = %r is not one of %s; using %r",
                    field_schema.NAME,
                    value,
                    allowed,
                    field_schema.DEFAULT,
                )
                return field_schema.DEFAULT
            return value

        return cls(
            subplot_height=bounded_number(schema.DefaultSubplotHeight),
            loop_subplot_height=bounded_number(schema.LoopSubplotHeight),
            loops_per_row=one_of(schema.LoopsPerRow),
            legend_entry_width=bounded_number(schema.LegendEntryWidth),
            y_significant_digits=one_of(schema.YSignificantDigits),
            colorway=one_of(schema.FallbackColorway),
            template=one_of(schema.Template),
            hovermode=one_of(schema.HoverModeOption),
            hover_time_format=one_of(schema.HoverTimeFormatOption),
            display_timezone=resolve_display_timezone(options.get(schema.DisplayTimezone.NAME)),
            spectrogram_db_range=ordered_bounds(schema.SpectrogramDbMin, schema.SpectrogramDbMax),
        )

    @property
    def colorway_palette(self) -> list[str] | None:
        """Resolved palette, or None to leave the template's own colorway in place."""
        palette = cst.Colorway.PALETTES.get(self.colorway)
        return list(palette) if palette else None

    def value_format(self, axis: str) -> str:
        """Plotly hover format for one axis value, e.g. ``%{y:.4g}``."""
        return f"%{{{axis}:.{self.y_significant_digits}g}}"

    def subplot_height_for(self, plot_type: str) -> int:
        """
        Subplot height fallback for *plot_type*.

        Grid-laid-out types get their own setting because their subplots are square, so height
        also sets width — one read site, so a new height fallback stays a one-line change.
        """
        if plot_type in cst.PlotType.GRID_LAYOUT:
            return self.loop_subplot_height
        return self.subplot_height


@dataclass
class Data:
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    timezone: str | None = None  # Stored here, not per-value in x, for efficiency.
    loop_time_axis: np.ndarray | None = None  # UTC epoch seconds (float64), only for loops
    # Hz, only for spectrograms. y then holds the 2-D power (dB), shaped (len(x), len(freq axis)).
    spectrogram_freq_axis: np.ndarray | None = None


@dataclass
class PlotOptions:
    """Plot-level options (for axis titles, ranges, legend, etc.)."""

    x_axis_title: str | None = None
    x_axis_range: list | None = None
    x_unit_name: str | None = None
    x2_axis_title: str | None = None
    x2_axis_range: list | None = None
    x2_unit_name: str | None = None
    y_axis_title: str | None = None
    y_axis_range: list[float] | None = None
    y_unit_name: str | None = None
    y2_axis_title: str | None = None
    y2_axis_range: list[float] | None = None
    y2_unit_name: str | None = None
    show_legend: bool = False
    legend_group: str | None = None
    legend_name: str | None = None
    fill_color: str | None = None
    fill_pattern: str | None = None
    square_plot: bool = False
    plot_height: int | None = None
    plot_type: str | None = None
    plot_priority: float | None = None
    display_timezone: str = field(default_factory=lambda: cst.DISPLAY_TIMEZONE)
    color_range: list[float] | None = None  # Heatmap zmin/zmax (dB), spectrogram only

    def __post_init__(self) -> None:
        if self.y_unit_name is None:
            self.y_unit_name = (
                cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT
            )  # a None unit produces terrible results downstream
        if self.plot_type is None:
            logger.warning("PlotOptions.plot_type should not be initialized to None")
        if self.plot_priority is None:
            self.plot_priority = 10000

    @staticmethod
    def combine_from_signals(signals: list["Signal"], group_name: str) -> "PlotOptions":
        """Combine the plot options from a list of signals."""
        start = time.perf_counter()

        if not signals:
            return PlotOptions()

        # --- Determine y units ---
        y_units = {}
        for signal in signals:
            key = signal.trace_options.plot_options.y_unit_name
            y_units.setdefault(key, []).append(signal)

        y_unit_list = list(y_units.keys())
        primary_unit = y_unit_list[0] if y_unit_list else None
        secondary_unit = y_unit_list[1] if len(y_unit_list) > 1 else None

        if len(y_unit_list) > MAX_ALLOWED_UNITS:
            logger.warning(
                "⚠️ Signals %s can't be plotted on one plot: more than %d units: %s",
                [signal.name for signal in signals],
                MAX_ALLOWED_UNITS,
                y_unit_list,
            )

        y_axis_title = wrap_label(f"{group_name} ({primary_unit})") if primary_unit else None
        y2_axis_title = wrap_label(f"{group_name} ({secondary_unit})") if secondary_unit else None

        y_axis_range = merge_y_ranges(signals, primary_unit)
        y2_axis_range = merge_y_ranges(signals, secondary_unit)

        # --- Determine plot_type and square_plot ---
        plot_type = get_unique_or_raise(
            [signal.trace_options.plot_options.plot_type for signal in signals],
            "plot_type",
            context="PlotOptions from signals",
        )
        square_plot = get_unique_or_raise(
            [signal.trace_options.plot_options.square_plot for signal in signals],
            "square_plot",
            context="PlotOptions from signals",
        )

        plot_priority = compute_average_priority(
            [signal.trace_options.plot_options for signal in signals]
        )

        display_timezone = get_unique_or_raise(
            [signal.trace_options.plot_options.display_timezone for signal in signals],
            "display_timezone",
            context="PlotOptions from signals",
        )

        # x-axis identity belongs to the plot type, not the signal, so signals[0] speaks for the
        # group — it is overlaid PSDs, sharing one frequency axis, that need it carried.
        first_plot_options = signals[0].trace_options.plot_options

        # --- Initialize combined PlotOptions ---
        combined = PlotOptions(
            x_axis_title=first_plot_options.x_axis_title,
            x_axis_range=first_plot_options.x_axis_range,
            x_unit_name=first_plot_options.x_unit_name,
            y_axis_title=y_axis_title,
            y_unit_name=primary_unit,
            y2_axis_title=y2_axis_title,
            y2_unit_name=secondary_unit,
            y_axis_range=y_axis_range,
            y2_axis_range=y2_axis_range,
            show_legend=True,
            plot_type=plot_type,
            square_plot=square_plot,
            plot_priority=plot_priority,
            display_timezone=display_timezone or cst.DISPLAY_TIMEZONE,
        )

        logger.debug(
            "⏳ %.4fs for PlotOptions.combine_from_signals for signals %s",
            time.perf_counter() - start,
            [signal.name for signal in signals],
        )
        return combined


@dataclass
class TraceOptions:
    mode: str | None = None  # can be "lines", "markers", "lines+markers"
    line_color: str | None = None
    line_width: float | None = None
    line_dash: str | None = None
    opacity: float | None = None
    marker_color: str | None = None
    marker_symbol: str | None = None
    marker_size: float | None = None
    visible: bool = True
    hover_template: str | None = None  # Plotly hovertemplate, or "fraction" for 1/n display
    plot_options: PlotOptions = field(default_factory=PlotOptions)

    def __post_init__(self) -> None:
        if self.mode is None:
            self.mode = cst.TraceDefaults.MODE
        if self.line_width is None:
            self.line_width = cst.TraceDefaults.LINE_WIDTH
        if self.line_dash is None:
            self.line_dash = cst.TraceDefaults.LINE_DASH
        if self.opacity is None:
            self.opacity = cst.TraceDefaults.OPACITY


@dataclass
class Metadata:
    datasource_name: str | None = None
    is_derived: bool = False
    parent_signal_name: str | None = None
    period_resampling: float | None = None
    time_shift_second: float | None = None


@dataclass
class Quality:
    is_valid: bool = True
    quality_score: float = 1.0


def _signal_utc_float_seconds(signal: "Signal") -> np.ndarray:
    """
    Return true UTC epoch float seconds for a signal's time axis.

    to_plotly_trace() shifts data.x in-place from its source timezone to naive
    DISPLAY_TIMEZONE values.  loop_from_signals() is called after that mutation,
    so data.x no longer holds UTC values.  Re-localise to data.timezone then
    convert to UTC nanoseconds via .asi8 (avoids np.issubdtype on tz-aware dtype).
    """
    if signal.data.timezone is None:
        return to_float_seconds(signal.data.x)
    return (
        pd.to_datetime(signal.data.x)
        .tz_localize(str(signal.data.timezone))
        .tz_convert(cst.LIBRARY_TZ)
        .asi8
        / 1e9
    )


@dataclass
class Signal:
    raw_name: str
    name: str
    trace: go.Scatter | None = None
    data: Data = field(default_factory=Data)
    trace_options: TraceOptions = field(default_factory=TraceOptions)
    metadata: Metadata = field(default_factory=Metadata)
    quality: Quality = field(default_factory=Quality)
    kwargs: dict = field(default_factory=dict)
    # Read by to_plotly_trace, which __post_init__ calls — so it has to be a constructor field.
    display_fallbacks: DisplayFallbacks = field(default_factory=DisplayFallbacks)
    timing: dict = field(default_factory=dict, init=False)

    @staticmethod
    def _build_trace_options(
        raw_signal_name: str,
        database_options_specific: dict[str, Any],
        source_options: dict[str, Any],
        plot_type: str,
        display_timezone: str | None = None,
    ) -> "TraceOptions":
        """Build trace options from database and source options."""
        signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS, {})
        signal_options = signals.get(raw_signal_name, {}) if isinstance(signals, dict) else {}
        numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})

        # PlotOptions fields
        plot_options_dict = source_options.get("plot_options", {})
        valid_keys_plot_options = {field_obj.name for field_obj in fields(PlotOptions)}
        additional_plot_options = {
            key: value for key, value in plot_options_dict.items() if key in valid_keys_plot_options
        }
        signal_config = cst.DatabaseOptions.SignalConfig
        name_signal = signal_options.get(signal_config.LABEL, raw_signal_name)
        range_signal_plot = signal_options.get(signal_config.RANGE)
        y_unit_name = signal_options.get(signal_config.UNIT, signal_config.DEFAULT_UNIT)
        y_axis_title_raw = f"{name_signal} ({y_unit_name or ''})"
        y_axis_title = wrap_label(y_axis_title_raw, max_line_length=12)

        # TraceOptions fields
        trace_options_dict = source_options.get(cst.SourceOptions.TRACE_OPTIONS, {})
        valid_keys_trace_options = {field_obj.name for field_obj in fields(TraceOptions)}
        additional_trace_options = {
            key: value
            for key, value in trace_options_dict.items()
            if key in valid_keys_trace_options
        }
        color = signal_options.get(signal_config.COLOR)
        plot_priority_default_db = numerics.get(cst.DatabaseOptions.Numerics.PRIORITY)
        plot_priority = signal_options.get(signal_config.PRIORITY, plot_priority_default_db)
        visible = signal_options.get(signal_config.VISIBLE, True)
        line_dash_db = signal_options.get(signal_config.LINE_DASH)
        hover_template = signal_options.get(signal_config.HOVER_TEMPLATE)

        plot_options = PlotOptions(
            y_axis_range=range_signal_plot,
            y_axis_title=y_axis_title,
            y_unit_name=y_unit_name,
            plot_type=plot_type,
            plot_priority=plot_priority,
            display_timezone=display_timezone or cst.DISPLAY_TIMEZONE,
            **additional_plot_options,
        )
        # line_dash from database_options takes precedence over source_options
        if line_dash_db is not None:
            additional_trace_options["line_dash"] = line_dash_db
        return TraceOptions(
            plot_options=plot_options,
            line_color=color,
            marker_color=color,
            visible=visible,
            hover_template=hover_template,
            **additional_trace_options,
        )

    # ---------------- Initialization Methods ----------------
    @classmethod
    def time_series_from_dataframe(
        cls,
        df: pd.DataFrame,
        raw_signal_name: str,
        source_options: dict | None = None,
        database_options_specific: dict | None = None,
        display_fallbacks: DisplayFallbacks | None = None,
    ) -> "Signal":
        start_total = time.perf_counter()
        source_options = source_options or {}
        database_options_specific = database_options_specific or {}
        display_fallbacks = display_fallbacks or DisplayFallbacks()
        timing = {}
        # ---- Step 1: metadata extraction ---------------------------------------
        signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS, {})
        signal_options = signals.get(raw_signal_name, {}) if isinstance(signals, dict) else {}
        numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})
        signal_config = cst.DatabaseOptions.SignalConfig
        name_signal = signal_options.get(signal_config.LABEL, raw_signal_name)
        unit_conversion_factor = signal_options.get(
            signal_config.UNIT_CONVERSION, signal_config.DEFAULT_UNIT_CONVERSION
        )
        period_resampling_global = numerics.get(
            cst.DatabaseOptions.Numerics.PERIOD_RESAMPLING,
            cst.DatabaseOptions.Numerics.DEFAULT_PERIOD_RESAMPLING,
        )
        period_resampling = signal_options.get(
            signal_config.PERIOD_RESAMPLING, period_resampling_global
        )
        # ---- Step 2-3: extract, prune, convert, resample ------------------------
        start = time.perf_counter()
        y_full = (
            df[get_column_name_from_pattern(df.columns, raw_signal_name)].to_numpy(dtype=np.float64)
            * unit_conversion_factor
        )
        valid_mask = np.isfinite(y_full)
        if not (0 < period_resampling < 1.0):
            x = df.index[valid_mask].to_numpy(dtype="datetime64[ns]")
            y = y_full[valid_mask]
        else:
            step = int(1 / period_resampling)
            valid_pos = np.flatnonzero(valid_mask)
            keep_pos = valid_pos[::step]
            x = df.index[keep_pos].to_numpy(dtype="datetime64[ns]")
            y = y_full[keep_pos]
        timezone = df.index.tz
        if timezone is None:
            logger.warning(
                "Dataframe.index.tz should not be none while using time_series_from_dataframe"
            )
        timing["x&y_extraction"] = time.perf_counter() - start
        # ---- Step 4: data + trace options --------------------------------------
        start = time.perf_counter()
        data = Data(
            x=x,
            y=y,
            timezone=timezone,
        )
        trace_options = cls._build_trace_options(
            raw_signal_name,
            database_options_specific,
            source_options,
            plot_type=cst.PlotType.TIME_SERIES,
            display_timezone=display_fallbacks.display_timezone,
        )
        metadata = Metadata(
            period_resampling=period_resampling,
        )
        timing["data_initialization"] = time.perf_counter() - start
        # ---- Step 5: assemble Signal instance ---------------------------------
        start = time.perf_counter()
        obj = cls(
            raw_name=raw_signal_name,
            name=name_signal,
            data=data,
            trace_options=trace_options,
            metadata=metadata,
            display_fallbacks=display_fallbacks,
        )
        timing["signal_initialization"] = time.perf_counter() - start
        # ---- Total --------------------------------------------------------------
        timing["total_time_series_from_dataframe"] = time.perf_counter() - start_total
        obj.timing = timing
        logger.debug(
            "⏳ %ss for signal '%s'. timing details: %s",
            f"{timing['total_time_series_from_dataframe']:.4f}",
            raw_signal_name,
            {key: f"{value:.4f}s" for key, value in timing.items()},
        )
        return obj

    @classmethod
    def loop_from_signals(
        cls, signal_x: "Signal", signal_y: "Signal", name: str | None = None
    ) -> "Signal":
        """Build a loop signal from two time-series; display fallbacks come from *signal_x*."""
        start_total = time.perf_counter()
        timing = {}

        if (
            signal_x.trace_options.plot_options.plot_type != cst.PlotType.TIME_SERIES
            or signal_y.trace_options.plot_options.plot_type != cst.PlotType.TIME_SERIES
        ):
            msg = "Both input signals must be of type 'time_series'."
            raise ValueError(msg)

        x_x = _signal_utc_float_seconds(signal_x)
        x_y = _signal_utc_float_seconds(signal_y)

        if len(x_x) == 0 or len(x_y) == 0:
            msg = "One or both input signals have no data points."
            raise ValueError(msg)

        t_min = max(x_x.min(), x_y.min())
        t_max = min(x_x.max(), x_y.max())

        if t_min >= t_max:
            msg = "Signals do not have overlapping time intervals."
            raise ValueError(msg)

        start = time.perf_counter()
        x_common = np.union1d(
            x_x[(x_x >= t_min) & (x_x <= t_max)], x_y[(x_y >= t_min) & (x_y <= t_max)]
        ).astype(np.float64)
        timing["x_common"] = time.perf_counter() - start

        start = time.perf_counter()

        y_x = np.interp(x_common, x_x, signal_x.data.y)
        y_y = np.interp(x_common, x_y, signal_y.data.y)

        timing["interpolation"] = time.perf_counter() - start
        start = time.perf_counter()
        data = Data(x=y_x, y=y_y, timezone=None, loop_time_axis=x_common)
        display_timezone = get_unique_or_raise(
            [
                signal_x.trace_options.plot_options.display_timezone,
                signal_y.trace_options.plot_options.display_timezone,
            ],
            "display_timezone",
            context="loop_from_signals",
        )
        plot_options = PlotOptions(
            plot_type=cst.PlotType.LOOP,
            x_unit_name=signal_x.trace_options.plot_options.y_unit_name,
            y_unit_name=signal_y.trace_options.plot_options.y_unit_name,
            x_axis_range=signal_x.trace_options.plot_options.y_axis_range,
            y_axis_range=signal_y.trace_options.plot_options.y_axis_range,
            x_axis_title=f"{signal_x.name} ({signal_x.trace_options.plot_options.y_unit_name})",
            y_axis_title=f"{signal_y.name} ({signal_y.trace_options.plot_options.y_unit_name})",
            show_legend=False,
            square_plot=True,
            display_timezone=display_timezone or cst.DISPLAY_TIMEZONE,
        )
        trace_options = TraceOptions(plot_options=plot_options)
        timing["data_trace_initialization"] = time.perf_counter() - start
        start = time.perf_counter()
        obj = cls(
            raw_name=name or f"{signal_x.raw_name}_vs_{signal_y.raw_name}",
            name=name or f"{signal_x.name} vs {signal_y.name}",
            data=data,
            trace_options=trace_options,
            metadata=Metadata(),
            display_fallbacks=signal_x.display_fallbacks,
        )
        timing["signal_initialization"] = time.perf_counter() - start
        timing["total_loop_from_signals"] = time.perf_counter() - start_total
        obj.timing = timing
        logger.debug(
            "⏳ %ss for loop signal '%s' timing details: %s",
            f"{timing['total_loop_from_signals']:.4f}",
            obj.raw_name,
            {key: f"{value:.4f}s" for key, value in timing.items()},
        )
        return obj

    @staticmethod
    def _require_time_series(signal: "Signal") -> None:
        if signal.trace_options.plot_options.plot_type != cst.PlotType.TIME_SERIES:
            msg = "Input signal must be of type 'time_series'."
            raise ValueError(msg)

    @staticmethod
    def _spectral_params(window_s: float | None, overlap: float | None) -> spectral.SpectralParams:
        """Build the DSP knobs, letting *None* mean "keep the SpectralParams default"."""
        defaults = spectral.SpectralParams()
        return spectral.SpectralParams(
            window_s=window_s,
            overlap=overlap if overlap is not None else defaults.overlap,
        )

    @classmethod
    def spectrogram_from_signal(
        cls,
        signal: "Signal",
        name: str,
        freq_range: tuple[float, float],
        db_range: list[float] | None = None,
        window_s: float | None = None,
        overlap: float | None = None,
    ) -> "Signal":
        """
        Build a spectrogram signal from one time-series; display fallbacks come from *signal*.

        Raises ``spectral.SpectralRefusalError`` when the source Signal's grid can't be safely
        turned into a spectrogram (too short, decimated, out-of-range) — callers decide whether
        that is a warning or an error.
        """
        cls._require_time_series(signal)

        times, freqs, power_db = spectral.spectrogram(
            signal.data.x,
            signal.data.y,
            freq_range=freq_range,
            period_resampling=signal.metadata.period_resampling,
            params=cls._spectral_params(window_s, overlap),
        )

        color_range = (
            list(db_range) if db_range else list(signal.display_fallbacks.spectrogram_db_range)
        )

        # signal.data.x/timezone were already converted to display timezone by signal's own
        # to_plotly_trace() (__post_init__ runs it eagerly) -- nothing left to convert here,
        # same reasoning as loop_from_signals leaving timezone unset above.
        data = Data(x=times, y=power_db, timezone=None, spectrogram_freq_axis=freqs)
        plot_options = PlotOptions(
            plot_type=cst.PlotType.SPECTROGRAM,
            y_axis_title="Frequency (Hz)",
            show_legend=False,
            color_range=color_range,
            display_timezone=signal.trace_options.plot_options.display_timezone,
        )
        trace_options = TraceOptions(plot_options=plot_options)
        return cls(
            raw_name=name,
            name=name,
            data=data,
            trace_options=trace_options,
            metadata=Metadata(),
            display_fallbacks=signal.display_fallbacks,
        )

    @classmethod
    def psd_from_signal(
        cls,
        signal: "Signal",
        psd_name: str,
        freq_range: tuple[float, float],
        db_range: list[float] | None = None,
        window_s: float | None = None,
        overlap: float | None = None,
        label: str | None = None,
        color: str | None = None,
        line_dash: str | None = None,
    ) -> "Signal":
        """
        Build one PSD signal from one time-series; display fallbacks come from *signal*.

        One trace, not one subplot: several PSDs share a subplot when a ``psd`` entry names
        several signals, so the caller groups them. Raises ``spectral.SpectralRefusalError``
        on a grid that can't be safely analysed, like ``spectrogram_from_signal``. *label*
        distinguishes two traces built from the same *signal* (e.g. compared with different
        *window_s*) that would otherwise share both name and raw_name; *color*/*line_dash*
        do the same visually, since both otherwise default to the source signal's own.
        """
        cls._require_time_series(signal)

        freqs, power_db = spectral.psd(
            signal.data.x,
            signal.data.y,
            freq_range=freq_range,
            period_resampling=signal.metadata.period_resampling,
            params=cls._spectral_params(window_s, overlap),
        )

        data = Data(x=freqs, y=power_db, timezone=None)
        plot_options = PlotOptions(
            plot_type=cst.PlotType.PSD,
            x_axis_title="Frequency (Hz)",
            x_unit_name="Hz",
            x_axis_range=list(freq_range),
            y_axis_title="Power spectral density (dB)",
            y_unit_name="dB",
            y_axis_range=list(db_range) if db_range else None,
            show_legend=False,
            display_timezone=signal.trace_options.plot_options.display_timezone,
        )
        trace_options = TraceOptions(
            plot_options=plot_options,
            # Match the source signal's colour/dash by default, so an overlay reads as the
            # same channel; both are overridable to tell apart 2 traces sharing a signal.
            line_color=color or signal.trace_options.line_color,
            marker_color=color or signal.trace_options.marker_color,
            line_dash=line_dash or signal.trace_options.line_dash,
        )
        return cls(
            # Qualified rather than the bare source raw_name: wrapper.main prunes single-signal
            # PlotGroups whose raw_name is in a global group, which would swallow the PSD too.
            raw_name=f"{psd_name}{cst.QUALIFIED_NAME_SEPARATOR}{label or signal.raw_name}",
            name=label or signal.name,
            data=data,
            trace_options=trace_options,
            metadata=Metadata(),
            display_fallbacks=signal.display_fallbacks,
        )

    # ---------------- Regular Methods ----------------
    def to_plotly_trace(self) -> go.Scatter | go.Heatmap:
        start = time.perf_counter()
        if self.trace is not None:
            logger.warning("Trace of %s will be overwritten", self.name)
        display_tz = self.trace_options.plot_options.display_timezone
        if self.data.timezone is not None:
            self.data.x, self.data.timezone = change_ndarray_timezone(
                self.data.x, self.data.timezone, display_tz
            )

        if self.trace_options.plot_options.plot_type == cst.PlotType.SPECTROGRAM:
            color_range = self.trace_options.plot_options.color_range
            # z is (freq, time): the transpose of data.y's (time, freq) shape from spectral.py,
            # since go.Heatmap indexes z as [row=y value][col=x value].
            trace = go.Heatmap(
                x=self.data.x,
                y=self.data.spectrogram_freq_axis,
                z=self.data.y.T if self.data.y is not None else None,
                colorscale=cst.Spectral.COLORSCALE,
                zmin=color_range[0] if color_range else None,
                zmax=color_range[1] if color_range else None,
                colorbar={"title": {"text": "dB"}},
                hovertemplate=(
                    f"<b>{self.name}</b><br>%{{x}}"
                    f"<br>%{{y:{cst.Spectral.HOVER_HEATMAP_FREQ_FORMAT}}} Hz"
                    f"<br>%{{z:{cst.Spectral.HOVER_DB_FORMAT}}} dB<extra></extra>"
                ),
            )
            elapsed = time.perf_counter() - start
            self.timing["to_plotly_trace"] = elapsed
            logger.debug("⏳ %.4fs for to_plotly_trace for signal '%s'", elapsed, self.name)
            return trace

        x = self.data.x
        line_dict = (
            {
                "color": self.trace_options.line_color,
                "width": self.trace_options.line_width,
                "dash": self.trace_options.line_dash,
            }
            if "lines" in self.trace_options.mode
            else None
        )
        marker_dict = (
            {
                "color": self.trace_options.marker_color,
                "symbol": self.trace_options.marker_symbol,
                "size": self.trace_options.marker_size,
            }
            if "markers" in self.trace_options.mode
            else None
        )
        y_unit_name = self.trace_options.plot_options.y_unit_name
        y_unit_suffix = (
            f" {y_unit_name}"
            if y_unit_name != cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT
            else ""
        )

        # Magic keyword in hover_template → pre-compute customdata strings
        _template = self.trace_options.hover_template
        _is_keyword = hover_formatters.is_keyword(_template)
        customdata = (
            hover_formatters.compute_customdata(self.data.y, _template) if _is_keyword else None
        )
        _y_fmt = "%{customdata}" if _is_keyword else self.display_fallbacks.value_format("y")

        if _template is not None and not _is_keyword:
            hovertemplate = _template
        elif self.trace_options.plot_options.plot_type == cst.PlotType.TIME_SERIES:
            # Compact single-line template: time is shown once in the "x unified"
            # header, so each trace only needs name + value.
            hovertemplate = f"<b>{self.name}</b>: {_y_fmt}{y_unit_suffix}<extra></extra>"
        elif self.trace_options.plot_options.plot_type == cst.PlotType.PSD:
            # x is frequency and y always dB, so neither unit comes from the signal itself.
            hovertemplate = (
                f"<b>{self.name}</b>"
                f"<br>%{{x:{cst.Spectral.HOVER_PSD_FREQ_FORMAT}}} Hz"
                f"<br>%{{y:{cst.Spectral.HOVER_DB_FORMAT}}} dB<extra></extra>"
            )
        elif self.trace_options.plot_options.plot_type == cst.PlotType.LOOP:
            x_unit_name = self.trace_options.plot_options.x_unit_name
            _x_unit_suffix = (
                f" {x_unit_name}"
                if x_unit_name != cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT
                else ""
            )
            # Keyword formatters (fraction, percentage, …) only cover one axis,
            # so they are intentionally ignored for loops to avoid asymmetric display.
            _x_fmt = self.display_fallbacks.value_format("x")
            _loop_y_fmt = self.display_fallbacks.value_format("y")
            if self.data.loop_time_axis is not None and len(self.data.loop_time_axis) > 0:
                customdata = loop_time_to_display_strings(
                    self.data.loop_time_axis, display_timezone=display_tz
                )
                _tz_abbr = (
                    pd.to_datetime(self.data.loop_time_axis[0], unit="s", utc=True)
                    .tz_convert(display_tz)
                    .tzname()
                )
                hovertemplate = (
                    f"<b>{self.name}</b><br>"
                    f"{_x_fmt}{_x_unit_suffix} | {_loop_y_fmt}{y_unit_suffix}<br>"
                    f"%{{customdata}} ({_tz_abbr})<br>"
                    "<extra></extra>"
                )
            else:
                hovertemplate = (
                    f"<b>{self.name}</b><br>"
                    f"{_x_fmt}{_x_unit_suffix} | {_loop_y_fmt}{y_unit_suffix}<br>"
                    "<extra></extra>"
                )
        else:
            hovertemplate = None
        trace = go.Scatter(
            x=x,
            y=self.data.y,
            name=self.name,
            mode=self.trace_options.mode,
            line=line_dict,
            marker=marker_dict,
            opacity=self.trace_options.opacity,
            customdata=customdata,
            hovertemplate=hovertemplate,
            visible="legendonly" if not self.trace_options.visible else True,
        )
        elapsed = time.perf_counter() - start
        self.timing["to_plotly_trace"] = elapsed
        logger.debug("⏳ %.4fs for to_plotly_trace for signal '%s'", elapsed, self.name)
        return trace

    def __post_init__(self) -> None:
        self.trace = self.to_plotly_trace()


@dataclass
class PlotGroup:
    name: str
    signals: list[Signal]
    plot_options: PlotOptions = field(init=False)
    allow_secondary_y: bool = True
    timing: dict = field(default_factory=dict)

    @classmethod
    def from_single_signal(cls, signal: Signal) -> "PlotGroup":
        start = time.perf_counter()
        plot_group = cls(name=signal.name, signals=[signal], allow_secondary_y=False)
        elapsed = time.perf_counter() - start
        plot_group.timing["from_single_signal"] = elapsed
        return plot_group

    def __post_init__(self) -> None:
        start = time.perf_counter()
        # Derive group-level plot options
        if isinstance(self.signals, Signal):
            self.signals = [self.signals]
        if len(self.signals) == 1:
            self.plot_options = self.signals[0].trace_options.plot_options
        else:
            self.plot_options = PlotOptions.combine_from_signals(self.signals, self.name)
            self.plot_options.show_legend = True
        elapsed = time.perf_counter() - start
        self.timing["__post_init__"] = elapsed

    def assign_axes(self) -> list[tuple[go.Scatter, bool]]:
        traces_with_axes = []
        for signal in self.signals:
            secondary_y = (
                signal.trace_options.plot_options.y_unit_name == self.plot_options.y2_unit_name
            )
            trace = signal.trace
            trace.showlegend = self.plot_options.show_legend
            traces_with_axes.append((signal.trace, secondary_y))
        return traces_with_axes


@dataclass
class PlotModel:
    groups: list[PlotGroup]
    square_plot: bool = False
    plot_type: str | None = None
    figure: go.Figure | None = None
    computed_height: float | None = None
    timing: dict = field(default_factory=dict)
    name: str | None = None
    # Read by to_figure, which __post_init__ calls — so it has to be a constructor field.
    display_fallbacks: DisplayFallbacks = field(default_factory=DisplayFallbacks)

    @property
    def n_cols(self) -> int:
        """
        Subplot columns of the rendered grid.

        Only loops pack side by side; everything else stacks in one column. The UI reads this
        to map a trace back to its subplot, so it must agree with what to_figure() builds.
        """
        if self.plot_type in cst.PlotType.GRID_LAYOUT and len(self.groups) > 1:
            return self.display_fallbacks.loops_per_row
        return 1

    def to_figure(self, min_spacing: float = 0.005) -> go.Figure:
        """
        Build the Plotly figure for this PlotModel's stacked/grid subplots.

        Spectrogram colorbars are sized off ``fig.data[-1]`` right after each
        ``add_trace()`` call, not off the original trace object -- ``add_trace()`` copies the
        trace into the figure, so mutations to the original are never reflected in ``fig``.
        """
        start = time.perf_counter()
        n_groups = len(self.groups)
        default_height = self.display_fallbacks.subplot_height_for(self.plot_type)
        n_cols = self.n_cols

        # Grid-laid-out plots with multiple subplots use a multi-column grid so square subplots
        # sit side-by-side instead of stacking vertically.
        if self.plot_type in cst.PlotType.GRID_LAYOUT and n_groups > 1:
            n_rows = int(np.ceil(n_groups / n_cols))
            subplot_height = self.groups[0].plot_options.plot_height or default_height
            total_fig_height = n_rows * subplot_height
            row_heights = [1.0] * n_rows
            specs = [
                [
                    {"secondary_y": True} if row * n_cols + col < n_groups else None
                    for col in range(n_cols)
                ]
                for row in range(n_rows)
            ]
            subplot_titles = [group.name for group in self.groups]
            fig_width = n_cols * subplot_height
            extra_subplot_kwargs = {"horizontal_spacing": 0.13}
            title_gap_px = 90.0
        else:
            n_rows = n_groups
            group_heights = [
                group.plot_options.plot_height or default_height for group in self.groups
            ]
            total_fig_height = np.sum(group_heights)
            row_heights = [height / total_fig_height for height in group_heights]
            specs = [[{"secondary_y": True}] for _ in range(n_rows)]
            subplot_titles = [group.name for group in self.groups]
            fig_width = total_fig_height / n_rows if self.square_plot else None
            extra_subplot_kwargs = {}
            # Aim for ~80 px between subplots to leave room for subplot titles.
            # Falls back to min_spacing so very tall figures don't get absurdly large gaps.
            title_gap_px = 80.0

        self.computed_height = total_fig_height
        spacing_from_height = (
            title_gap_px / total_fig_height if total_fig_height > 0 else min_spacing
        )
        vertical_spacing = max(min_spacing, spacing_from_height)

        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            shared_xaxes=False,
            vertical_spacing=vertical_spacing,
            specs=specs,
            row_heights=row_heights,
            subplot_titles=subplot_titles,
            **extra_subplot_kwargs,
        )

        # Map x-data type → master row for automatic shared x-axis (time-series only)
        x_type_to_master_row = {}
        for group_idx, group in enumerate(self.groups):
            plotly_row = group_idx // n_cols + 1
            plotly_col = group_idx % n_cols + 1

            traces_with_axes = group.assign_axes()
            for trace, secondary_y in traces_with_axes:
                fig.add_trace(trace, row=plotly_row, col=plotly_col, secondary_y=secondary_y)
                if self.plot_type in cst.PlotType.HAS_COLORBAR:
                    # Scope this trace's colorbar to its own row, else it spans the whole figure.
                    added_trace = fig.data[-1]
                    axis_suffix = added_trace.yaxis[1:] if added_trace.yaxis else ""
                    domain = fig.layout[f"yaxis{axis_suffix}"].domain
                    added_trace.colorbar.update(
                        y=(domain[0] + domain[1]) / 2,
                        yanchor="middle",
                        len=domain[1] - domain[0],
                        thickness=cst.Spectral.COLORBAR_THICKNESS,
                    )

            y_title = group.plot_options.y_axis_title or ""
            fig.update_yaxes(
                title_text=y_title,
                row=plotly_row,
                col=plotly_col,
                range=group.plot_options.y_axis_range,
                secondary_y=False,
            )
            if group.allow_secondary_y and len(traces_with_axes) > 1:
                second_y_title = group.plot_options.y2_axis_title or ""
                fig.update_yaxes(
                    title_text=second_y_title,
                    row=plotly_row,
                    col=plotly_col,
                    range=group.plot_options.y2_axis_range,
                    secondary_y=True,
                )
            x_title = group.plot_options.x_axis_title
            fig.update_xaxes(
                title_text=x_title,
                row=plotly_row,
                col=plotly_col,
                range=group.plot_options.x_axis_range,
            )

            # Shared x-axis only applies where x is time. A loop's x is another signal's
            # values and a PSD's is frequency, so each of their subplots stands alone.
            if self.plot_type in cst.PlotType.TIME_AXIS:
                x_data_type = type(group.signals[0].data.x)
                if x_data_type in x_type_to_master_row:
                    master_row = x_type_to_master_row[x_data_type]
                    master_ref = "x" if master_row == 1 else f"x{master_row}"
                    fig.update_xaxes(matches=master_ref, row=plotly_row, col=plotly_col)
                else:
                    x_type_to_master_row[x_data_type] = plotly_row

            if self.plot_type in cst.PlotType.RESAMPLED:
                fig.update_yaxes(modebardisable="zoominout", row=plotly_row)

        # Hover header format and panel style are user fallbacks: no database option speaks
        # about either, so they apply unconditionally to the types that want them.
        if self.plot_type in cst.PlotType.UNIFIED_HOVER:
            fig.update_xaxes(hoverformat=self.display_fallbacks.hover_time_format)
            fig.update_layout(hovermode=self.display_fallbacks.hovermode)

        fig.update_layout(
            title_text=self.name,
            height=total_fig_height,
            width=fig_width,
            showlegend=True,
            hoverlabel={"namelength": -1},
            template=self.display_fallbacks.template,
            # Plotly only draws from the colorway for traces with no explicit color, so a
            # per-signal color from database_options wins by construction (ADR-0005).
            colorway=self.display_fallbacks.colorway_palette,
            # Time-series figures autosize to the browser width; capping an entry keeps the
            # longest signal label from eating the plot area.
            legend={
                "entrywidth": self.display_fallbacks.legend_entry_width,
                "entrywidthmode": "pixels",
            },
        )

        fig.update_layout(
            modebar_remove=[
                "select2d",
                "lasso2d",
                "autoScale2d",
            ]
        )

        elapsed = time.perf_counter() - start
        self.timing["to_figure"] = elapsed
        logger.debug(
            "⏳ %.4fs for figure generation from PlotModel with plot type %s",
            elapsed,
            self.plot_type,
        )
        return fig

    def __post_init__(self) -> None:
        """Validate plot_type/square_plot consistency across groups, and build the figure."""
        groups = self.groups

        plot_type = get_unique_or_raise(
            [group.plot_options.plot_type for group in groups],
            "plot_options.plot_type",
            context="PlotGroups",
        )
        square_plot = get_unique_or_raise(
            [group.plot_options.square_plot for group in groups],
            "square_plot",
            context="PlotGroups",
        )

        self.name = plot_type
        self.plot_type = plot_type
        self.square_plot = square_plot

        self.groups = sorted(groups, key=lambda group: group.plot_options.plot_priority)
        self.figure = self.to_figure()

    @staticmethod
    def assign_plot_model(
        plot_group_list: list[PlotGroup], display_fallbacks: DisplayFallbacks | None = None
    ) -> list["PlotModel"]:
        """Assign plot groups to plot models by plot type, ordered."""
        fallbacks = display_fallbacks or DisplayFallbacks()
        groups = {}
        for plot_group in plot_group_list:
            plot_options = plot_group.plot_options
            # ADR-0005: a height from the database configuration wins; None means it was silent,
            # so the user's per-plot-type fallback fills the gap.
            if plot_options.plot_height is None:
                plot_options.plot_height = fallbacks.subplot_height_for(plot_options.plot_type)
            groups.setdefault(plot_options.plot_type, []).append(plot_group)
        page_order = cst.PlotType.PAGE_ORDER
        ordered = sorted(
            groups,
            key=lambda plot_type: (
                page_order.index(plot_type) if plot_type in page_order else len(page_order)
            ),
        )
        return [
            PlotModel(groups=groups[plot_type], display_fallbacks=fallbacks)
            for plot_type in ordered
        ]

    @staticmethod
    def to_html(
        plot_models: list["PlotModel"],
        patient_options: dict[str, Any],
        self_contained: bool = False,
    ) -> None:
        """Write every figure to the patient's visualization.html (see print_out_figure)."""
        fig_list = [
            plot_model.figure for plot_model in plot_models if plot_model.figure is not None
        ]
        if not fig_list:
            logger.warning("⚠️ PlotModel figure generation to html skipped: no figures to write")
            return
        data_folder = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        output_root = patient_options.get(cst.PatientOptions.OutputRoot.NAME) or None
        output_path = get_visualization_path(data_folder, output_root)
        start = time.perf_counter()
        print_out_figure(output_path, fig_list, self_contained=self_contained)
        elapsed = time.perf_counter() - start
        logger.debug("⏳ %.4fs for PlotModel list to html visualization", elapsed)


# ==================================================================================================
def wrap_label(text: str, max_line_length: int = 12, break_chars: str = r"[ \-_]") -> str:
    """
    Wrap a long label into multiple HTML lines (<br>) at allowed break characters.

    Used for axis titles or legends in Plotly figures.

    Args:
        text: The text to wrap.
        max_line_length: Maximum characters per line before wrapping.
        break_chars: Regex pattern of allowed break characters (default: space, hyphen, underscore).

    Returns:
        Wrapped text string with <br> line breaks.

    """
    tokens = re.split(f"({break_chars})", text)
    lines = []
    current_line = ""

    for token in tokens:
        if len(current_line + token) <= max_line_length:
            current_line += token
        else:
            if current_line.strip():
                lines.append(current_line.strip())
            current_line = token

    if current_line.strip():
        lines.append(current_line.strip())

    return "<br>".join(lines)


# ==================================================================================================
def print_out_figure(path_output: Path, fig_list: list, self_contained: bool = False) -> None:
    """
    Export Plotly figures to a single HTML file.

    With *self_contained*, plotly.js is embedded once (in the first figure; the rest reuse it)
    so the file renders on a machine with no network — at ~3.5 MB. Otherwise it is fetched
    from a CDN, which keeps the file small but shows a blank page offline.
    """
    path_output.parent.mkdir(parents=True, exist_ok=True)
    with Path.open(path_output, "w") as file_out:
        for figure_index, fig in enumerate(fig_list):
            if self_contained:
                # Embedding the ~3.5 MB bundle once per file, not once per figure.
                include_plotlyjs = (
                    cst.HtmlExport.INLINE if figure_index == 0 else cst.HtmlExport.OMIT
                )
            else:
                include_plotlyjs = cst.HtmlExport.CDN
            file_out.write(fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs))
