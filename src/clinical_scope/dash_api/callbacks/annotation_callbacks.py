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
    AnnotationType,
)
from clinical_scope.dash_api.annotations.renderer import (
    build_figure_overlays,
    normalize_annotation_for_display,
)
from clinical_scope.dash_api.styles import (
    ANNOTATION_LIST_ROW,
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_MODAL_STYLE_SHOWN,
    ANNOTATION_TOOLBAR_STYLE,
    BUTTON_ANNOTATION_ACTIVE,
    BUTTON_ANNOTATION_INACTIVE,
    BUTTON_ANNOTATION_SAVE,
    BUTTON_MODAL_CLOSE,
)
from clinical_scope.datasource.formatting.timezone import to_naive_display_ts

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

_SMALL_BTN: dict = {
    **BUTTON_ANNOTATION_INACTIVE,
    "padding": "2px 7px",
    "fontSize": "11px",
}


def default_mode() -> dict:
    """
    Return a fresh annotation-mode-store value.

    This dict is the annotation state machine: ``active`` gates click handling, the
    ``pending_*`` pair holds a time-window's first click, and the ``group_*`` fields —
    set only in group mode — make clicks bypass the creation modal.
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
    }


def _localize_x_val(x_val: str, display_tz: str = cst.DISPLAY_TIMEZONE) -> str:
    """Return x_val as an ISO string with timezone offset; pass-through for non-datetime values."""
    try:
        ts = pd.Timestamp(x_val)
        if pd.isna(ts):
            return x_val
        if ts.tzinfo is None:
            ts = ts.tz_localize(display_tz)
        return ts.isoformat()
    except Exception:  # noqa: BLE001
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


def _build_swatch_styles(selected_color: str, swatch_ids: list[dict]) -> list[dict]:
    """Return a style list for colour swatches, highlighting the selected one."""
    styles = []
    for swatch_id in swatch_ids:
        color = swatch_id["color"]
        border = "3px solid #333" if color == selected_color else "2px solid transparent"
        styles.append(
            {
                "width": "22px",
                "height": "22px",
                "borderRadius": "50%",
                "backgroundColor": color,
                "cursor": "pointer",
                "border": border,
                "flexShrink": 0,
            }
        )
    return styles


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

    label_text = "L:off" if annotation.label_hidden else "L:on"
    label_style = {
        **_SMALL_BTN,
        "backgroundColor": "#6c757d" if annotation.label_hidden else "#adb5bd",
        "padding": "1px 5px",
        "fontSize": "10px",
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
                style=label_style,
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
            }
        else:
            new_mode = {**mode, "active": True, "type": annotation_type, "group_id": None}

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
) -> tuple[dict, dict, dict, list, str, list]:
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

    is_loop = subplots_data.get("plot_type") == cst.PlotType.LOOP
    if is_loop and annotation_type in TIME_BASED_ANNOTATION_TYPES:
        logger.warning(
            "User attempted to create %s annotation on a loop plot. "
            "Loop plots have non-time x-axes, so only Point annotations are valid.",
            annotation_type,
        )
        return (
            mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            "⚠ Time-based annotations are not supported on loop plots — switch to Point.",
            no_update,
        )

    x_str = str(x_val) if is_loop else _localize_x_val(str(x_val), display_tz)

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

    # --- Group mode: bypass modal, create annotation immediately ---
    group_id = mode.get("group_id")
    if group_id:
        group_name = mode.get("group_name", "")
        group_color = mode.get("group_color", ANNOTATION_COLORS[0])
        group_is_global = mode.get("group_is_global", False)
        current_annotations = list(annotations_raw or [])

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
                )

            data: dict[str, Any] = {"x0": stored_x0, "x1": x_str, "xaxis": xaxis_ref}
            annotation = Annotation(
                type=AnnotationType(annotation_type),
                plot_name=plot_name,
                label=group_name,
                color=group_color,
                subplot_name=None if group_is_global else subplot_name,
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
                [*current_annotations, annotation.to_dict()],
            )

        if annotation_type == AnnotationType.POINT.value:
            data = {
                "x": x_str,
                "y": y_val,
                "xaxis": xaxis_ref,
                "yaxis": yaxis_ref,
            }
            if is_loop:
                raw_t = point.get("customdata")
                if raw_t:
                    with contextlib.suppress(Exception):
                        data["t"] = pd.Timestamp(str(raw_t)).tz_localize(display_tz).isoformat()
            ann_subplot = subplot_name
        else:
            data = {"x": x_str, "xaxis": xaxis_ref}
            ann_subplot = None if group_is_global else subplot_name

        annotation = Annotation(
            type=AnnotationType(annotation_type),
            plot_name=plot_name,
            label=group_name,
            color=group_color,
            subplot_name=ann_subplot,
            group_id=group_id,
            group_name=group_name,
            data=data,
            trace_metadata=trace_metadata or None,
            label_hidden=annotation_type == AnnotationType.POINT.value,
        )
        return (
            mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            "",
            [*current_annotations, annotation.to_dict()],
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
            )

        modal_data: dict[str, Any] = {
            "type": annotation_type,
            "plot_name": plot_name,
            "x0": stored_x0,
            "x1": x_str,
            "xaxis": xaxis_ref,
            "auto_subplot_row": auto_subplot_row,
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
        )

    modal_data = {
        "type": annotation_type,
        "plot_name": plot_name,
        "x": x_str,
        "xaxis": xaxis_ref,
        "auto_subplot_row": auto_subplot_row,
        "subplot_name": subplot_name,
        "suggested_color": suggested_color,
        "display_timezone": display_tz,
    }
    if annotation_type == AnnotationType.POINT.value:
        modal_data["y"] = y_val
        modal_data["yaxis"] = yaxis_ref
        if is_loop:
            raw_t = point.get("customdata")
            if raw_t:
                with contextlib.suppress(Exception):
                    modal_data["t"] = pd.Timestamp(str(raw_t)).tz_localize(display_tz).isoformat()
    if trace_metadata:
        modal_data["trace_metadata"] = trace_metadata

    return mode, modal_data, ANNOTATION_MODAL_STYLE_SHOWN, no_update_patches, "", no_update


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
    """Hide the global checkbox for POINT annotations (they're always subplot-specific)."""
    if not modal_data:
        raise PreventUpdate
    annotation_type = modal_data.get("type", "")
    if annotation_type == AnnotationType.POINT.value:
        return {"marginBottom": "20px", "display": "none"}
    return {"marginBottom": "20px"}


# ---------------------------------------------------------------------------
# 5. Colour swatch pickers — one per creation modal (annotation, group)
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-color-input", "value", allow_duplicate=True),
    Output({"type": "annotation-color-swatch", "color": ALL}, "style"),
    Input({"type": "annotation-color-swatch", "color": ALL}, "n_clicks"),
    State({"type": "annotation-color-swatch", "color": ALL}, "id"),
    prevent_initial_call=True,
)
def pick_annotation_color_swatch(_n_clicks_list: list, swatch_ids: list) -> tuple[str, list]:
    """Highlight the selected colour swatch and update the annotation modal hex input."""
    if ctx.triggered_id is None:
        raise PreventUpdate
    selected = ctx.triggered_id["color"]
    return selected, _build_swatch_styles(selected, swatch_ids)


@callback(
    Output("group-color-input", "value", allow_duplicate=True),
    Output({"type": "group-color-swatch", "color": ALL}, "style"),
    Input({"type": "group-color-swatch", "color": ALL}, "n_clicks"),
    State({"type": "group-color-swatch", "color": ALL}, "id"),
    prevent_initial_call=True,
)
def pick_group_color_swatch(_n_clicks_list: list, swatch_ids: list) -> tuple[str, list]:
    """Highlight the selected colour swatch and update the group modal hex input."""
    if ctx.triggered_id is None:
        raise PreventUpdate
    selected = ctx.triggered_id["color"]
    return selected, _build_swatch_styles(selected, swatch_ids)


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
    subplot_name = None if is_global else modal_data.get("subplot_name")
    color = color or ANNOTATION_COLORS[0]

    if annotation_type == AnnotationType.TIME_EVENT:
        data = {"x": modal_data["x"], "xaxis": modal_data.get("xaxis", "x")}
    elif annotation_type == AnnotationType.TIME_WINDOW:
        data = {
            "x0": modal_data["x0"],
            "x1": modal_data["x1"],
            "xaxis": modal_data.get("xaxis", "x"),
        }
    elif annotation_type == AnnotationType.POINT:
        data = {
            "x": modal_data["x"],
            "y": modal_data.get("y"),
            "xaxis": modal_data.get("xaxis", "x"),
            "yaxis": modal_data.get("yaxis", "y"),
        }
        if "t" in modal_data:
            data["t"] = modal_data["t"]
    else:
        raise PreventUpdate

    annotation = Annotation(
        type=annotation_type,
        plot_name=modal_data["plot_name"],
        label=label or "",
        color=color,
        subplot_name=subplot_name,
        data=data,
        trace_metadata=modal_data.get("trace_metadata"),
        label_hidden=annotation_type == AnnotationType.POINT,
    )

    new_annotations = [*(annotations_raw or []), annotation.to_dict()]
    new_mode = {**(mode or default_mode()), "pending_x0": None, "pending_plot_name": None}
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
    new_mode = {**(mode or default_mode()), "pending_x0": None, "pending_plot_name": None}
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
    prevent_initial_call=True,
)
def render_annotations(
    annotations_raw: list,
    mode: dict,
    graph_ids: list,
    subplots_list: list,
    display_timezone: str | None,
) -> list:
    """Rebuild layout.shapes and layout.annotations for every visible graph using Patch()."""
    if not graph_ids:
        raise PreventUpdate

    display_tz = display_timezone or cst.DISPLAY_TIMEZONE
    annotations = [
        normalize_annotation_for_display(Annotation.from_dict(annotation_dict), display_tz)
        for annotation_dict in (annotations_raw or [])
    ]
    mode = mode or default_mode()
    pending_x0 = mode.get("pending_x0")
    pending_plot = mode.get("pending_plot_name")
    point_mode_active = mode.get("active") and mode.get("type") == AnnotationType.POINT.value

    subplot_map = {
        graph_id["name"]: (subplots_list[idx] or {}) for idx, graph_id in enumerate(graph_ids)
    }

    patches = []
    for graph_id in graph_ids:
        plot_name = graph_id["name"]
        subplots_data = subplot_map.get(plot_name, {})
        subplot_title_annotations = subplots_data.get("subplot_annotations", [])
        is_loop = subplots_data.get("plot_type") == cst.PlotType.LOOP

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
        if not is_loop:
            patch.layout.hovermode = "closest" if point_mode_active else "x unified"
        patches.append(patch)

    return patches


# ---------------------------------------------------------------------------
# 9. Annotation list — grouped, collapsible
# ---------------------------------------------------------------------------


def _group_header_row(
    group: dict,
    annotation_count: int,
    is_expanded: bool,
    is_hidden: bool = False,
) -> html.Div:
    """Build a collapsible group header row with per-group action buttons."""
    toggle_icon = "▼" if is_expanded else "▶"
    labels_label = "Labels: off" if is_hidden else "Labels: on"
    labels_style = {**_SMALL_BTN, "backgroundColor": "#6c757d" if is_hidden else "#adb5bd"}

    type_icon = _TYPE_ICONS.get(group["type"], "?")
    type_label = _TYPE_LABELS.get(group["type"], group["type"])

    # Scope badge only for time-based annotations (global/subplot distinction is
    # meaningless for points which are always subplot-specific).
    scope_badge = None
    if AnnotationType(group["type"]) in TIME_BASED_ANNOTATION_TYPES:
        scope_text = "Global" if group["is_global"] else "Subplot"
        scope_color = "#5a9fd4" if group["is_global"] else "#e67e00"
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
                id={"type": "group-toggle-btn", "id": group["id"]},
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
                    "color": group["color"],
                    "fontSize": "16px",
                    "fontWeight": "bold",
                    "minWidth": "16px",
                    "textAlign": "center",
                    "flexShrink": 0,
                },
            ),
            html.Span(
                group["name"],
                style={"fontWeight": "bold", "fontSize": "13px", "flex": 1, "color": "#333"},
            ),
            html.Span(
                type_label,
                style={"color": "#888", "fontSize": "11px", "flexShrink": 0},
            ),
            *([scope_badge] if scope_badge else []),
            html.Span(
                f"({annotation_count})",
                style={"color": "#888", "fontSize": "12px", "flexShrink": 0},
            ),
            html.Button(
                "▶ Continue",
                id={"type": "group-continue-btn", "id": group["id"]},
                n_clicks=0,
                style=_SMALL_BTN,
            ),
            html.Button(
                labels_label,
                id={"type": "group-hide-btn", "id": group["id"]},
                n_clicks=0,
                style=labels_style,
            ),
            html.Button(
                "Delete all",
                id={"type": "group-delete-btn", "id": group["id"]},
                n_clicks=0,
                style={**_SMALL_BTN, "backgroundColor": "#dc3545"},
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
) -> tuple[list | html.Div, str]:
    """Rebuild the annotation list, always sorted by group with collapsible group sections."""
    annotations = [
        Annotation.from_dict(annotation_dict) for annotation_dict in (annotations_raw or [])
    ]
    if not annotations:
        return [], ""

    expanded_set = set(expanded_groups or [])

    # Derive group metadata from the annotations themselves.
    # is_global is encoded as subplot_name is None on the first annotation in the group.
    groups_by_id: dict[str, dict] = {}
    for annotation in annotations:
        if annotation.group_id and annotation.group_id not in groups_by_id:
            groups_by_id[annotation.group_id] = {
                "id": annotation.group_id,
                "name": annotation.group_name or "",
                "color": annotation.color,
                "type": annotation.type.value,
                "is_global": annotation.subplot_name is None,
            }

    # Bucket annotations: grouped (preserve creation order within group) + ungrouped
    grouped: dict[str, list[Annotation]] = {}
    ungrouped: list[Annotation] = []
    group_order: list[str] = []  # first-seen order of group IDs

    for annotation in annotations:
        if annotation.group_id and annotation.group_id in groups_by_id:
            if annotation.group_id not in grouped:
                grouped[annotation.group_id] = []
                group_order.append(annotation.group_id)
            grouped[annotation.group_id].append(annotation)
        else:
            ungrouped.append(annotation)

    rows: list = []

    for group_id in group_order:
        group = groups_by_id[group_id]
        group_annotations = grouped[group_id]
        is_expanded = group_id in expanded_set
        is_hidden = bool(group_annotations) and all(
            annotation.label_hidden for annotation in group_annotations
        )

        rows.append(_group_header_row(group, len(group_annotations), is_expanded, is_hidden))

        if is_expanded:
            rows.extend(
                _annotation_list_row(
                    annotation, group_name=group["name"], display_tz=display_timezone
                )
                for annotation in group_annotations
            )

    if ungrouped:
        if group_order:
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

    count_text = f"{len(annotations)} annotation{'s' if len(annotations) != 1 else ''}"
    panel = html.Div(
        [
            html.Div(
                "Annotations",
                style={
                    "fontWeight": "bold",
                    "fontSize": "13px",
                    "color": "#555",
                    "marginBottom": "4px",
                    "borderBottom": "1px solid #dee2e6",
                    "paddingBottom": "4px",
                },
            ),
            *rows,
        ],
        style={
            "border": "1px solid #dee2e6",
            "borderRadius": "6px",
            "padding": "8px 12px",
            "backgroundColor": "#fff",
            "marginBottom": "12px",
            "maxHeight": "300px",
            "overflowY": "auto",
        },
    )
    return panel, count_text


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
    Input({"type": "group-hide-btn", "id": ALL}, "n_clicks"),
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
    annotations = [
        Annotation.from_dict(annotation_dict) for annotation_dict in (annotations_raw or [])
    ]
    group_annotations = [
        annotation for annotation in annotations if annotation.group_id == group_id
    ]
    target_hidden = any(not annotation.label_hidden for annotation in group_annotations)
    return [
        {**annotation_dict, "label_hidden": target_hidden}
        if annotation_dict.get("group_id") == group_id
        else annotation_dict
        for annotation_dict in (annotations_raw or [])
    ]


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
    new_annotations = [
        annotation_dict
        for annotation_dict in (annotations_raw or [])
        if annotation_dict.get("group_id") != group_id
    ]
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
        annotations = [
            Annotation.from_dict(annotation_dict) for annotation_dict in (annotations_raw or [])
        ]
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
    except Exception:  # noqa: BLE001
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
    return [
        annotation_dict
        for annotation_dict in (annotations_raw or [])
        if annotation_dict["id"] != annotation_id
    ]


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
        color = color or ANNOTATION_COLORS[0]
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
    reference_annotation = next(
        (
            annotation_dict
            for annotation_dict in (annotations_raw or [])
            if annotation_dict.get("group_id") == group_id
        ),
        None,
    )
    if not reference_annotation:
        raise PreventUpdate
    group_name = reference_annotation.get("group_name", "")
    group_color = reference_annotation.get("color", ANNOTATION_COLORS[0])
    group_type = AnnotationType(reference_annotation["type"])
    group_is_global = reference_annotation.get("subplot_name") is None
    new_mode = {
        **(mode or default_mode()),
        "active": True,
        "type": group_type.value,
        "group_id": group_id,
        "group_name": group_name,
        "group_color": group_color,
        "group_is_global": group_is_global,
        "pending_x0": None,
        "pending_plot_name": None,
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
    return [
        {**annotation_dict, "label_hidden": not annotation_dict.get("label_hidden", False)}
        if annotation_dict["id"] == annotation_id
        else annotation_dict
        for annotation_dict in (annotations_raw or [])
    ]
