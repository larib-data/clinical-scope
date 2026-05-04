"""
Loop-related callbacks for Dash API visualization.

Contains callbacks for filtering loop plots by time range via a slider.
"""

import logging

from dash import MATCH, Input, Output, Patch, State, callback, no_update

from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    LOOP_DATA_CACHE,
    format_time_range,
)
from clinical_data_visualizer.io.timezone import loop_time_to_display_strings

logger = logging.getLogger(__name__)


@callback(
    Output({"type": "graph", "name": MATCH}, "figure", allow_duplicate=True),
    Input({"type": "loop-time-slider", "name": MATCH}, "value"),
    State({"type": "loop-store", "name": MATCH}, "data"),
    prevent_initial_call=True,
)
def filter_loop_by_time(
    slider_value: list[float],
    loop_uid: str | None,
) -> Patch:
    """
    Filter loop plot traces to the selected time window.

    Slider values are seconds offset from t_min (relative). This function
    converts them to absolute epoch seconds before masking.
    """
    if not slider_value or not loop_uid:
        return no_update

    cache = LOOP_DATA_CACHE.get(loop_uid)
    if cache is None:
        logger.warning("Loop cache miss for uid=%s", loop_uid)
        return no_update

    t_min = cache["t_min"]
    t_start = t_min + slider_value[0]
    t_end = t_min + slider_value[1]

    patch = Patch()
    for i, trace_data in enumerate(cache["traces"]):
        time_array = trace_data["time_axis"]
        if time_array is None:
            continue
        mask = (time_array >= t_start) & (time_array <= t_end)
        patch["data"][i]["x"] = trace_data["x"][mask].tolist()
        patch["data"][i]["y"] = trace_data["y"][mask].tolist()
        patch["data"][i]["customdata"] = loop_time_to_display_strings(time_array[mask]).tolist()

    return patch


@callback(
    Output({"type": "loop-time-display", "name": MATCH}, "children"),
    Input({"type": "loop-time-slider", "name": MATCH}, "value"),
    State({"type": "loop-store", "name": MATCH}, "data"),
    prevent_initial_call=True,
)
def update_time_display(slider_value: list[float], loop_uid: str | None) -> str:
    """Update the human-readable time range text below the slider."""
    if not slider_value or not loop_uid:
        return no_update

    cache = LOOP_DATA_CACHE.get(loop_uid)
    if cache is None:
        return no_update

    t_min = cache["t_min"]
    return format_time_range(t_min + slider_value[0], t_min + slider_value[1])
