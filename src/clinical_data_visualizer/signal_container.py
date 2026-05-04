import logging
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer import helper, hover_formatters

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
        sig.trace_options.plot_options.y_axis_range
        for sig in signals
        if sig.trace_options.plot_options.y_unit_name == unit_name
        and sig.trace_options.plot_options.y_axis_range is not None
    ]
    if not ranges:
        return None
    return [min(r[0] for r in ranges), max(r[1] for r in ranges)]


@dataclass
class Data:
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    timezone: str | None = (
        None  # New attribute to store timezone information, more efficient than storing in x values  # noqa: E501
    )
    loop_time_axis: np.ndarray | None = None  # UTC epoch seconds (float64), only for loops


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
    plot_height: int = 300
    plot_type: str | None = None
    plot_priority: float | None = None

    def __post_init__(self) -> None:
        """Initialize PlotOptions with default values."""
        if self.y_unit_name is None:
            self.y_unit_name = (
                cst.DatabaseOptions.Signal.DEFAULT_UNIT
            )  # authorizing None here produce terrible results later
        if self.plot_type is None:
            logger.warning("PlotOptions.plot_type should not be initialized to None")
        if self.plot_priority is None:
            self.plot_priority = 10000  # By default, after everything else

    @staticmethod
    def combine_from_signals(signals: list["Signal"], group_name: str) -> "PlotOptions":
        """Combine the plot options from a list of signals."""
        start = time.perf_counter()

        if not signals:
            return PlotOptions()  # Return default if no signals

        # --- Determine y units ---
        y_units = {}
        for sig in signals:
            key = sig.trace_options.plot_options.y_unit_name
            y_units.setdefault(key, []).append(sig)

        y_unit_list = list(y_units.keys())
        primary_unit = y_unit_list[0] if y_unit_list else None
        secondary_unit = y_unit_list[1] if len(y_unit_list) > 1 else None

        if len(y_unit_list) > MAX_ALLOWED_UNITS:
            logger.warning(
                "⚠️ Signals %s can't be plotted on one plot: more than %d units: %s",
                [sig.name for sig in signals],
                MAX_ALLOWED_UNITS,
                y_unit_list,
            )

        y_axis_title = helper.wrap_label(f"{group_name} ({primary_unit})") if primary_unit else None
        y2_axis_title = (
            helper.wrap_label(f"{group_name} ({secondary_unit})") if secondary_unit else None
        )

        y_axis_range = merge_y_ranges(signals, primary_unit)
        y2_axis_range = merge_y_ranges(signals, secondary_unit)

        # --- Determine plot_type and square_plot ---
        plot_type = get_unique_or_raise(
            [sig.trace_options.plot_options.plot_type for sig in signals],
            "plot_type",
            context="PlotOptions from signals",
        )
        square_plot = get_unique_or_raise(
            [sig.trace_options.plot_options.square_plot for sig in signals],
            "square_plot",
            context="PlotOptions from signals",
        )

        plot_priority = compute_average_priority(
            [sig.trace_options.plot_options for sig in signals]
        )

        # --- Initialize combined PlotOptions ---
        combined = PlotOptions(
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
        )

        logger.debug(
            "⏳ %.4fs for PlotOptions.combine_from_signals for signals %s",
            time.perf_counter() - start,
            [sig.name for sig in signals],
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
        """Initialize TraceOptions with default values."""
        # I believe default params are better left here rather than in constants.py file ?
        if self.mode is None:
            self.mode = "lines"
        if self.line_width is None:
            self.line_width = 2.0
        if self.line_dash is None:
            self.line_dash = "solid"
        if self.opacity is None:
            self.opacity = 1.0


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


def _signal_utc_float_seconds(sig: "Signal") -> np.ndarray:
    """
    Return true UTC epoch float seconds for a signal's time axis.

    to_plotly_trace() shifts data.x in-place from its source timezone to naive
    DISPLAY_TIMEZONE values.  loop_from_signals() is called after that mutation,
    so data.x no longer holds UTC values.  Re-localise to data.timezone then
    convert to UTC nanoseconds via .asi8 (avoids np.issubdtype on tz-aware dtype).
    """
    if sig.data.timezone is None:
        return helper.to_float_seconds(sig.data.x)
    return (
        pd.to_datetime(sig.data.x)
        .tz_localize(str(sig.data.timezone))
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
    # Dictionary to store time spent in each step
    timing: dict = field(default_factory=dict, init=False)

    @staticmethod
    def _build_trace_options(
        raw_signal_name: str,
        database_options_specific: dict[str, Any],
        source_options: dict[str, Any],
        plot_type: str,
    ) -> "TraceOptions":
        """Build trace options from database and source options."""
        signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS, {})
        sig = signals.get(raw_signal_name, {}) if isinstance(signals, dict) else {}
        numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})

        # PlotOptions fields
        plot_options_dict = source_options.get("plot_options", {})
        valid_keys_plot_options = {f.name for f in fields(PlotOptions)}
        additional_plot_options = {
            k: v for k, v in plot_options_dict.items() if k in valid_keys_plot_options
        }
        sig_cst = cst.DatabaseOptions.Signal
        name_signal = sig.get(sig_cst.LABEL, raw_signal_name)
        range_signal_plot = sig.get(sig_cst.RANGE)
        y_unit_name = sig.get(sig_cst.UNIT, sig_cst.DEFAULT_UNIT)
        y_axis_title_raw = f"{name_signal} ({y_unit_name or ''})"
        y_axis_title = helper.wrap_label(y_axis_title_raw, max_line_length=12)

        # TraceOptions fields
        trace_options_dict = source_options.get(cst.SourceOptions.TRACE_OPTIONS, {})
        valid_keys_trace_options = {f.name for f in fields(TraceOptions)}
        additional_trace_options = {
            k: v for k, v in trace_options_dict.items() if k in valid_keys_trace_options
        }
        color = sig.get(sig_cst.COLOR)
        plot_priority_default_db = numerics.get(cst.DatabaseOptions.Numerics.PRIORITY)
        plot_priority = sig.get(sig_cst.PRIORITY, plot_priority_default_db)
        visible = sig.get(sig_cst.VISIBLE, True)
        line_dash_db = sig.get(sig_cst.LINE_DASH)
        hover_template = sig.get(sig_cst.HOVER_TEMPLATE)

        plot_options = PlotOptions(
            y_axis_range=range_signal_plot,
            y_axis_title=y_axis_title,
            y_unit_name=y_unit_name,
            plot_type=plot_type,
            plot_priority=plot_priority,
            # Any other field
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
            # Any other field
            **additional_trace_options,
        )

    # ---------------- Initialization Methods ----------------
    @classmethod
    def time_series_from_dataframe(
        cls,
        df: pd.DataFrame,
        raw_signal_name: str,
        source_options: dict | None = None,
        patient_options: dict | None = None,
        database_options_specific: dict | None = None,
    ) -> "Signal":
        start_total = time.perf_counter()
        source_options = source_options or {}
        patient_options = patient_options or {}
        database_options_specific = database_options_specific or {}
        timing = {}
        # ---- Step 1: metadata extraction ---------------------------------------
        signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS, {})
        sig = signals.get(raw_signal_name, {}) if isinstance(signals, dict) else {}
        numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})
        sig_cst = cst.DatabaseOptions.Signal
        name_signal = sig.get(sig_cst.LABEL, raw_signal_name)
        unit_conversion_factor = sig.get(sig_cst.UNIT_CONVERSION, sig_cst.DEFAULT_UNIT_CONVERSION)
        p_global = numerics.get(
            cst.DatabaseOptions.Numerics.PERIOD_RESAMPLING,
            cst.DatabaseOptions.Numerics.DEFAULT_PERIOD_RESAMPLING,
        )
        p = sig.get(sig_cst.PERIOD_RESAMPLING, p_global)
        # ---- Step 2-3: extract, prune, convert, resample ------------------------
        start = time.perf_counter()
        y_full = (
            df[helper.get_column_name_from_pattern(df.columns, raw_signal_name)].to_numpy(
                dtype=np.float64
            )
            * unit_conversion_factor
        )
        valid_mask = np.isfinite(y_full)
        if not (0 < p < 1.0):
            x = df.index[valid_mask].to_numpy(dtype="datetime64[ns]")
            y = y_full[valid_mask]
        else:
            step = int(1 / p)
            valid_pos = np.flatnonzero(valid_mask)
            keep_pos = valid_pos[::step]
            x = df.index[keep_pos].to_numpy(dtype="datetime64[ns]")
            y = y_full[keep_pos]
        # Extract timezone information
        timezone = df.index.tz  # Extract timezone information
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
            timezone=timezone,  # Store the timezone information
        )
        trace_options = cls._build_trace_options(
            raw_signal_name,
            database_options_specific,
            source_options,
            plot_type=cst.PlotType.TIME_SERIES,
        )
        metadata = Metadata(
            period_resampling=p,
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
        )
        timing["signal_initialization"] = time.perf_counter() - start
        # ---- Total --------------------------------------------------------------
        timing["total_time_series_from_dataframe"] = time.perf_counter() - start_total
        obj.timing = timing
        logger.debug(
            "⏳ %ss for signal '%s'. timing details: %s",
            f"{timing['total_time_series_from_dataframe']:.4f}",
            raw_signal_name,
            {k: f"{v:.4f}s" for k, v in timing.items()},
        )
        return obj

    @classmethod
    def loop_from_signals(
        cls, signal_x: "Signal", signal_y: "Signal", name: str | None = None
    ) -> "Signal":
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
            plot_height=600,
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
        )
        timing["signal_initialization"] = time.perf_counter() - start
        timing["total_loop_from_signals"] = time.perf_counter() - start_total
        obj.timing = timing
        logger.debug(
            "⏳ %ss for loop signal '%s' timing details: %s",
            f"{timing['total_loop_from_signals']:.4f}",
            obj.raw_name,
            {k: f"{v:.4f}s" for k, v in timing.items()},
        )
        return obj

    # ---------------- Regular Methods ----------------
    def to_plotly_trace(self) -> go.Scatter:
        start = time.perf_counter()
        if self.trace is not None:
            logger.warning("Trace of %s will be overwritten", self.name)
        # Convert timezone-naive numpy datetime to the desired timezone
        if self.data.timezone is not None:
            self.data.x, self.data.timezone = helper.change_ndarray_timezone(
                self.data.x, self.data.timezone, cst.DISPLAY_TIMEZONE
            )

        x = self.data.x
        # Prepare line dict only if mode includes lines
        line_dict = (
            {
                "color": self.trace_options.line_color,
                "width": self.trace_options.line_width,
                "dash": self.trace_options.line_dash,
            }
            if "lines" in self.trace_options.mode
            else None
        )
        # Prepare marker dict only if mode includes markers
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
            f" {y_unit_name}" if y_unit_name != cst.DatabaseOptions.Signal.DEFAULT_UNIT else ""
        )

        # Magic keyword in hover_template → pre-compute customdata strings
        _template = self.trace_options.hover_template
        _is_keyword = hover_formatters.is_keyword(_template)
        customdata = (
            hover_formatters.compute_customdata(self.data.y, _template) if _is_keyword else None
        )
        _y_fmt = "%{customdata}" if _is_keyword else "%{y:.4g}"

        if _template is not None and not _is_keyword:
            hovertemplate = _template
        elif self.trace_options.plot_options.plot_type == cst.PlotType.TIME_SERIES:
            # Compact single-line template: time is shown once in the "x unified"
            # header, so each trace only needs name + value.
            hovertemplate = f"<b>{self.name}</b>: {_y_fmt}{y_unit_suffix}<extra></extra>"
        elif self.trace_options.plot_options.plot_type == cst.PlotType.LOOP:
            x_unit_name = self.trace_options.plot_options.x_unit_name
            _x_unit_suffix = (
                f" {x_unit_name}" if x_unit_name != cst.DatabaseOptions.Signal.DEFAULT_UNIT else ""
            )
            # Keyword formatters (fraction, percentage, …) only cover one axis,
            # so they are intentionally ignored for loops to avoid asymmetric display.
            if self.data.loop_time_axis is not None and len(self.data.loop_time_axis) > 0:
                customdata = helper.loop_time_to_display_strings(self.data.loop_time_axis)
                _tz_abbr = (
                    pd.to_datetime(self.data.loop_time_axis[0], unit="s", utc=True)
                    .tz_convert(cst.DISPLAY_TIMEZONE)
                    .tzname()
                )
                hovertemplate = (
                    f"<b>{self.name}</b><br>"
                    f"%{{x:.4g}}{_x_unit_suffix} | %{{y:.4g}}{y_unit_suffix}<br>"
                    f"%{{customdata}} ({_tz_abbr})<br>"
                    "<extra></extra>"
                )
            else:
                hovertemplate = (
                    f"<b>{self.name}</b><br>"
                    f"%{{x:.4g}}{_x_unit_suffix} | %{{y:.4g}}{y_unit_suffix}<br>"
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
        """Initialize Signal by creating its Plotly trace."""
        self.trace = self.to_plotly_trace()


@dataclass
class PlotGroup:
    name: str
    signals: list[Signal]
    plot_options: PlotOptions = field(init=False)
    allow_secondary_y: bool = True
    timing: dict = field(default_factory=dict)  # Add timing dictionary

    @classmethod
    def from_single_signal(cls, sig: Signal) -> "PlotGroup":
        start = time.perf_counter()
        plot_group = cls(name=sig.name, signals=[sig], allow_secondary_y=False)
        elapsed = time.perf_counter() - start
        plot_group.timing["from_single_signal"] = elapsed
        return plot_group

    def __post_init__(self) -> None:
        """Initialize PlotGroup with plot options."""
        start = time.perf_counter()
        # Derive group-level plot options
        if isinstance(self.signals, Signal):
            self.signals = [self.signals]
        if len(self.signals) == 1:
            # Single signal → copy its plot options
            self.plot_options = self.signals[0].trace_options.plot_options
        else:
            # Multiple signals → combine their plot options
            self.plot_options = PlotOptions.combine_from_signals(self.signals, self.name)
            self.plot_options.show_legend = True
        elapsed = time.perf_counter() - start
        self.timing["__post_init__"] = elapsed

    def assign_axes(self) -> list[tuple[go.Scatter, bool]]:
        traces_with_axes = []
        # Assign traces to axes
        for sig in self.signals:
            secondary_y = (
                sig.trace_options.plot_options.y_unit_name == self.plot_options.y2_unit_name
            )
            trace = sig.trace
            trace.showlegend = self.plot_options.show_legend
            traces_with_axes.append((sig.trace, secondary_y))
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

    def to_figure(self, min_spacing: float = 0.005) -> go.Figure:
        start = time.perf_counter()
        n_groups = len(self.groups)
        is_loop = self.plot_type == cst.PlotType.LOOP

        # Loop plots with multiple subplots use a multi-column grid so square subplots
        # sit side-by-side instead of stacking vertically.
        if is_loop and n_groups > 1:
            n_cols = 2  # Flexible, TODO: remove the magic number
            n_rows = int(np.ceil(n_groups / n_cols))
            subplot_height = self.groups[0].plot_options.plot_height
            total_fig_height = n_rows * subplot_height
            row_heights = [1.0] * n_rows
            specs = [
                [
                    {"secondary_y": True} if r * n_cols + c < n_groups else None
                    for c in range(n_cols)
                ]
                for r in range(n_rows)
            ]
            subplot_titles = [g.name for g in self.groups]
            fig_width = n_cols * subplot_height
            extra_subplot_kwargs = {"horizontal_spacing": 0.05}
        else:
            n_cols = 1  # Fixed
            n_rows = n_groups
            total_fig_height = np.sum([g.plot_options.plot_height for g in self.groups])
            row_heights = [g.plot_options.plot_height / total_fig_height for g in self.groups]
            specs = [[{"secondary_y": True}] for _ in range(n_rows)]
            subplot_titles = [g.name for g in self.groups]
            fig_width = total_fig_height / n_rows if self.square_plot else None
            extra_subplot_kwargs = {}

        self.computed_height = total_fig_height
        # Aim for ~30 px between subplots to leave room for subplot titles.
        # Falls back to min_spacing so very tall figures don't get absurdly large gaps.
        title_gap_px = 30.0
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

            # Shared x-axis only applies to time-series (loop subplots each have
            # an independent x-axis representing a different signal).
            if not is_loop:
                x_data_type = type(group.signals[0].data.x)
                if x_data_type in x_type_to_master_row:
                    master_row = x_type_to_master_row[x_data_type]
                    master_ref = "x" if master_row == 1 else f"x{master_row}"
                    fig.update_xaxes(matches=master_ref, row=plotly_row, col=plotly_col)
                else:
                    x_type_to_master_row[x_data_type] = plotly_row

            if self.plot_type == cst.PlotType.TIME_SERIES:
                fig.update_yaxes(modebardisable="zoominout", row=plotly_row)

        # Time-series figures use "x unified": one compact tooltip with a single time header
        # and one line per trace.  Format the x-axis header as HH:MM:SS (milliseconds would
        # clutter the header; they're available per trace via a custom hover_template if needed).
        # Loop figures keep Plotly's default ("closest"): each point is independent.
        if self.plot_type == cst.PlotType.TIME_SERIES:
            fig.update_xaxes(hoverformat="%H:%M:%S.%3f")
            fig.update_layout(hovermode="x unified")

        fig.update_layout(
            title_text=self.name,
            height=total_fig_height,
            width=fig_width,
            showlegend=True,
            hoverlabel={"namelength": -1},
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
        """
        Initialize PlotModel object.

        Validates plot_type and square_plot consistency,
        sorts groups by plot_priority, and builds the figure.
        """
        plot_group = self.groups

        plot_type = get_unique_or_raise(
            [group.plot_options.plot_type for group in plot_group],
            "plot_options.plot_type",
            context="PlotGroups",
        )
        square_plot = get_unique_or_raise(
            [group.plot_options.square_plot for group in plot_group],
            "square_plot",
            context="PlotGroups",
        )

        self.name = plot_type
        self.plot_type = plot_type
        self.square_plot = square_plot

        # Sort groups by plot_priority
        self.groups = sorted(plot_group, key=lambda group: group.plot_options.plot_priority)

        # Build the figure
        self.figure = self.to_figure()

    @staticmethod
    def assign_plot_model(plot_group_list: list[PlotGroup]) -> list["PlotModel"]:
        """Assign plot groups to plot models by plot type."""
        groups = {}
        for plot_group in plot_group_list:
            plot_type = plot_group.plot_options.plot_type
            if plot_type not in groups:
                groups[plot_type] = [plot_group]
            else:
                groups[plot_type].append(plot_group)
        return [
            PlotModel(groups=common_plot_group_list) for common_plot_group_list in groups.values()
        ]

    @staticmethod
    def to_html(plot_models: list["PlotModel"], patient_options: dict[str, Any]) -> None:
        if not plot_models:
            logger.warning("⚠️ PlotModel figure generation to html was called with empty list")
        data_folder = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        output_path = data_folder / cst.FOLDER_NAME_VISU / cst.DEFAULT_NAME_VISUALIZATION
        fig_list = [plot_mod.figure for plot_mod in plot_models if plot_mod.figure is not None]
        start = time.perf_counter()
        helper.print_out_figure(output_path, fig_list)
        elapsed = time.perf_counter() - start
        logger.debug("⏳ %.4fs for PlotModel list to html visualization", elapsed)
