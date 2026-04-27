"""
Annotation callbacks for the Dash application.

Implements the full annotation creation / rendering / persistence flow:

 1. toggle_annotation_mode   — activate an annotation type or deactivate mode (toggle + deactivate
                               share one @callback)
 2. handle_graph_click       — interpret graph clicks in annotation mode
 3. update_modal_ui          — populate the modal's dynamic fields (position, global checkbox)
 4. toggle_global_checkbox_visibility — hide the global checkbox for POINT annotations
 5. pick_color_swatch        — select a preset colour in the modal
 6. create_annotation        — confirm creation and append to the store
 7. cancel_annotation        — cancel and discard any pending time-window first click
 8. render_annotations       — Patch all graphs whenever the store or pending state changes
 9. update_annotation_list   — rebuild the sidebar list of annotations
10. save_annotations_cb      — write annotations.json to the patient folder
11. auto_load_annotations    — load annotations.json when a new folder is visualised
12. delete_annotation        — remove one annotation by ID
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import pandas as pd
from dash import ALL, Input, Output, Patch, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer.dash_api.annotations.io import load_annotations, save_annotations
from clinical_data_visualizer.dash_api.annotations.model import (
    ANNOTATION_COLORS,
    TIME_BASED_ANNOTATION_TYPES,
    Annotation,
    AnnotationType,
)
from clinical_data_visualizer.dash_api.annotations.renderer import build_figure_overlays
from clinical_data_visualizer.dash_api.styles import (
    ANNOTATION_LIST_ROW,
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_MODAL_STYLE_SHOWN,
    ANNOTATION_TOOLBAR_STYLE,
    BUTTON_ANNOTATION_ACTIVE,
    BUTTON_ANNOTATION_INACTIVE,
    BUTTON_ANNOTATION_SAVE,
    BUTTON_MODAL_CLOSE,
)

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


def _default_mode() -> dict:
    return {
        "active": False,
        "type": AnnotationType.TIME_EVENT.value,
        "pending_x0": None,
        "pending_plot_name": None,
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


def _format_position(modal_data: dict) -> str:
    ann_type = modal_data.get("type", "")
    if ann_type == AnnotationType.TIME_EVENT.value:
        return f"At: {modal_data.get('x', '')}"
    if ann_type == AnnotationType.TIME_WINDOW.value:
        return f"From: {modal_data.get('x0', '')}  →  {modal_data.get('x1', '')}"
    if ann_type == AnnotationType.POINT.value:
        x = modal_data.get("x", "")
        y = modal_data.get("y")
        t = modal_data.get("t")
        if y is None:
            pos = f"At: x={x}"
        else:
            pos = f"At: x={x}  y={y:.4g}" if isinstance(y, float) else f"At: x={x}  y={y}"
        if t:
            pos += f"  t={t}"
        return pos
    return ""


def _annotation_list_row(ann: Annotation) -> html.Div:
    type_label = _TYPE_LABELS.get(ann.type.value, ann.type.value)
    icon = _TYPE_ICONS.get(ann.type.value, "?")
    display_label = ann.label or f"({type_label})"
    return html.Div(
        [
            html.Span(
                icon,
                style={
                    "color": ann.color,
                    "fontSize": "16px",
                    "fontWeight": "bold",
                    "minWidth": "16px",
                    "textAlign": "center",
                },
            ),
            html.Span(
                display_label,
                style={"flex": 1, "overflow": "hidden", "textOverflow": "ellipsis"},
            ),
            html.Span(
                type_label,
                style={"color": "#888", "fontSize": "11px", "marginRight": "6px"},
            ),
            html.Button(
                "×",  # noqa: RUF001
                id={"type": "annotation-delete-btn", "id": ann.id},
                n_clicks=0,
                style={
                    **BUTTON_MODAL_CLOSE,
                    "padding": "1px 7px",
                    "fontSize": "14px",
                    "lineHeight": "1.2",
                    "backgroundColor": "#dc3545",
                },
            ),
        ],
        style=ANNOTATION_LIST_ROW,
    )


# ---------------------------------------------------------------------------
# 1 & 2. Annotation mode toggle / deactivate
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-type-btn-time_event", "style"),
    Output("annotation-type-btn-time_window", "style"),
    Output("annotation-type-btn-point", "style"),
    Output("annotation-mode-deactivate", "style"),
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
) -> tuple[dict, dict, dict, dict, dict]:
    """Activate an annotation type or deactivate mode entirely."""
    mode = mode or _default_mode()
    triggered = ctx.triggered_id

    if triggered == "annotation-mode-deactivate":
        new_mode = {**mode, "active": False, "pending_x0": None, "pending_plot_name": None}
    else:
        btn_to_type = {
            "annotation-type-btn-time_event": AnnotationType.TIME_EVENT.value,
            "annotation-type-btn-time_window": AnnotationType.TIME_WINDOW.value,
            "annotation-type-btn-point": AnnotationType.POINT.value,
        }
        ann_type = btn_to_type.get(triggered, mode.get("type", AnnotationType.TIME_EVENT.value))
        # If clicking the already-active type, toggle off; otherwise activate
        if mode.get("active") and mode.get("type") == ann_type:
            new_mode = {**mode, "active": False, "pending_x0": None, "pending_plot_name": None}
        else:
            new_mode = {**mode, "active": True, "type": ann_type}

    active = new_mode["active"]
    active_type = new_mode["type"]

    def _btn_style(ann_type_value: str) -> dict:
        if active and active_type == ann_type_value:
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
    )


# ---------------------------------------------------------------------------
# 3. Graph click handler
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-mode-store", "data", allow_duplicate=True),
    Output("annotation-modal-data", "data"),
    Output("annotation-modal", "style"),
    Output({"type": "graph", "name": ALL}, "figure", allow_duplicate=True),
    Output("annotation-warning-msg", "children"),
    Input({"type": "graph", "name": ALL}, "clickData"),
    State("annotation-mode-store", "data"),
    State({"type": "graph-subplots", "name": ALL}, "data"),
    State({"type": "graph-trace-map", "name": ALL}, "data"),
    State({"type": "graph", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def handle_graph_click(
    click_data_list: list,
    mode: dict,
    subplots_list: list,
    trace_map_list: list,
    graph_ids: list,
) -> tuple[dict, dict, dict, list, str]:
    """React to a graph click when annotation mode is active."""
    mode = mode or _default_mode()
    if not mode.get("active"):
        raise PreventUpdate

    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate

    # Find which graph was clicked
    plot_name = triggered_id["name"]
    graph_names = [gid["name"] for gid in graph_ids]
    try:
        graph_idx = graph_names.index(plot_name)
    except ValueError as v:
        raise PreventUpdate from v

    click_data = click_data_list[graph_idx]
    if not click_data or not click_data.get("points"):
        raise PreventUpdate

    point = click_data["points"][0]
    x_val = point.get("x")
    y_val = point.get("y")
    curve_num = point.get("curveNumber", 0)

    # Look up axis references and signal metadata for this trace
    trace_map = trace_map_list[graph_idx] or {}
    trace_info = trace_map.get(f"curve_{curve_num}", {"xaxis": "x", "yaxis": "y"})
    xaxis_ref = trace_info.get("xaxis", "x")
    yaxis_ref = trace_info.get("yaxis", "y")
    trace_metadata = {
        k: v
        for k, v in {
            "datasource_name": trace_info.get("datasource_name"),
            "raw_name": trace_info.get("raw_name"),
            "display_name": trace_info.get("display_name"),
        }.items()
        if v
    }

    # Subplot metadata
    subplots_data = subplots_list[graph_idx] or {}
    display_tz = subplots_data.get("display_timezone", cst.DISPLAY_TIMEZONE)
    n_cols = subplots_data.get("n_cols", 1)

    ann_type = mode.get("type", AnnotationType.TIME_EVENT.value)
    no_update_patches = [no_update] * len(graph_ids)

    # --- Validation: prevent time-based annotations on loop plots ---
    # TIME_BASED_ANNOTATION_TYPES is defined in model.py as the authoritative source.
    is_loop = subplots_data.get("plot_type") == cst.PlotType.LOOP
    if is_loop and ann_type in TIME_BASED_ANNOTATION_TYPES:
        logger.warning(
            "User attempted to create %s annotation on a loop plot. "
            "Loop plots have non-time x-axes, so only Point annotations are valid.",
            ann_type,
        )
        return (
            mode,
            no_update,
            ANNOTATION_MODAL_STYLE_HIDDEN,
            no_update_patches,
            "⚠ Time-based annotations are not supported on loop plots — switch to Point.",
        )

    # Loop plot x-axes are numeric (e.g. volume) — skip timestamp localization to avoid
    # pd.Timestamp silently converting a float to a near-epoch datetime string.
    x_str = str(x_val) if is_loop else _localize_x_val(str(x_val), display_tz)

    # Compute the subplot row from the clicked trace's y-axis.
    # Used for all annotation types when the user unchecks the "global" checkbox.
    axis_idx = _parse_yaxis_idx(yaxis_ref)
    auto_subplot_row = (axis_idx - 1) // n_cols + 1

    # --- Time Window: two-click flow ---
    if ann_type == AnnotationType.TIME_WINDOW.value:
        pending_x0 = mode.get("pending_x0")
        pending_plot = mode.get("pending_plot_name")

        if pending_x0 is None or pending_plot != plot_name:
            # First click — store x0 (tz-aware); render_annotations draws the preview.
            new_mode = {
                **mode,
                "pending_x0": x_str,
                "pending_plot_name": plot_name,
            }
            return new_mode, no_update, ANNOTATION_MODAL_STYLE_HIDDEN, no_update_patches, ""

        # Second click — open modal with x0 + x1
        modal_data: dict[str, Any] = {
            "type": ann_type,
            "plot_name": plot_name,
            "x0": pending_x0,
            "x1": x_str,
            "xaxis": xaxis_ref,
            "auto_subplot_row": auto_subplot_row,
        }
        if trace_metadata:
            modal_data["trace_metadata"] = trace_metadata
        new_mode = {**mode, "pending_x0": None, "pending_plot_name": None}
        return new_mode, modal_data, ANNOTATION_MODAL_STYLE_SHOWN, no_update_patches, ""

    # --- Time Event / Point: single click → open modal ---
    modal_data = {
        "type": ann_type,
        "plot_name": plot_name,
        "x": x_str,
        "xaxis": xaxis_ref,
        "auto_subplot_row": auto_subplot_row,
    }
    if ann_type == AnnotationType.POINT.value:
        modal_data["y"] = y_val
        modal_data["yaxis"] = yaxis_ref
        # Loop plots embed per-point timestamps in customdata (UTC epoch → DISPLAY_TIMEZONE
        # string, produced by helper.loop_time_to_display_strings).  Parse back to an ISO
        # string so the timing survives the JSON round-trip with its timezone preserved.
        if is_loop:
            raw_t = point.get("customdata")
            if raw_t:
                with contextlib.suppress(Exception):
                    modal_data["t"] = (
                        pd.Timestamp(str(raw_t)).tz_localize(cst.DISPLAY_TIMEZONE).isoformat()
                    )
    if trace_metadata:
        modal_data["trace_metadata"] = trace_metadata

    return mode, modal_data, ANNOTATION_MODAL_STYLE_SHOWN, no_update_patches, ""


# ---------------------------------------------------------------------------
# 4. Populate modal UI from modal-data store
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-modal-position-display", "children"),
    Output("annotation-label-input", "value"),
    Output("annotation-global-checkbox", "value"),
    Input("annotation-modal-data", "data"),
    prevent_initial_call=True,
)
def update_modal_ui(modal_data: dict) -> tuple[str, str, list]:
    """Refresh position text and global checkbox when modal data changes."""
    if not modal_data:
        raise PreventUpdate
    position_text = _format_position(modal_data)
    ann_type = modal_data.get("type", "")
    # POINT → unchecked (subplot-specific); all others → checked (global)
    is_global = ann_type != AnnotationType.POINT.value
    checkbox_value = ["global"] if is_global else []
    return position_text, "", checkbox_value


# ---------------------------------------------------------------------------
# 4b. Toggle global checkbox visibility based on annotation type
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
    ann_type = modal_data.get("type", "")
    # Hide for POINT annotations, show for TIME_EVENT and TIME_WINDOW
    if ann_type == AnnotationType.POINT.value:
        return {"marginBottom": "20px", "display": "none"}
    return {"marginBottom": "20px"}


# ---------------------------------------------------------------------------
# 5. Colour swatch picker
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-color-input", "value"),
    Output({"type": "annotation-color-swatch", "color": ALL}, "style"),
    Input({"type": "annotation-color-swatch", "color": ALL}, "n_clicks"),
    State({"type": "annotation-color-swatch", "color": ALL}, "id"),
    prevent_initial_call=True,
)
def pick_color_swatch(_n_clicks_list: list, swatch_ids: list) -> tuple[str, list]:
    """Highlight the selected colour swatch and update the hex input."""
    triggered_id = ctx.triggered_id
    if triggered_id is None:
        raise PreventUpdate
    selected_color = triggered_id["color"]
    styles = []
    for sid in swatch_ids:
        c = sid["color"]
        border = "3px solid #333" if c == selected_color else "2px solid transparent"
        styles.append(
            {
                "width": "22px",
                "height": "22px",
                "borderRadius": "50%",
                "backgroundColor": c,
                "cursor": "pointer",
                "border": border,
                "flexShrink": 0,
            }
        )
    return selected_color, styles


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
    # Fast double-click would fire this callback twice with the same modal_data,
    # creating duplicate annotations. Acceptable for now; deduplication would
    # require either disabling the button on first click or a store-level ID check.
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

    ann_type = AnnotationType(modal_data["type"])
    subplot_row = (
        None if "global" in (global_checkbox or []) else int(modal_data.get("auto_subplot_row", 1))
    )
    color = color or ANNOTATION_COLORS[0]

    if ann_type == AnnotationType.TIME_EVENT:
        data = {"x": modal_data["x"], "xaxis": modal_data.get("xaxis", "x")}
    elif ann_type == AnnotationType.TIME_WINDOW:
        data = {
            "x0": modal_data["x0"],
            "x1": modal_data["x1"],
            "xaxis": modal_data.get("xaxis", "x"),
        }
    elif ann_type == AnnotationType.POINT:
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

    ann = Annotation(
        type=ann_type,
        plot_name=modal_data["plot_name"],
        label=label or "",
        color=color,
        subplot_row=subplot_row,
        data=data,
        trace_metadata=modal_data.get("trace_metadata"),
    )

    new_annotations = [*(annotations_raw or []), ann.to_dict()]
    new_mode = {**(mode or _default_mode()), "pending_x0": None, "pending_plot_name": None}
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
    new_mode = {**(mode or _default_mode()), "pending_x0": None, "pending_plot_name": None}
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
    prevent_initial_call=True,
)
def render_annotations(
    annotations_raw: list,
    mode: dict,
    graph_ids: list,
    subplots_list: list,
) -> list:
    """Rebuild layout.shapes and layout.annotations for every visible graph using Patch()."""
    if not graph_ids:
        raise PreventUpdate

    annotations = [Annotation.from_dict(d) for d in (annotations_raw or [])]
    mode = mode or _default_mode()
    pending_x0 = mode.get("pending_x0")
    pending_plot = mode.get("pending_plot_name")
    point_mode_active = mode.get("active") and mode.get("type") == AnnotationType.POINT.value

    # Build lookup: plot_name → subplot data
    subplot_map = {gid["name"]: (subplots_list[i] or {}) for i, gid in enumerate(graph_ids)}

    patches = []
    for gid in graph_ids:
        plot_name = gid["name"]
        subplots_data = subplot_map.get(plot_name, {})
        subplot_title_annotations = subplots_data.get("subplot_annotations", [])
        is_loop = subplots_data.get("plot_type") == cst.PlotType.LOOP

        graph_pending_x0 = pending_x0 if pending_plot == plot_name else None
        n_cols = subplots_data.get("n_cols", 1)

        shapes, all_annotations = build_figure_overlays(
            annotations=annotations,
            plot_name=plot_name,
            subplot_annotations=subplot_title_annotations,
            pending_x0=graph_pending_x0,
            n_cols=n_cols,
        )

        p = Patch()
        p.layout.shapes = shapes
        p.layout.annotations = all_annotations
        # Switch time-series hover to "closest" in POINT mode so the cursor
        # snaps to the nearest trace; restore "x unified" otherwise.
        if not is_loop:
            p.layout.hovermode = "closest" if point_mode_active else "x unified"
        patches.append(p)

    return patches


# ---------------------------------------------------------------------------
# 9. Update annotation list panel
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-list-panel", "children"),
    Output("annotation-count-badge", "children"),
    Input("annotation-store", "data"),
    prevent_initial_call=False,  # must initialise the badge/list even with an empty store
)
def update_annotation_list(annotations_raw: list) -> tuple[list | html.Div, str]:
    """Rebuild the sidebar list from the current annotation store."""
    annotations = [Annotation.from_dict(d) for d in (annotations_raw or [])]
    if not annotations:
        return [], ""

    rows = [_annotation_list_row(ann) for ann in annotations]
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
        },
    )
    return panel, count_text


# ---------------------------------------------------------------------------
# 10. Save annotations to patient folder
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-save-status", "children", allow_duplicate=True),
    Output("annotation-save-btn", "style", allow_duplicate=True),
    Input("annotation-save-btn", "n_clicks"),
    State("annotation-store", "data"),
    State("folder-visu-path", "data"),
    prevent_initial_call=True,
)
def save_annotations_cb(_n: int, annotations_raw: list, folder: str) -> tuple[str, dict]:
    """Write annotations.json to the patient data folder."""
    if not folder:
        return "No patient folder loaded.", BUTTON_ANNOTATION_SAVE
    try:
        annotations = [Annotation.from_dict(d) for d in (annotations_raw or [])]
        save_annotations(annotations, folder)
        return f"Saved ({len(annotations)})", {
            **BUTTON_ANNOTATION_SAVE,
            "backgroundColor": "#28a745",
        }
    except Exception:
        logger.exception("Failed to save annotations")
        return "Save failed.", {**BUTTON_ANNOTATION_SAVE, "backgroundColor": "#dc3545"}


@callback(
    Output("annotation-save-status", "children", allow_duplicate=True),
    Output("annotation-save-btn", "style", allow_duplicate=True),
    Input("annotation-store", "data"),
    prevent_initial_call=True,
)
def reset_save_status_on_store_change(_data: list) -> tuple[str, dict]:
    """Reset save button to neutral so the next save always shows a fresh colour."""
    return "", BUTTON_ANNOTATION_SAVE


# ---------------------------------------------------------------------------
# 11. Auto-load annotations when a new patient folder is visualised
# ---------------------------------------------------------------------------


@callback(
    Output("annotation-store", "data", allow_duplicate=True),
    Output("annotation-toolbar", "style"),
    Input("folder-visu-path", "data"),
    prevent_initial_call=True,
)
def auto_load_annotations(folder: str) -> tuple[list, dict]:
    """Load annotations.json from the patient folder after visualisation."""
    toolbar_shown = {**ANNOTATION_TOOLBAR_STYLE, "display": "flex"}

    if not folder:
        return [], {**ANNOTATION_TOOLBAR_STYLE, "display": "none"}

    try:
        annotations = load_annotations(folder)
    except Exception:  # noqa: BLE001
        logger.warning("Unexpected error loading annotations from %s", folder, exc_info=True)
        annotations = []

    return [a.to_dict() for a in annotations], toolbar_shown


# ---------------------------------------------------------------------------
# 12. Delete one annotation by ID
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
    ann_id = triggered_id["id"]
    return [d for d in (annotations_raw or []) if d["id"] != ann_id]
