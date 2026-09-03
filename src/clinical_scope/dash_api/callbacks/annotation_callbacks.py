"""
Annotation callbacks for the Dash application.

Implements the full annotation creation / rendering / persistence flow, from graph clicks
through the creation modals to annotations.json. Section banners below mark each stage.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from typing import Any

import pandas as pd
from dash import ALL, Input, Output, Patch, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

import clinical_scope.constants as cst
from clinical_scope import load_annotations
from clinical_scope.dash_api.annotations.io import save_annotations
from clinical_scope.dash_api.annotations.model import (
    ANNOTATION_COLORS,
    TIME_BASED_ANNOTATION_TYPES,
    Annotation,
    AnnotationSet,
    AnnotationType,
    Group,
    normalize_hex_color,
)
from clinical_scope.dash_api.annotations.renderer import (
    build_figure_overlays,
    normalize_annotation_for_display,
)
from clinical_scope.dash_api.styles import (
    ANNOTATION_LIST_PANEL,
    ANNOTATION_LIST_PANEL_HIDDEN,
    ANNOTATION_LIST_ROW,
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_MODAL_STYLE_SHOWN,
    ANNOTATION_TOOLBAR_STYLE,
    BUTTON_ANNOTATION_ACTIVE,
    BUTTON_ANNOTATION_INACTIVE,
    BUTTON_ANNOTATION_ROW,
    BUTTON_ANNOTATION_SAVE,
    BUTTON_ANNOTATION_SMALL,
    BUTTON_DISABLED_OVERLAY,
    BUTTON_MODAL_CLOSE,
    COLOR_PREVIEW_SWATCH,
)
from clinical_scope.datasource.formatting.timezone import to_naive_display_ts
from clinical_scope.plot_types import registry as plot_types
from clinical_scope.signal_container import DisplayFallbacks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TYPE_LABELS = {
    AnnotationType.TIME_EVENT.value: "Time Event",
    AnnotationType.TIME_WINDOW.value: "Time Window",
    AnnotationType.POINT.value: "Point",
}

_TYPE_ICONS = {
    AnnotationType.TIME_EVENT.value: "│",
    AnnotationType.TIME_WINDOW.value: "▭",
    AnnotationType.POINT.value: "•",
}


def default_mode() -> dict:
    """
    Return a fresh annotation-mode-store value.

    This dict is the annotation state machine: ``active`` gates click handling, the
    ``pending_*`` pair holds a time-window's first click, the ``group_*`` fields — set only
    in group mode — make clicks bypass the creation modal, and ``moving_id`` names the
    annotation the next click re-places.

    One mode at a time: group and move are never both armed, so every writer of this store
    clears the fields of the mode it is not entering.
    """
    return {
        "active": False,
        "type": AnnotationType.TIME_EVENT.value,
        "pending_x0": None,
        "pending_plot_name": None,
        "group_id": None,
        "group_name": None,
        "group_color": None,
        "group_is_global": False,
        "moving_id": None,
    }


def _build_annotation_data(
    annotation_type: AnnotationType,
    *,
    x: str | None = None,
    x0: str | None = None,
    x1: str | None = None,
    xaxis: str = "x",
    y: float | None = None,
    yaxis: str = "y",
    point_time: str | None = None,
) -> dict:
    """Build an annotation's type-specific ``data`` payload from an already-resolved click."""
    if annotation_type == AnnotationType.TIME_WINDOW:
        return {"x0": x0, "x1": x1, "xaxis": xaxis}
    if annotation_type == AnnotationType.POINT:
        data: dict[str, Any] = {"x": x, "y": y, "xaxis": xaxis, "yaxis": yaxis}
        if point_time:
            data["t"] = point_time
        return data
    return {"x": x, "xaxis": xaxis}


def _point_time(point: dict, *, timestamped: bool, display_tz: str) -> str | None:
    """
    Return when a clicked point was recorded, read off the trace's customdata.

    Only loop-style plots carry it; on a time-axis plot the x value already is that instant.
    """
    if not timestamped:
        return None
    raw_t = point.get("customdata")
    if not raw_t:
        return None
    with contextlib.suppress(Exception):
        return pd.Timestamp(str(raw_t)).tz_localize(display_tz).isoformat()
    return None


def _localize_x_val(x_val: str, display_tz: str = cst.DISPLAY_TIMEZONE) -> str:
    """Return x_val as an ISO string with timezone offset; pass-through for non-datetime values."""
    try:
        ts = pd.Timestamp(x_val)
        if pd.isna(ts):
            return x_val
        if ts.tzinfo is None:
            ts = ts.tz_localize(display_tz)
        return ts.isoformat()
    except Exception:
        logger.warning("Could not localize x value %r", x_val, exc_info=True)
        return x_val


def _parse_yaxis_idx(yaxis_ref: str) -> int:
    """Parse Plotly axis ref to 1-based index: 'y' → 1, 'y2' → 2, etc."""
    num_str = yaxis_ref[1:] if yaxis_ref.startswith("y") else ""
    return int(num_str) if num_str else 1


def _fmt_ts(ts_str: str, display_tz: str | None) -> str:
    """Format a stored tz-aware timestamp as a human-readable display-TZ string."""
    naive = to_naive_display_ts(ts_str, display_tz)
    return naive.replace("T", " ")


def _format_position(modal_data: dict) -> str:
    display_tz = modal_data.get("display_timezone")
    annotation_type = modal_data.get("type", "")
    if annotation_type == AnnotationType.TIME_EVENT.value:
        return f"At: {_fmt_ts(modal_data.get('x', ''), display_tz)}"
    if annotation_type == AnnotationType.TIME_WINDOW.value:
        x0 = _fmt_ts(modal_data.get("x0", ""), display_tz)
        x1 = _fmt_ts(modal_data.get("x1", ""), display_tz)
        return f"From: {x0}  →  {x1}"
    if annotation_type == AnnotationType.POINT.value:
        x = _fmt_ts(modal_data.get("x", ""), display_tz)
        y = modal_data.get("y")
        t = modal_data.get("t")
        if y is None:
            pos = f"At: x={x}"
        else:
            pos = f"At: x={x}  y={y:.4g}" if isinstance(y, float) else f"At: x={x}  y={y}"
        if t:
            pos += f"  t={_fmt_ts(t, display_tz)}"
        return pos
    return ""


def _format_x_short(x_val: str | None, display_tz: str | None = None) -> str:
    """Format an x value for compact display in the annotation list."""
    if not x_val:
        return ""
    with contextlib.suppress(Exception):
        ts = pd.Timestamp(x_val)
        if not pd.isna(ts):
            if ts.tzinfo is not None and display_tz:
                ts = ts.tz_convert(display_tz)
            return ts.strftime("%H:%M:%S")
    with contextlib.suppress(Exception):
        numeric_value = float(x_val)
        return f"{numeric_value:.4g}"
    return str(x_val)


def _annotation_list_row(
    annotation: Annotation, group_name: str | None = None, display_tz: str | None = None
) -> html.Div:
    type_label = _TYPE_LABELS.get(annotation.type.value, annotation.type.value)
    icon = _TYPE_ICONS.get(annotation.type.value, "?")
    display_label = annotation.label or (group_name or f"({type_label})")

    x_val = annotation.data.get("x") or annotation.data.get("x0")
    time_str = _format_x_short(x_val, display_tz)
    trace_str = (annotation.trace_metadata or {}).get("display_name", "")
    scope_str = annotation.subplot_name or "Global"
    info_parts = [part for part in [time_str, trace_str, scope_str] if part]
    info_line = " · ".join(info_parts)

    # Hiding dominates: while it is on, the label toggle can have no visible effect and a
    # move could not be verified, so both are disabled rather than left to act invisibly.
    label_text = "L:off" if annotation.label_hidden else "L:on"
    label_style = {
        **BUTTON_ANNOTATION_ROW,
        "backgroundColor": "#6c757d" if annotation.label_hidden else "#adb5bd",
        **(BUTTON_DISABLED_OVERLAY if annotation.hidden else {}),
    }
    visible_text = "V:off" if annotation.hidden else "V:on"
    visible_style = {
        **BUTTON_ANNOTATION_ROW,
        "backgroundColor": "#6c757d" if annotation.hidden else "#adb5bd",
    }

    return html.Div(
        [
            html.Span(
                icon,
                style={
                    "color": annotation.color,
                    "fontSize": "16px",
                    "fontWeight": "bold",
                    "minWidth": "16px",
                    "textAlign": "center",
                    "alignSelf": "flex-start",
                    "paddingTop": "2px",
                },
            ),
            html.Div(
                [
                    html.Span(
                        display_label,
                        style={"overflow": "hidden", "textOverflow": "ellipsis"},
                    ),
                    html.Span(
                        info_line,
                        style={"fontSize": "11px", "color": "#999", "marginTop": "2px"},
                    ),
                ],
                style={"display": "flex", "flexDirection": "column", "flex": 1, "minWidth": 0},
            ),
            html.Button(
                label_text,
                id={"type": "annotation-label-toggle-btn", "id": annotation.id},
                n_clicks=0,
                disabled=annotation.hidden,
                title="Show or hide this annotation's text label",
                style=label_style,
            ),
            html.Button(
                visible_text,
                id={"type": "annotation-hidden-toggle-btn", "id": annotation.id},
                n_clicks=0,
                title="Show or hide this annotation entirely",
                style=visible_style,
            ),
            html.Button(
                "Move",
                id={"type": "annotation-move-btn", "id": annotation.id},
                n_clicks=0,
                disabled=annotation.hidden,
                title="Click here, then click the new position on the plot",
                style={
                    **BUTTON_ANNOTATION_ROW,
                    **(BUTTON_DISABLED_OVERLAY if annotation.hidden else {}),
                },
            ),
            html.Button(
                "×",  # noqa: RUF001
                id={"type": "annotation-delete-btn", "id": annotation.id},
                n_clicks=0,
                style={
                    **BUTTON_MODAL_CLOSE,
                    "padding": "1px 7px",
                    "fontSize": "14px",
                    "lineHeight": "1.2",
                    "backgroundColor": "#dc3545",
                    "flexShrink": 0,
                },
            ),
        ],
        style=ANNOTATION_LIST_ROW,
    )


# ---------------------------------------------------------------------------
# 1. Annotation mode toggle / deactivate
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-type-btn-time_event", "style"),
    Output("annotation-type-btn-time_window", "style"),
    Output("annotation-type-btn-point", "style"),
    Output("annotation-mode-deactivate", "style"),
    Output("annotation-active-group-display", "children", allow_duplicate=True),
    Input("annotation-type-btn-time_event", "n_clicks"),
    Input("annotation-type-btn-time_window", "n_clicks"),
    Input("annotation-type-btn-point", "n_clicks"),
    Input("annotation-mode-deactivate", "n_clicks"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def toggle_annotation_mode(
    _te: int,
    _tw: int,
    _pt: int,
    _deactivate: int,
    mode: dict,
) -> tuple[dict, dict, dict, dict, dict, str]:
    """Activate an annotation type or deactivate mode entirely."""
    mode = mode or default_mode()
    triggered = ctx.triggered_id

    if triggered == "annotation-mode-deactivate":
        new_mode = {
            **mode,
            "active": False,
            "pending_x0": None,
            "pending_plot_name": None,
            "group_id": None,
            "moving_id": None,
        }
    else:
        btn_to_type = {
            "annotation-type-btn-time_event": AnnotationType.TIME_EVENT.value,
            "annotation-type-btn-time_window": AnnotationType.TIME_WINDOW.value,
            "annotation-type-btn-point": AnnotationType.POINT.value,
        }
        annotation_type = btn_to_type.get(
            triggered, mode.get("type", AnnotationType.TIME_EVENT.value)
        )
        if mode.get("active") and mode.get("type") == annotation_type and not mode.get("group_id"):
            new_mode = {
                **mode,
                "active": False,
                "pending_x0": None,
                "pending_plot_name": None,
                "group_id": None,
                "moving_id": None,
            }
        else:
            new_mode = {
                **mode,
                "active": True,
                "type": annotation_type,
                "group_id": None,
                "moving_id": None,
            }

    active = new_mode["active"]
    active_type = new_mode["type"]

    def _btn_style(annotation_type_value: str) -> dict:
        if active and active_type == annotation_type_value and not new_mode.get("group_id"):
            return BUTTON_ANNOTATION_ACTIVE
        return BUTTON_ANNOTATION_INACTIVE

    deactivate_style = {
        **BUTTON_ANNOTATION_INACTIVE,
        "display": "inline-block" if active else "none",
    }

    return (
        new_mode,
        _btn_style(AnnotationType.TIME_EVENT.value),
        _btn_style(AnnotationType.TIME_WINDOW.value),
        _btn_style(AnnotationType.POINT.value),
        deactivate_style,
        "",  # clear group display text
    )


# ---------------------------------------------------------------------------
# Internal helper: time-window pending state machine
# ---------------------------------------------------------------------------


def _check_pending_x0(mode: dict, x_str: str, plot_name: str) -> tuple[bool, str | None, dict]:
    """
    Handle the first/second click for a TIME_WINDOW annotation.

    Returns ``(is_first_click, stored_x0, new_mode)``.
    First click  → new_mode stores x_str; stored_x0 is None.
    Second click → new_mode clears pending; stored_x0 holds the first-click value.
    """
    pending_x0 = mode.get("pending_x0")
    pending_plot = mode.get("pending_plot_name")
    if pending_x0 is None or pending_plot != plot_name:
        return True, None, {**mode, "pending_x0": x_str, "pending_plot_name": plot_name}
    return False, pending_x0, {**mode, "pending_x0": None, "pending_plot_name": None}


# ---------------------------------------------------------------------------
# 2. Graph click handler
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-modal-data", "data"),
    Output("annotation-modal", "style"),
    Output({"type": "graph", "name": ALL}, "figure", allow_duplicate=True),
    Output("annotation-warning-msg", "children"),
    Output("annotation-store", "data", allow_duplicate=True),
    Output("annotation-active-group-display", "children", allow_duplicate=True),
    Output("annotation-mode-deactivate", "style", allow_duplicate=True),
    Input({"type": "graph", "name": ALL}, "clickData"),
    State("annotation-mode-store", "data"),
    State({"type": "graph-subplots", "name": ALL}, "data"),
    State({"type": "graph-trace-map", "name": ALL}, "data"),
    State({"type": "graph", "name": ALL}, "id"),
    State("annotation-store", "data"),
    State("display-timezone-store", "data"),
    prevent_initial_call=True,
)
def handle_graph_click(
    click_data_list: list,
    mode: dict,
    subplots_list: list,
    trace_map_list: list,
    graph_ids: list,
    annotations_raw: list,
    display_timezone: str | None,
) -> tuple[dict, dict, dict, list, str, list, str, dict]:
    """React to a graph click when annotation mode is active."""
    mode = mode or default_mode()
    if not mode.get("active"):
        raise PreventUpdate

    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate

    plot_name = triggered_id["name"]
    graph_names = [graph_id["name"] for graph_id in graph_ids]
    try:
        graph_idx = graph_names.index(plot_name)
    except ValueError as exc:
        raise PreventUpdate from exc

    click_data = click_data_list[graph_idx]
    if not click_data or not click_data.get("points"):
        raise PreventUpdate

    point = click_data["points"][0]
    x_val = point.get("x")
    y_val = point.get("y")
    curve_num = point.get("curveNumber", 0)

    trace_map = trace_map_list[graph_idx] or {}
    trace_info = trace_map.get(f"curve_{curve_num}", {"xaxis": "x", "yaxis": "y"})
    xaxis_ref = trace_info.get("xaxis", "x")
    yaxis_ref = trace_info.get("yaxis", "y")
    trace_metadata = {
        key: value
        for key, value in {
            "datasource_name": trace_info.get("datasource_name"),
            "raw_name": trace_info.get("raw_name"),
            "display_name": trace_info.get("display_name"),
        }.items()
        if value
    }

    subplots_data = subplots_list[graph_idx] or {}
    display_tz = display_timezone or cst.DISPLAY_TIMEZONE
    n_cols = subplots_data.get("n_cols", 1)
    subplot_rows = subplots_data.get("rows", [])

    annotation_type = mode.get("type", AnnotationType.TIME_EVENT.value)
    no_update_patches = [no_update] * len(graph_ids)

    plot_type = subplots_data.get("plot_type")
    # The store holds JSON, so the definition could not be carried across — this is the one place
    # a name is converted back. A plot type can have a non-time x-axis and still know when each
    # point was recorded, so the two capabilities are asked separately.
    definition = plot_types.definition_for(plot_type)
    point_is_timestamped = definition.POINT_TIMESTAMPS
    has_time_axis = definition.TIME_AXIS
    if not has_time_axis and annotation_type in TIME_BASED_ANNOTATION_TYPES:
        logger.warning(
            "User attempted to create %s annotation on a '%s' plot. Its x-axis is not time, "
            "so only Point annotations are valid.",
            annotation_type,
            plot_type,
        )
        return (
            mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            f"⚠ Time-based annotations are not supported on {plot_type} plots — switch to Point.",
            no_update,
            no_update,
            no_update,
        )

    x_str = _localize_x_val(str(x_val), display_tz) if has_time_axis else str(x_val)
    click_point_time = _point_time(point, timestamped=point_is_timestamped, display_tz=display_tz)

    # Built in data_callbacks.py, so it reflects the real layout (sparse grids, secondary
    # y-axes). Used for the subplot NAME only — row/col still come from the grid formula.
    yaxis_to_subplot = subplots_data.get("yaxis_to_subplot", {})
    subplot_info = yaxis_to_subplot.get(yaxis_ref)

    subplot_name = subplot_info["name"] if subplot_info else None

    axis_idx = _parse_yaxis_idx(yaxis_ref)
    auto_subplot_row = (axis_idx - 1) // n_cols + 1
    auto_col = (axis_idx - 1) % n_cols + 1

    if subplot_name is None:
        row_obj = next(
            (
                row_entry
                for row_entry in subplot_rows
                if row_entry["row"] == auto_subplot_row and row_entry["col"] == auto_col
            ),
            None,
        )
        # Fallback: row-only match covers secondary y-axes and single-column layouts
        if row_obj is None and subplot_rows:
            row_obj = next(
                (row_entry for row_entry in subplot_rows if row_entry["row"] == auto_subplot_row),
                None,
            )
        if row_obj is None and subplot_rows:
            logger.debug(
                "subplot lookup: no match (axis_idx=%d n_cols=%d row=%d col=%d) available=%s",
                axis_idx,
                n_cols,
                auto_subplot_row,
                auto_col,
                [
                    (row_entry["row"], row_entry["col"], row_entry["name"])
                    for row_entry in subplot_rows
                ],
            )
        subplot_name = row_obj["name"] if row_obj else None

    # --- Move mode: re-place an existing annotation, keeping everything but its position ---
    moving_id = mode.get("moving_id")
    if moving_id:
        annotation_set = AnnotationSet.from_dicts(annotations_raw)
        target = next(
            (annotation for annotation in annotation_set if annotation.id == moving_id), None
        )
        settled_mode = {
            **mode,
            "active": False,
            "moving_id": None,
            "pending_x0": None,
            "pending_plot_name": None,
        }
        toolbar_at_rest = {**BUTTON_ANNOTATION_INACTIVE, "display": "none"}

        if target is None:
            # Deleted mid-move, or a folder change reloaded the store. Disarm, change nothing.
            return (
                settled_mode,
                no_update,
                ANNOTATION_MODAL_STYLE_HIDDEN,
                no_update_patches,
                "",
                no_update,
                "",
                toolbar_at_rest,
            )

        if annotation_type == AnnotationType.TIME_WINDOW.value:
            is_first, stored_x0, pending_mode = _check_pending_x0(mode, x_str, plot_name)
            if is_first:
                # Still armed, and the preview line is drawn from the pending first click.
                return (
                    pending_mode,
                    no_update,
                    ANNOTATION_MODAL_STYLE_HIDDEN,
                    no_update_patches,
                    "",
                    no_update,
                    no_update,
                    no_update,
                )
            data = _build_annotation_data(
                AnnotationType.TIME_WINDOW, x0=stored_x0, x1=x_str, xaxis=xaxis_ref
            )
        else:
            data = _build_annotation_data(
                AnnotationType(annotation_type),
                x=x_str,
                xaxis=xaxis_ref,
                y=y_val,
                yaxis=yaxis_ref,
                point_time=click_point_time,
            )

        moved = annotation_set.with_moved(
            moving_id,
            data=data,
            plot_name=plot_name,
            subplot_name=subplot_name,
            trace_metadata=trace_metadata or None,
        )
        return (
            settled_mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            "",
            moved.to_dicts(),
            "",
            toolbar_at_rest,
        )

    # --- Group mode: bypass modal, create annotation immediately ---
    group_id = mode.get("group_id")
    if group_id:
        group_name = mode.get("group_name", "")
        group_color = mode.get("group_color", ANNOTATION_COLORS[0])
        group_is_global = mode.get("group_is_global", False)
        annotation_set = AnnotationSet.from_dicts(annotations_raw)

        if annotation_type == AnnotationType.TIME_WINDOW.value:
            is_first, stored_x0, new_mode = _check_pending_x0(mode, x_str, plot_name)
            if is_first:
                return (
                    new_mode,
                    no_update,
                    ANNOTATION_MODAL_STYLE_HIDDEN,
                    no_update_patches,
                    "",
                    no_update,
                    no_update,
                    no_update,
                )

            data = _build_annotation_data(
                AnnotationType.TIME_WINDOW, x0=stored_x0, x1=x_str, xaxis=xaxis_ref
            )
            annotation = Annotation.create(
                annotation_type=AnnotationType(annotation_type),
                plot_name=plot_name,
                label=group_name,
                color=group_color,
                is_global=group_is_global,
                subplot_name=subplot_name,
                group_id=group_id,
                group_name=group_name,
                data=data,
                trace_metadata=trace_metadata or None,
            )
            return (
                new_mode,
                no_update,
                ANNOTATION_MODAL_STYLE_HIDDEN,
                no_update_patches,
                "",
                annotation_set.with_added(annotation).to_dicts(),
                no_update,
                no_update,
            )

        data = _build_annotation_data(
            AnnotationType(annotation_type),
            x=x_str,
            xaxis=xaxis_ref,
            y=y_val,
            yaxis=yaxis_ref,
            point_time=click_point_time,
        )

        annotation = Annotation.create(
            annotation_type=AnnotationType(annotation_type),
            plot_name=plot_name,
            label=group_name,
            color=group_color,
            is_global=group_is_global,
            subplot_name=subplot_name,
            group_id=group_id,
            group_name=group_name,
            data=data,
            trace_metadata=trace_metadata or None,
        )
        return (
            mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            "",
            annotation_set.with_added(annotation).to_dicts(),
            no_update,
            no_update,
        )

    # --- Normal mode ---
    suggested_color = trace_info.get("line_color") or ANNOTATION_COLORS[0]

    if annotation_type == AnnotationType.TIME_WINDOW.value:
        is_first, stored_x0, new_mode = _check_pending_x0(mode, x_str, plot_name)
        if is_first:
            return (
                new_mode,
                no_update,
                ANNOTATION_MODAL_STYLE_HIDDEN,
                no_update_patches,
                "",
                no_update,
                no_update,
                no_update,
            )

        modal_data: dict[str, Any] = {
            "type": annotation_type,
            "plot_name": plot_name,
            "x0": stored_x0,
            "x1": x_str,
            "xaxis": xaxis_ref,
            "subplot_name": subplot_name,
            "suggested_color": suggested_color,
            "display_timezone": display_tz,
        }
        if trace_metadata:
            modal_data["trace_metadata"] = trace_metadata
        return (
            new_mode,
            modal_data,
            ANNOTATION_MODAL_STYLE_SHOWN,
            no_update_patches,
            "",
            no_update,
            no_update,
            no_update,
        )

    modal_data = {
        "type": annotation_type,
        "plot_name": plot_name,
        "x": x_str,
        "xaxis": xaxis_ref,
        "subplot_name": subplot_name,
        "suggested_color": suggested_color,
        "display_timezone": display_tz,
    }
    if annotation_type == AnnotationType.POINT.value:
        modal_data["y"] = y_val
        modal_data["yaxis"] = yaxis_ref
        if click_point_time:
            modal_data["t"] = click_point_time
    if trace_metadata:
        modal_data["trace_metadata"] = trace_metadata

    return (
        mode,
        modal_data,
        ANNOTATION_MODAL_STYLE_SHOWN,
        no_update_patches,
        "",
        no_update,
        no_update,
        no_update,
    )


# ---------------------------------------------------------------------------
# 3. Populate modal UI from modal-data store
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-modal-position-display", "children"),
    Output("annotation-label-input", "value"),
    Output("annotation-global-checkbox", "value"),
    Output("annotation-color-input", "value"),
    Input("annotation-modal-data", "data"),
    prevent_initial_call=True,
)
def update_modal_ui(modal_data: dict) -> tuple[str, str, list, str]:
    """Refresh position text, global checkbox and color when modal data changes."""
    if not modal_data:
        raise PreventUpdate
    position_text = _format_position(modal_data)
    color = modal_data.get("suggested_color", ANNOTATION_COLORS[0])
    return position_text, "", [], color


# ---------------------------------------------------------------------------
# 4. Toggle global checkbox visibility based on annotation type
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-global-checkbox-container", "style"),
    Input("annotation-modal-data", "data"),
    prevent_initial_call=True,
)
def toggle_global_checkbox_visibility(modal_data: dict) -> dict:
    """Hide the global checkbox for annotations that cannot be global (points)."""
    if not modal_data:
        raise PreventUpdate
    # StrEnum members hash as their value, so the raw payload string tests directly.
    if modal_data.get("type", "") not in TIME_BASED_ANNOTATION_TYPES:
        return {"marginBottom": "20px", "display": "none"}
    return {"marginBottom": "20px"}


# ---------------------------------------------------------------------------
# 5. Colour pickers — one per creation modal (annotation, group)
# ---------------------------------------------------------------------------
# The hex input is the single source of truth: presets only write to it, the preview only
# reads from it. A second indicator of the selected colour would inevitably desync from it.


@callback(
    Output("annotation-color-input", "value", allow_duplicate=True),
    Input({"type": "annotation-color-swatch", "color": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def pick_annotation_color_swatch(_n_clicks_list: list) -> str:
    """Write the clicked preset into the annotation modal hex input."""
    if ctx.triggered_id is None:
        raise PreventUpdate
    return ctx.triggered_id["color"]


@callback(
    Output("group-color-input", "value", allow_duplicate=True),
    Input({"type": "group-color-swatch", "color": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def pick_group_color_swatch(_n_clicks_list: list) -> str:
    """Write the clicked preset into the group modal hex input."""
    if ctx.triggered_id is None:
        raise PreventUpdate
    return ctx.triggered_id["color"]


@callback(
    Output("annotation-color-preview", "style"),
    Input("annotation-color-input", "value"),
)
def update_annotation_color_preview(color: str) -> dict:
    """Mirror the annotation hex input, showing the colour that Create would actually save."""
    return {**COLOR_PREVIEW_SWATCH, "backgroundColor": normalize_hex_color(color)}


@callback(
    Output("group-color-preview", "style"),
    Input("group-color-input", "value"),
)
def update_group_color_preview(color: str) -> dict:
    """Mirror the group hex input, showing the colour that the group would actually get."""
    return {**COLOR_PREVIEW_SWATCH, "backgroundColor": normalize_hex_color(color)}


# ---------------------------------------------------------------------------
# 6. Create annotation
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-modal", "style", allow_duplicate=True),
    Input("create-annotation-btn", "n_clicks"),
    State("annotation-modal-data", "data"),
    State("annotation-label-input", "value"),
    State("annotation-color-input", "value"),
    State("annotation-global-checkbox", "value"),
    State("annotation-store", "data"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def create_annotation(
    _n: int,
    modal_data: dict,
    label: str,
    color: str,
    global_checkbox: list,
    annotations_raw: list,
    mode: dict,
) -> tuple[list, dict, dict]:
    """Confirm annotation creation and append it to the store."""
    if not modal_data:
        raise PreventUpdate

    annotation_type = AnnotationType(modal_data["type"])
    is_global = "global" in (global_checkbox or [])
    color = normalize_hex_color(color)

    data = _build_annotation_data(
        annotation_type,
        x=modal_data.get("x"),
        x0=modal_data.get("x0"),
        x1=modal_data.get("x1"),
        xaxis=modal_data.get("xaxis", "x"),
        y=modal_data.get("y"),
        yaxis=modal_data.get("yaxis", "y"),
        point_time=modal_data.get("t"),
    )

    annotation = Annotation.create(
        annotation_type=annotation_type,
        plot_name=modal_data["plot_name"],
        label=label or "",
        color=color,
        is_global=is_global,
        subplot_name=modal_data.get("subplot_name"),
        data=data,
        trace_metadata=modal_data.get("trace_metadata"),
    )

    new_annotations = AnnotationSet.from_dicts(annotations_raw).with_added(annotation).to_dicts()
    new_mode = {
        **(mode or default_mode()),
        "pending_x0": None,
        "pending_plot_name": None,
        "moving_id": None,
    }
    return new_annotations, new_mode, ANNOTATION_MODAL_STYLE_HIDDEN


# ---------------------------------------------------------------------------
# 7. Cancel annotation (both x button and Cancel footer button)
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-modal", "style", allow_duplicate=True),
    Input("cancel-annotation-btn", "n_clicks"),
    Input("cancel-annotation-btn-footer", "n_clicks"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def cancel_annotation(_h: int, _f: int, mode: dict) -> tuple[dict, dict]:
    """Close the modal and discard any pending time-window first click."""
    new_mode = {
        **(mode or default_mode()),
        "pending_x0": None,
        "pending_plot_name": None,
        "moving_id": None,
    }
    return new_mode, ANNOTATION_MODAL_STYLE_HIDDEN


# ---------------------------------------------------------------------------
# 8. Render annotations on all graphs
# ---------------------------------------------------------------------------


@callback(
    Output({"type": "graph", "name": ALL}, "figure", allow_duplicate=True),
    Input("annotation-store", "data"),
    Input("annotation-mode-store", "data"),
    State({"type": "graph", "name": ALL}, "id"),
    State({"type": "graph-subplots", "name": ALL}, "data"),
    State("display-timezone-store", "data"),
    State("user-options-store", "data"),
    prevent_initial_call=True,
)
def render_annotations(
    annotations_raw: list,
    mode: dict,
    graph_ids: list,
    subplots_list: list,
    display_timezone: str | None,
    user_options: dict[str, Any] | None,
) -> list:
    """Rebuild layout.shapes and layout.annotations for every visible graph using Patch()."""
    if not graph_ids:
        raise PreventUpdate

    display_tz = display_timezone or cst.DISPLAY_TIMEZONE
    annotations = [
        normalize_annotation_for_display(annotation, display_tz)
        for annotation in AnnotationSet.from_dicts(annotations_raw)
    ]
    mode = mode or default_mode()
    pending_x0 = mode.get("pending_x0")
    pending_plot = mode.get("pending_plot_name")
    point_mode_active = mode.get("active") and mode.get("type") == AnnotationType.POINT.value
    display_fallbacks = DisplayFallbacks.from_user_options(user_options or {})

    subplot_map = {
        graph_id["name"]: (subplots_list[idx] or {}) for idx, graph_id in enumerate(graph_ids)
    }

    patches = []
    for graph_id in graph_ids:
        plot_name = graph_id["name"]
        subplots_data = subplot_map.get(plot_name, {})
        subplot_title_annotations = subplots_data.get("subplot_annotations", [])

        raw_pending_x0 = pending_x0 if pending_plot == plot_name else None
        graph_pending_x0 = (
            to_naive_display_ts(raw_pending_x0, display_tz) if raw_pending_x0 else None
        )
        subplot_rows = subplots_data.get("rows", [])

        shapes, all_annotations = build_figure_overlays(
            annotations=annotations,
            plot_name=plot_name,
            subplot_annotations=subplot_title_annotations,
            subplot_rows=subplot_rows,
            pending_x0=graph_pending_x0,
        )

        patch = Patch()
        patch.layout.shapes = shapes
        # Replacing with an empty list would wipe the subplot titles while the
        # subplot-annotations store is still unpopulated, so leave them untouched instead.
        if all_annotations:
            patch.layout.annotations = all_annotations
        # Same capability PlotModel.to_figure reads, so the two stay in step. Point mode
        # forces the nearest point; otherwise restore the user's own panel style, since this
        # patch runs after to_figure and would otherwise silently discard it.
        if plot_types.definition_for(subplots_data.get("plot_type")).UNIFIED_HOVER:
            patch.layout.hovermode = (
                cst.HoverMode.CLOSEST if point_mode_active else display_fallbacks.hovermode
            )
        patches.append(patch)

    return patches


# ---------------------------------------------------------------------------
# 9. Annotation list — grouped, collapsible
# ---------------------------------------------------------------------------


def _group_header_row(group: Group, is_expanded: bool) -> html.Div:
    """Build a collapsible group header row with per-group action buttons."""
    toggle_icon = "▼" if is_expanded else "▶"
    labels_label = "Labels: off" if group.labels_hidden else "Labels: on"
    labels_style = {
        **BUTTON_ANNOTATION_SMALL,
        "backgroundColor": "#6c757d" if group.labels_hidden else "#adb5bd",
        **(BUTTON_DISABLED_OVERLAY if group.hidden else {}),
    }
    visible_label = "Visible: off" if group.hidden else "Visible: on"
    visible_style = {
        **BUTTON_ANNOTATION_SMALL,
        "backgroundColor": "#6c757d" if group.hidden else "#adb5bd",
    }

    type_icon = _TYPE_ICONS.get(group.type, "?")
    type_label = _TYPE_LABELS.get(group.type, group.type)

    # Scope badge only for time-based annotations (global/subplot distinction is
    # meaningless for points which are always subplot-specific).
    scope_badge = None
    if group.type in TIME_BASED_ANNOTATION_TYPES:
        scope_text = "Global" if group.is_global else "Subplot"
        scope_color = "#5a9fd4" if group.is_global else "#e67e00"
        scope_badge = html.Span(
            scope_text,
            style={
                "fontSize": "10px",
                "backgroundColor": scope_color,
                "color": "white",
                "borderRadius": "3px",
                "padding": "1px 5px",
                "flexShrink": 0,
            },
        )

    return html.Div(
        [
            html.Button(
                toggle_icon,
                id={"type": "group-toggle-btn", "id": group.id},
                n_clicks=0,
                style={
                    "background": "none",
                    "border": "none",
                    "cursor": "pointer",
                    "padding": "0 4px",
                    "fontSize": "12px",
                    "color": "#555",
                    "flexShrink": 0,
                },
            ),
            html.Span(
                type_icon,
                style={
                    "color": group.color,
                    "fontSize": "16px",
                    "fontWeight": "bold",
                    "minWidth": "16px",
                    "textAlign": "center",
                    "flexShrink": 0,
                },
            ),
            html.Span(
                group.name,
                style={"fontWeight": "bold", "fontSize": "13px", "flex": 1, "color": "#333"},
            ),
            html.Span(
                type_label,
                style={"color": "#888", "fontSize": "11px", "flexShrink": 0},
            ),
            *([scope_badge] if scope_badge else []),
            html.Span(
                f"({len(group)})",
                style={"color": "#888", "fontSize": "12px", "flexShrink": 0},
            ),
            html.Button(
                "▶ Continue",
                id={"type": "group-continue-btn", "id": group.id},
                n_clicks=0,
                style=BUTTON_ANNOTATION_SMALL,
            ),
            html.Button(
                labels_label,
                id={"type": "group-labels-btn", "id": group.id},
                n_clicks=0,
                disabled=group.hidden,
                style=labels_style,
            ),
            html.Button(
                visible_label,
                id={"type": "group-hidden-btn", "id": group.id},
                n_clicks=0,
                style=visible_style,
            ),
            html.Button(
                "Delete all",
                id={"type": "group-delete-btn", "id": group.id},
                n_clicks=0,
                style={**BUTTON_ANNOTATION_SMALL, "backgroundColor": "#dc3545"},
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "4px",
            "padding": "5px 8px",
            "backgroundColor": "#efefef",
            "borderBottom": "1px solid #dee2e6",
        },
    )


@callback(
    Output("annotation-list-panel", "children"),
    Output("annotation-list-panel", "style"),
    Output("annotation-count-badge", "children"),
    Input("annotation-store", "data"),
    Input("annotation-expanded-groups-store", "data"),
    State("display-timezone-store", "data"),
    prevent_initial_call=False,
)
def update_annotation_list(
    annotations_raw: list,
    expanded_groups: list,
    display_timezone: str | None,
) -> tuple[list, dict, str]:
    """
    Rebuild the annotation list, always sorted by group with collapsible group sections.

    Only the *contents* are rebuilt: the scrolling element is the layout's own panel div, so a
    label or visibility toggle leaves the reader where they were scrolled to.
    """
    annotation_set = AnnotationSet.from_dicts(annotations_raw)
    if not len(annotation_set):
        return [], ANNOTATION_LIST_PANEL_HIDDEN, ""

    expanded_set = set(expanded_groups or [])
    groups = annotation_set.groups()
    ungrouped = annotation_set.ungrouped()

    rows: list = []

    for group in groups:
        is_expanded = group.id in expanded_set
        rows.append(_group_header_row(group, is_expanded))

        if is_expanded:
            rows.extend(
                _annotation_list_row(annotation, group_name=group.name, display_tz=display_timezone)
                for annotation in group.annotations
            )

    if ungrouped:
        if groups:
            rows.append(
                html.Div(
                    "Other annotations",
                    style={
                        "padding": "4px 8px",
                        "backgroundColor": "#efefef",
                        "borderBottom": "1px solid #dee2e6",
                        "fontSize": "12px",
                        "color": "#888",
                        "fontStyle": "italic",
                    },
                )
            )
        rows.extend(
            _annotation_list_row(annotation, display_tz=display_timezone)
            for annotation in ungrouped
        )

    count = len(annotation_set)
    # An all-hidden set draws an empty plot; without the suffix the badge would read as
    # "1000 annotations" beside it, which looks like a failed load rather than a choice.
    hidden_count = sum(1 for annotation in annotation_set if annotation.hidden)
    count_text = f"{count} annotation{'s' if count != 1 else ''}"
    if hidden_count:
        count_text += f" · {hidden_count} hidden"
    header = html.Div(
        "Annotations",
        style={
            "fontWeight": "bold",
            "fontSize": "13px",
            "color": "#555",
            "marginBottom": "4px",
            "borderBottom": "1px solid #dee2e6",
            "paddingBottom": "4px",
        },
    )
    return [header, *rows], ANNOTATION_LIST_PANEL, count_text


# ---------------------------------------------------------------------------
# 10. Toggle group expanded state OR label visibility
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-expanded-groups-store", "data"),
    Input({"type": "group-toggle-btn", "id": ALL}, "n_clicks"),
    State("annotation-expanded-groups-store", "data"),
    prevent_initial_call=True,
)
def toggle_group_expand(_n_clicks_list: list, expanded_groups: list) -> list:
    """Add or remove a group ID from the expanded set when its header is clicked."""
    # Rebuilding the list recreates the buttons with n_clicks=0, which would fire a
    # spurious toggle — so only react to a real click.
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    group_id = triggered_id["id"]
    expanded = list(expanded_groups or [])
    if group_id in expanded:
        expanded.remove(group_id)
    else:
        expanded.append(group_id)
    return expanded


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Input({"type": "group-labels-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    prevent_initial_call=True,
)
def toggle_group_labels(_n: list, annotations_raw: list) -> list:
    """Flip label_hidden for all group annotations: hide all if any visible, show all otherwise."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    group_id = triggered_id["id"]
    return AnnotationSet.from_dicts(annotations_raw).with_group_labels_toggled(group_id).to_dicts()


# ---------------------------------------------------------------------------
# 10b-bis. Toggle whether a whole group is drawn at all
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Input({"type": "group-hidden-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    prevent_initial_call=True,
)
def toggle_group_hidden(_n: list, annotations_raw: list) -> list:
    """Flip `hidden` for all group annotations: hide all if any shown, show all otherwise."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    group_id = triggered_id["id"]
    return AnnotationSet.from_dicts(annotations_raw).with_group_hidden_toggled(group_id).to_dicts()


# ---------------------------------------------------------------------------
# 10c. Delete all annotations in a group
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Output("annotation-expanded-groups-store", "data", allow_duplicate=True),
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-active-group-display", "children", allow_duplicate=True),
    Output("annotation-mode-deactivate", "style", allow_duplicate=True),
    Input({"type": "group-delete-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    State("annotation-expanded-groups-store", "data"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def delete_group(
    _n: list,
    annotations_raw: list,
    expanded_groups: list,
    mode: dict,
) -> tuple:
    """Remove all annotations belonging to a group; deactivate mode if that group was active."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    group_id = triggered_id["id"]
    new_annotations = AnnotationSet.from_dicts(annotations_raw).without_group(group_id).to_dicts()
    new_expanded = [
        expanded_group_id
        for expanded_group_id in (expanded_groups or [])
        if expanded_group_id != group_id
    ]

    mode = mode or default_mode()
    if mode.get("group_id") == group_id:
        new_mode = {
            **mode,
            "active": False,
            "group_id": None,
            "pending_x0": None,
            "pending_plot_name": None,
            "moving_id": None,
        }
        return (
            new_annotations,
            new_expanded,
            new_mode,
            "",
            {**BUTTON_ANNOTATION_INACTIVE, "display": "none"},
        )
    return new_annotations, new_expanded, no_update, no_update, no_update


# ---------------------------------------------------------------------------
# 11. Save / reset save-button — one callback dispatching on triggered_id, so neither output
# needs allow_duplicate: a store change resets the button, the button performs the write.
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-save-status", "children"),
    Output("annotation-save-btn", "style"),
    Input("annotation-save-btn", "n_clicks"),
    Input("annotation-store", "data"),
    State("folder-visu-path", "data"),
    prevent_initial_call=True,
)
def save_annotations_cb(_n: int, annotations_raw: list, folder: str) -> tuple[str, dict]:
    """Write annotations.json on save-button click; reset button style on any store change."""
    if ctx.triggered_id == "annotation-store":
        return "", BUTTON_ANNOTATION_SAVE

    # Triggered by the save button.
    if not folder:
        return "No patient folder loaded.", BUTTON_ANNOTATION_SAVE
    try:
        annotations = AnnotationSet.from_dicts(annotations_raw).annotations
        save_annotations(annotations, folder)
        return f"Saved ({len(annotations)})", {
            **BUTTON_ANNOTATION_SAVE,
            "backgroundColor": "#28a745",
        }
    except Exception:
        logger.exception("Failed to save annotations")
        return "Save failed.", {**BUTTON_ANNOTATION_SAVE, "backgroundColor": "#dc3545"}


# ---------------------------------------------------------------------------
# 12. Auto-load annotations when a new patient folder is visualised
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Output("annotation-toolbar", "style"),
    Output("annotation-expanded-groups-store", "data", allow_duplicate=True),
    Input("folder-visu-path", "data"),
    prevent_initial_call=True,
)
def auto_load_annotations(folder: str) -> tuple[list, dict, list]:
    """Load annotations from the patient folder; groups are derived on-demand from annotations."""
    toolbar_shown = {**ANNOTATION_TOOLBAR_STYLE, "display": "flex"}

    if not folder:
        return [], {**ANNOTATION_TOOLBAR_STYLE, "display": "none"}, []

    try:
        annotations = load_annotations(folder)
    except Exception:
        logger.warning("Unexpected error loading annotations from %s", folder, exc_info=True)
        annotations = []

    # Reset expanded state so all groups start collapsed when a new patient is loaded
    return [annotation.to_dict() for annotation in annotations], toolbar_shown, []


# ---------------------------------------------------------------------------
# 13. Delete one annotation by ID
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Input({"type": "annotation-delete-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    prevent_initial_call=True,
)
def delete_annotation(n_clicks_list: list, annotations_raw: list) -> list:
    """Remove the annotation whose delete button was clicked."""
    triggered_id = ctx.triggered_id
    if triggered_id is None or not any(n_clicks_list):
        raise PreventUpdate
    annotation_id = triggered_id["id"]
    return AnnotationSet.from_dicts(annotations_raw).without(annotation_id).to_dicts()


# ---------------------------------------------------------------------------
# 14. Open group creation modal
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-group-modal", "style"),
    Output("group-name-input", "value"),
    Output("group-color-input", "value"),
    Input("new-group-btn", "n_clicks"),
    prevent_initial_call=True,
)
def open_group_modal(_n: int) -> tuple[dict, str, str]:
    """Show the group creation modal and reset its fields."""
    return ANNOTATION_MODAL_STYLE_SHOWN, "", ANNOTATION_COLORS[0]


# ---------------------------------------------------------------------------
# 15. Create annotation group
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-group-modal", "style", allow_duplicate=True),
    Output("annotation-active-group-display", "children", allow_duplicate=True),
    Output("annotation-mode-deactivate", "style", allow_duplicate=True),
    Output("annotation-type-btn-time_event", "style", allow_duplicate=True),
    Output("annotation-type-btn-time_window", "style", allow_duplicate=True),
    Output("annotation-type-btn-point", "style", allow_duplicate=True),
    Input("create-group-btn", "n_clicks"),
    Input({"type": "group-continue-btn", "id": ALL}, "n_clicks"),
    State("group-name-input", "value"),
    State("group-type-dropdown", "value"),
    State("group-color-input", "value"),
    State("group-scope-is-global", "value"),
    State("annotation-store", "data"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def activate_group(
    _create: int,
    _continue_list: list,
    name: str,
    annotation_type_value: str,
    color: str,
    scope_value: list,
    annotations_raw: list,
    mode: dict,
) -> tuple:
    """Create a new annotation group or re-activate an existing one, then enter group mode."""

    triggered_id = ctx.triggered_id
    deactivate_style = {**BUTTON_ANNOTATION_INACTIVE, "display": "inline-block"}
    inactive = BUTTON_ANNOTATION_INACTIVE

    if triggered_id == "create-group-btn":
        if not name:
            raise PreventUpdate
        color = normalize_hex_color(color)
        annotation_type = AnnotationType(annotation_type_value or AnnotationType.TIME_EVENT.value)
        is_global = (
            "global" in (scope_value or []) and annotation_type in TIME_BASED_ANNOTATION_TYPES
        )
        new_mode = {
            **(mode or default_mode()),
            "active": True,
            "type": annotation_type.value,
            "group_id": str(uuid.uuid4()),
            "group_name": name,
            "group_color": color,
            "group_is_global": is_global,
            "pending_x0": None,
            "pending_plot_name": None,
            "moving_id": None,
        }
        return (
            new_mode,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            f"Group: {name}",
            deactivate_style,
            inactive,
            inactive,
            inactive,
        )

    # Triggered by a "Continue" button on an existing group — derive props from annotations.
    if not any(_continue_list):
        raise PreventUpdate
    group_id = triggered_id["id"]
    group = AnnotationSet.from_dicts(annotations_raw).group(group_id)
    if group is None:
        raise PreventUpdate
    group_name = group.name
    new_mode = {
        **(mode or default_mode()),
        "active": True,
        "type": group.type.value,
        "group_id": group_id,
        "group_name": group_name,
        "group_color": group.color,
        "group_is_global": group.is_global,
        "pending_x0": None,
        "pending_plot_name": None,
        "moving_id": None,
    }
    return (
        new_mode,
        no_update,
        f"Group: {group_name}",
        deactivate_style,
        inactive,
        inactive,
        inactive,
    )


@callback(
    Output("annotation-group-modal", "style", allow_duplicate=True),
    Input("cancel-group-btn", "n_clicks"),
    Input("cancel-group-btn-footer", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_group_modal(_h: int, _f: int) -> dict:
    """Close the group creation modal without creating a group."""
    return ANNOTATION_MODAL_STYLE_HIDDEN


# ---------------------------------------------------------------------------
# 16. Toggle label visibility for an individual annotation
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Input({"type": "annotation-label-toggle-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    prevent_initial_call=True,
)
def toggle_annotation_label(_n: list, annotations_raw: list) -> list:
    """Flip label_hidden on the annotation whose toggle button was clicked."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    annotation_id = triggered_id["id"]
    return AnnotationSet.from_dicts(annotations_raw).with_label_toggled(annotation_id).to_dicts()


# ---------------------------------------------------------------------------
# 16b. Toggle whether an individual annotation is drawn at all
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Input({"type": "annotation-hidden-toggle-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    prevent_initial_call=True,
)
def toggle_annotation_hidden(_n: list, annotations_raw: list) -> list:
    """Flip `hidden` on the annotation whose visibility button was clicked."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    annotation_id = triggered_id["id"]
    return AnnotationSet.from_dicts(annotations_raw).with_hidden_toggled(annotation_id).to_dicts()


# ---------------------------------------------------------------------------
# 17. Arm a move — the next graph click re-places this annotation
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-type-btn-time_event", "style", allow_duplicate=True),
    Output("annotation-type-btn-time_window", "style", allow_duplicate=True),
    Output("annotation-type-btn-point", "style", allow_duplicate=True),
    Output("annotation-mode-deactivate", "style", allow_duplicate=True),
    Output("annotation-active-group-display", "children", allow_duplicate=True),
    Input({"type": "annotation-move-btn", "id": ALL}, "n_clicks"),
    State("annotation-store", "data"),
    State("annotation-mode-store", "data"),
    prevent_initial_call=True,
)
def start_move(_n: list, annotations_raw: list, mode: dict) -> tuple:
    """Enter move mode for the annotation whose move button was clicked."""
    if not ctx.triggered or ctx.triggered[0]["value"] <= 0:
        raise PreventUpdate
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    annotation_id = triggered_id["id"]
    target = next(
        (
            annotation
            for annotation in AnnotationSet.from_dicts(annotations_raw)
            if annotation.id == annotation_id
        ),
        None,
    )
    if target is None:
        raise PreventUpdate

    # The click handler routes on `type`, so a window move gets its two-click state machine
    # for free.  Group mode is cleared rather than nested: "▶ Continue" costs one click.
    new_mode = {
        **(mode or default_mode()),
        "active": True,
        "type": target.type.value,
        "moving_id": annotation_id,
        "pending_x0": None,
        "pending_plot_name": None,
        "group_id": None,
        "group_name": None,
        "group_color": None,
        "group_is_global": False,
    }

    def _btn_style(annotation_type_value: str) -> dict:
        if annotation_type_value == target.type.value:
            return BUTTON_ANNOTATION_ACTIVE
        return BUTTON_ANNOTATION_INACTIVE

    gesture = (
        "click the new start, then the new end"
        if target.type == AnnotationType.TIME_WINDOW
        else "click the new position"
    )
    display_label = target.label or _TYPE_LABELS.get(target.type.value, target.type.value)

    return (
        new_mode,
        _btn_style(AnnotationType.TIME_EVENT.value),
        _btn_style(AnnotationType.TIME_WINDOW.value),
        _btn_style(AnnotationType.POINT.value),
        {**BUTTON_ANNOTATION_INACTIVE, "display": "inline-block"},
        f'Moving "{display_label}" — {gesture}',
    )
