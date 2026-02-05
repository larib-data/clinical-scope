import logging
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer import helper

logger = logging.getLogger(__name__)


def get_unique_or_raise(values: list, attribute_name: str, context: str = ""):
    """
    Ensure all values are identical in a list.
    Raise ValueError if not.
    Returns the unique value (or None if list empty).
    """
    unique_values = list(set(values))
    if len(unique_values) > 1:
        raise ValueError(
            f"We can't combine {context} with different '{attribute_name}' attributes. "
            f"Given: {unique_values}"
        )
    return unique_values[0] if unique_values else None


def compute_average_priority(items: list):
    """Compute average plot_priority, defaulting missing to 10000."""
    return float(np.mean([getattr(item, "plot_priority", 10000) or 10000 for item in items]))


def merge_y_ranges(signals: list["Signal"], unit_name: str):
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
    timezone: str | None = None  # New attribute to store timezone information


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

    def __post_init__(self):
        if self.y_unit_name is None:
            self.y_unit_name = (
                cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO
            )  # authorizing None here produce terrible results later
        if self.plot_type is None:
            logger.warning("PlotOptions.plot_type should not be initialized to None")
        if self.plot_priority is None:
            self.plot_priority = 10000  # By default, after everything else

    @staticmethod
    def combine_from_signals(signals: list["Signal"], group_name: str) -> "PlotOptions":
        """
        Combine the plot options from a list of signals.
        """
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

        if len(y_unit_list) > 2:
            logger.warning(
                "⚠️ Signals %s can't be plotted on one plot: more than 2 units: %s",
                [sig.name for sig in signals],
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
    plot_options: PlotOptions = field(default_factory=PlotOptions)

    def __post_init__(self):
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
    device_name: str | None = None
    is_derived: bool = False
    parent_signal_name: str | None = None
    period_resampling: float | None = None
    time_shift_second: float | None = None


@dataclass
class Quality:
    is_valid: bool = True
    quality_score: float = 1.0


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
    def _build_trace_options(raw_signal_name, database_options_specific, source_options, plot_type):
        data_opts = database_options_specific.get(cst.DatabaseOptions.DATA, {})
        data_numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})
        # PlotOptions fields
        plot_options_dict = source_options.get("plot_options", {})
        valid_keys_plot_options = {f.name for f in fields(PlotOptions)}
        additional_plot_options = {
            k: v for k, v in plot_options_dict.items() if k in valid_keys_plot_options
        }
        name_signal = data_opts.get(cst.DatabaseOptions.Data.LABEL_CORRESPONDENCE, {}).get(
            raw_signal_name
        )
        range_signal_plot = data_opts.get(cst.DatabaseOptions.Data.UNIT_RANGE, {}).get(
            raw_signal_name
        )
        y_unit_name = data_opts.get(cst.DatabaseOptions.Data.UNIT_INFO, {}).get(
            raw_signal_name, cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO
        )
        y_axis_title_raw = f"{name_signal} ({y_unit_name or ''})"
        y_axis_title = helper.wrap_label(y_axis_title_raw, max_line_length=12)
        # TraceOptions fields
        trace_options_dict = source_options.get(cst.SourceOptions.TRACE_OPTIONS, {})
        valid_keys_trace_options = {f.name for f in fields(TraceOptions)}
        additional_trace_options = {
            k: v for k, v in trace_options_dict.items() if k in valid_keys_trace_options
        }
        color = data_opts.get(cst.DatabaseOptions.Data.COLOR, {}).get(raw_signal_name)
        plot_priority_default_db = data_numerics.get(cst.DatabaseOptions.Numerics.PRIORITY)
        plot_priority = data_opts.get(cst.DatabaseOptions.Data.PRIORITY, {}).get(
            raw_signal_name, plot_priority_default_db
        )
        plot_options = PlotOptions(
            y_axis_range=range_signal_plot,
            y_axis_title=y_axis_title,
            y_unit_name=y_unit_name,
            plot_type=plot_type,
            plot_priority=plot_priority,
            # Any ohter field
            **additional_plot_options,
        )
        trace_options = TraceOptions(
            plot_options=plot_options,
            line_color=color,
            marker_color=color,
            # Any ohter field
            **additional_trace_options,
        )
        return trace_options

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
        data_opts = database_options_specific.get(cst.DatabaseOptions.DATA, {})
        numerics = database_options_specific.get(cst.DatabaseOptions.NUMERICS, {})
        name_signal = data_opts.get(cst.DatabaseOptions.Data.LABEL_CORRESPONDENCE, {}).get(
            raw_signal_name
        )
        unit_conversion_factor = data_opts.get(cst.DatabaseOptions.Data.UNIT_CONVERSION, {}).get(
            raw_signal_name, cst.DatabaseOptions.DEFAULT_UNIT_FACTOR
        )
        p_global = numerics.get(
            cst.DatabaseOptions.Numerics.PERIOD_RESAMPLING,
            cst.DatabaseOptions.DEFAULT_PERIOD_RESAMPLING,
        )
        p = data_opts.get(cst.DatabaseOptions.Data.PERIOD_RESAMPLING, {}).get(
            raw_signal_name, p_global
        )
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
            raise ValueError("Both input signals must be of type 'time_series'.")

        x_x = helper.to_float_seconds(signal_x.data.x)
        x_y = helper.to_float_seconds(signal_y.data.x)

        t_min = max(x_x[0], x_y[0])
        t_max = min(x_x[-1], x_y[-1])

        if t_min >= t_max:
            raise ValueError("Signals do not have overlapping time intervals.")

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
        data = Data(x=y_x, y=y_y, timezone=None)
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
    def to_plotly_trace(self):
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
            dict(
                color=self.trace_options.line_color,
                width=self.trace_options.line_width,
                dash=self.trace_options.line_dash,
            )
            if "lines" in self.trace_options.mode
            else None
        )
        # Prepare marker dict only if mode includes markers
        marker_dict = (
            dict(
                color=self.trace_options.marker_color,
                symbol=self.trace_options.marker_symbol,
                size=self.trace_options.marker_size,
            )
            if "markers" in self.trace_options.mode
            else None
        )
        y_unit_name = self.trace_options.plot_options.y_unit_name
        if self.trace_options.plot_options.plot_type == cst.PlotType.TIME_SERIES:
            hovertemplate = (
                f"<b>{self.name}</b><br>"
                + "%{x|%H:%M:%S.%f} | %{y}"
                + f" {
                    y_unit_name if y_unit_name != cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO else ''
                }<br>"
                + "<extra></extra>"
            )
        elif self.trace_options.plot_options.plot_type == cst.PlotType.LOOP:
            x_unit_name = self.trace_options.plot_options.x_unit_name
            hovertemplate = (
                f"<b>{self.name}</b><br>"
                + "%{x}"
                + f" {
                    x_unit_name if x_unit_name != cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO else ''
                }"
                + " | %{y}"
                + f" {
                    y_unit_name if y_unit_name != cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO else ''
                }<br>"
                + "<extra></extra>"
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
            hovertemplate=hovertemplate,
        )
        elapsed = time.perf_counter() - start
        self.timing["to_plotly_trace"] = elapsed
        logger.debug("⏳ %.4fs for to_plotly_trace for signal '%s'", elapsed, self.name)
        return trace

    def __post_init__(self):
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

    def __post_init__(self):
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
    timing: dict = field(default_factory=dict)  # Add timing dictionary

    def to_figure(self, base_spacing=0.05, min_spacing=0.005) -> go.Figure:
        start = time.perf_counter()
        n_rows = len(self.groups)
        total_fig_height = np.sum(
            [plot_group.plot_options.plot_height for plot_group in self.groups]
        )
        proportions = [
            plot_group.plot_options.plot_height / total_fig_height for plot_group in self.groups
        ]
        subplot_title = (
            [plot_group.name for plot_group in self.groups]
            if self.plot_type != cst.PlotType.TIME_SERIES
            else None
        )
        vertical_spacing = max(min_spacing, base_spacing / n_rows)

        fig = make_subplots(
            rows=n_rows,
            cols=1,
            shared_xaxes=False,
            vertical_spacing=vertical_spacing,
            specs=[[{"secondary_y": True}] for _ in range(n_rows)],
            row_heights=proportions,
            subplot_titles=subplot_title,
        )
        # Map x-data type → master row for automatic shared x-axis
        x_type_to_master_row = {}
        for row_idx, group in enumerate(self.groups, start=1):
            traces_with_axes = group.assign_axes()  # Use the new method
            for trace, secondary_y in traces_with_axes:
                fig.add_trace(trace, row=row_idx, col=1, secondary_y=secondary_y)
            # Update y-axis titles from plot_options
            y_title = group.plot_options.y_axis_title or ""
            fig.update_yaxes(
                title_text=y_title,
                row=row_idx,
                col=1,
                range=group.plot_options.y_axis_range,
                secondary_y=False,
            )
            # Add secondary y-axis title if exists
            if group.allow_secondary_y and len(group.assign_axes()) > 1:
                second_y_title = group.plot_options.y2_axis_title or ""
                fig.update_yaxes(
                    title_text=second_y_title,
                    row=row_idx,
                    col=1,
                    range=group.plot_options.y2_axis_range,
                    secondary_y=True,
                )
            # Update x-axis title
            x_title = group.plot_options.x_axis_title
            fig.update_xaxes(
                title_text=x_title,
                row=row_idx,
                col=1,
                range=group.plot_options.x_axis_range,
            )
            # --- Automatic shared x-axis based on x-data type ---
            x_data_type = type(group.signals[0].data.x)
            if x_data_type in x_type_to_master_row:
                master_row = x_type_to_master_row[x_data_type]
                fig.update_xaxes(matches=f"x{master_row}", row=row_idx, col=1)
            else:
                x_type_to_master_row[x_data_type] = row_idx
        fig.update_layout(
            title_text=self.name,
            height=total_fig_height,
            width=total_fig_height / n_rows if self.square_plot else None,
            showlegend=True,
            hoverlabel=dict(
                namelength=-1  # Show full curve name
            ),
        )
        elapsed = time.perf_counter() - start
        self.timing["to_figure"] = elapsed
        logger.debug(
            "⏳ %.4fs for figure generation from PlotModel with plot type %s",
            elapsed,
            self.plot_type,
        )
        return fig

    def __post_init__(self):
        """
        Initialize PlotGroup object:
        - Validate plot_type and square_plot consistency
        - Sort groups by plot_priority
        - Build figure
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
        self.square_plot = square_plot

        # Sort groups by plot_priority
        self.groups = sorted(plot_group, key=lambda group: group.plot_options.plot_priority)

        # Build the figure
        self.figure = self.to_figure()

    @staticmethod
    def assign_plot_model(plot_group_list: list[PlotGroup]) -> list["PlotModel"]:
        groups = {}
        for plot_group in plot_group_list:
            plot_type = plot_group.plot_options.plot_type
            if plot_type not in groups:
                groups[plot_type] = [plot_group]
            else:
                groups[plot_type].append(plot_group)
        plot_model_list = [
            PlotModel(groups=common_plot_group_list) for common_plot_group_list in groups.values()
        ]
        return plot_model_list

    @staticmethod
    def to_html(plot_models: list["PlotModel"], patient_options: dict) -> None:
        if not plot_models:
            logger.warning("⚠️ PlotModel figure generation to html was called with empty list")
        data_folder = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        output_path = data_folder / cst.FOLDER_NAME_VISU / cst.DEFAULT_NAME_VISUALIZATION
        fig_list = [plot_mod.figure for plot_mod in plot_models if plot_mod.figure is not None]
        start = time.perf_counter()
        helper.print_out_figure(output_path, fig_list)
        elapsed = time.perf_counter() - start
        logger.debug("⏳ %.4fs for PlotModel list to html visualization", elapsed)
