"""Top half of the ``loop`` plot type: interpolate two time-series onto one another."""

import logging
import time
from typing import Any

import numpy as np
import pandas as pd

import clinical_scope.constants as cst
from clinical_scope.datasource.formatting.timezone import loop_time_to_display_strings
from clinical_scope.plot_types.base import (
    PlotBuilder,
    PlotTypeArityError,
    RenderSpec,
    TimeSeries,
)
from clinical_scope.plot_types.loop.schema import LOOP_REFERENCE_COUNT, LoopSchema
from clinical_scope.signal_container import (
    Data,
    Metadata,
    PlotOptions,
    Signal,
    TraceOptions,
    get_unique_or_raise,
    signal_utc_float_seconds,
)
from clinical_scope.signal_reference import resolve_one

logger = logging.getLogger(__name__)


def _hover_spec(
    signal_name: str,
    plot_options: PlotOptions,
    loop_time_axis: np.ndarray,
    display_fallbacks: Any,
) -> RenderSpec:
    """
    Build the tooltip a loop point shows: both axes, then the instant it was recorded.

    Keyword formatters (fraction, percentage, ...) only cover one axis, so they are
    intentionally ignored for loops rather than displayed asymmetrically.
    """
    x_unit_name = plot_options.x_unit_name
    x_unit_suffix = (
        f" {x_unit_name}" if x_unit_name != cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT else ""
    )
    y_unit_name = plot_options.y_unit_name
    y_unit_suffix = (
        f" {y_unit_name}" if y_unit_name != cst.DatabaseOptions.SignalConfig.DEFAULT_UNIT else ""
    )
    x_format = display_fallbacks.value_format("x")
    y_format = display_fallbacks.value_format("y")
    axes_line = f"{x_format}{x_unit_suffix} | {y_format}{y_unit_suffix}"

    if loop_time_axis is None or len(loop_time_axis) == 0:
        return RenderSpec(hover_template=f"<b>{signal_name}</b><br>{axes_line}<br><extra></extra>")

    display_tz = plot_options.display_timezone
    timestamps = loop_time_to_display_strings(loop_time_axis, display_timezone=display_tz)
    tz_abbreviation = (
        pd.to_datetime(loop_time_axis[0], unit="s", utc=True).tz_convert(display_tz).tzname()
    )
    return RenderSpec(
        hover_template=(
            f"<b>{signal_name}</b><br>"
            f"{axes_line}<br>"
            f"%{{customdata}} ({tz_abbreviation})<br>"
            "<extra></extra>"
        ),
        hover_customdata=timestamps,
    )


def loop_from_signals(signal_x: Signal, signal_y: Signal, name: str | None = None) -> Signal:
    """Build a loop signal from two time-series; display fallbacks come from *signal_x*."""
    start_total = time.perf_counter()
    timing = {}

    time_series = TimeSeries.NAME
    if (
        signal_x.trace_options.plot_options.plot_type != time_series
        or signal_y.trace_options.plot_options.plot_type != time_series
    ):
        msg = f"Both input signals must be of type '{time_series}'."
        raise ValueError(msg)

    x_x = signal_utc_float_seconds(signal_x)
    x_y = signal_utc_float_seconds(signal_y)

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
        plot_type=LoopSchema.NAME,
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
    display_name = name or f"{signal_x.name} vs {signal_y.name}"
    obj = Signal(
        raw_name=name or f"{signal_x.raw_name}_vs_{signal_y.raw_name}",
        name=display_name,
        data=data,
        trace_options=trace_options,
        metadata=Metadata(),
        display_fallbacks=signal_x.display_fallbacks,
        render=_hover_spec(display_name, plot_options, x_common, signal_x.display_fallbacks),
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


def build(all_signals: list[Signal], loop_name: str, loop_field_list: list[str]) -> Signal:
    """Build the loop one ``loop`` config entry describes."""
    if len(loop_field_list) != LOOP_REFERENCE_COUNT:
        msg = f"needs exactly {LOOP_REFERENCE_COUNT} signal references, got {len(loop_field_list)}"
        raise PlotTypeArityError(msg)
    signal_x, signal_y = (resolve_one(reference, all_signals) for reference in loop_field_list)
    return loop_from_signals(signal_x, signal_y, name=loop_name)


BUILDER = PlotBuilder(build=build, refusals=(PlotTypeArityError,))
