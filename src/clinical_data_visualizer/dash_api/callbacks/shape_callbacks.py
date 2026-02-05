"""
Shape-related callbacks for Dash API visualization.

Contains callbacks for shape management, annotation persistence,
and shape editing modal.
"""

import json
import logging
from pathlib import Path

from dash import (
    ALL,
    MATCH,
    Input,
    Output,
    Patch,
    State,
    callback,
    callback_context,
    exceptions,
    html,
    no_update,
)

from clinical_data_visualizer.dash_api import datetime_utils, shape_manager, ui_components
from clinical_data_visualizer.dash_api.helper_api import is_user_annotation

# Style constant for the shape edit popup modal
EDIT_SHAPE_POPUP_STYLE = {
    "display": "none",
    "position": "fixed",
    "top": "30%",
    "left": "70%",
    "transform": "translate(-50%, -50%)",
    "zIndex": 1000,
    "background": "white",
    "padding": "16px",
    "borderRadius": "8px",
    "boxShadow": "0 4px 12px rgba(0,0,0,0.15)",
}

logger = logging.getLogger(__name__)


@callback(
    Output("annotations-store", "data", allow_duplicate=True),
    Input({"type": "graph", "name": ALL}, "relayoutData"),
    State({"type": "graph", "name": ALL}, "figure"),
    State({"type": "graph", "name": ALL}, "id"),
    State("annotations-store", "data"),
    prevent_initial_call=True,
)
def sync_plotly_annotations(relayout_list, figures, graph_ids, store):
    """Sync Plotly annotations from figures to store."""
    if not relayout_list:
        return no_update

    store = store or {"by_figure": {}}

    for relayout, fig, gid in zip(relayout_list, figures, graph_ids):
        if not relayout:
            continue

        fig_name = gid["name"]
        store["by_figure"].setdefault(fig_name, {})
        layout = fig.get("layout", {})

        layout_annotations = layout.get("annotations", [])
        user_annotations = [ann for ann in layout_annotations if is_user_annotation(ann)]
        store["by_figure"][fig_name]["annotations"] = user_annotations

        store["by_figure"][fig_name]["shapes"] = layout.get("shapes", [])

    return store


@callback(
    Output({"type": "graph", "name": MATCH}, "figure", allow_duplicate=True),
    Input({"type": "graph", "name": MATCH}, "relayoutData"),
    State({"type": "graph", "name": MATCH}, "figure"),
    State({"type": "graph", "name": MATCH}, "id"),
    prevent_initial_call=True,
)
def lock_and_style_shapes(relayout, fig, gid):
    """Lock newly drawn shapes and apply styling."""
    if not relayout or "shapes" not in fig.get("layout", {}):
        raise exceptions.PreventUpdate

    patch = Patch()
    shapes = fig["layout"]["shapes"]

    for idx, s in enumerate(shapes):
        logger.debug(s)
        if not s.get("editable", True):
            continue

        patch["layout"]["shapes"][idx]["editable"] = False

        shape_type = s.get("type", "rect")

        # Line shapes - force vertical
        if shape_type == "line":
            x0, x1 = s.get("x0"), s.get("x1")
            if x0 != x1:
                try:
                    dt0 = datetime_utils.parse_datetime(x0) if isinstance(x0, str) else x0
                    dt1 = datetime_utils.parse_datetime(x1) if isinstance(x1, str) else x1
                    midpoint = dt0 + (dt1 - dt0) / 2
                    patch["layout"]["shapes"][idx]["x0"] = datetime_utils.format_datetime(midpoint)
                    patch["layout"]["shapes"][idx]["x1"] = datetime_utils.format_datetime(midpoint)
                except Exception:
                    pass

    return patch


@callback(
    Output("annotations-store", "data", allow_duplicate=True),
    Input({"type": "graph", "name": ALL}, "figure"),
    State({"type": "graph", "name": ALL}, "id"),
    State("annotations-store", "data"),
    prevent_initial_call=True,
)
def persist_shapes(figures, ids, store):
    """Persist shapes from figures to annotations store."""
    store = store.copy() if store else {"by_figure": {}}

    for fig, gid in zip(figures, ids):
        fig_name = gid["name"]
        shapes = fig.get("layout", {}).get("shapes", [])

        if store["by_figure"].get(fig_name, {}).get("shapes") != shapes:
            store["by_figure"].setdefault(fig_name, {})
            store["by_figure"][fig_name]["shapes"] = shapes

    return store


@callback(
    Input("annotations-store", "data"),
    State("folder-visu-path", "data"),
    prevent_initial_call=True,
)
def save_annotations_and_shapes(store, folder_visu_path):
    """Save annotations and shapes to JSON file."""
    if folder_visu_path:
        path = Path(folder_visu_path) / "annotations.json"
        with path.open("w") as f:
            json.dump(store, f, indent=2, default=str)

    return


@callback(Output("shape-selector", "options"), Input("annotations-store", "data"))
def update_shape_options(store):
    """Update shape selector dropdown options."""
    if not store or "by_figure" not in store:
        return []

    options = []

    for fig_name, fig_data in store["by_figure"].items():
        for i, shape in enumerate(fig_data.get("shapes", [])):
            if shape is None:
                continue

            display_label, value, color = shape_manager.build_shape_option_label(
                fig_name, shape, i
            )
            square_color = ui_components.parse_color(color)

            label = html.Span(
                [
                    html.Span("■", style={"color": square_color, "margin-right": "6px"}),
                    display_label,
                ]
            )

            options.append({"label": label, "value": value})

    return options


@callback(
    Output("shape-edit-popup", "style"),
    Output("shape-name-input", "value"),
    Output("shape-global-input", "value"),
    Output("shape-color-input", "value"),
    Input("modify-button", "n_clicks"),
    Input("delete-button", "n_clicks"),
    Input("shape-save-button", "n_clicks"),
    Input("shape-cancel-button", "n_clicks"),
    State("shape-selector", "value"),
    State("annotations-store", "data"),
    prevent_initial_call=True,
)
def toggle_modal(modify_clicks, delete_clicks, save_clicks, cancel_clicks, selected_value, store):
    """Toggle the shape edit modal and populate fields."""
    triggered = callback_context.triggered_id

    hidden_style = {**EDIT_SHAPE_POPUP_STYLE, "display": "none"}

    if not selected_value or not store:
        return hidden_style, no_update, no_update, no_update

    if triggered != "modify-button":
        return hidden_style, no_update, no_update, no_update

    parsed = shape_manager.parse_shape_selector_value(selected_value)
    if not parsed:
        return hidden_style, no_update, no_update, no_update

    fig_name, shape_idx = parsed
    shape = shape_manager.get_shape_from_store(store, fig_name, shape_idx)
    if not shape:
        return hidden_style, no_update, no_update, no_update

    # Extract shape properties
    props = shape_manager.extract_shape_properties(shape)

    # Prefill values
    global_value = ["global"] if props["is_global"] else []
    color_value = shape_manager.parse_rgba_color(props["color"]) or no_update

    return (
        {**EDIT_SHAPE_POPUP_STYLE, "display": "block"},
        props["name"],
        global_value,
        color_value,
    )


@callback(
    Output({"type": "graph", "name": MATCH}, "figure"),
    Input("shape-save-button", "n_clicks"),
    Input("delete-button", "n_clicks"),
    State("shape-selector", "value"),
    State("shape-name-input", "value"),
    State("shape-color-input", "value"),
    State("shape-global-input", "value"),
    State({"type": "graph", "name": MATCH}, "figure"),
    prevent_initial_call=True,
)
def modify_shape(
    n_clicks_save,
    n_clicks_delete,
    selected_value,
    new_name,
    new_color,
    global_value,
    fig,
):
    """Modify or delete a shape based on user action."""
    ctx = callback_context
    triggered_props = ctx.triggered_prop_ids
    logger.debug(f"ctx.outputs_list: {ctx.outputs_list}")
    current_fig_name = (ctx.outputs_list).get("id", {}).get("name")

    # Guard 1 - Only react to Save or Delete explicitly
    if not any(
        prop in triggered_props
        for prop in (
            "shape-save-button.n_clicks",
            "delete-button.n_clicks",
        )
    ):
        logger.debug(
            f"triggered_props: {triggered_props}. Stopped running modify_shape due to guard 1"
        )
        return Patch()

    # Guard 2 - Selection must exist
    parsed = shape_manager.parse_shape_selector_value(selected_value)
    if not parsed:
        logger.debug(f"selected_value empty or invalid: {selected_value}")
        return Patch()

    selected_fig_name, shape_idx = parsed

    # Guard 3 - selected fig must be the correct one
    if selected_fig_name != current_fig_name:
        return Patch()

    # Guard 4 - Figure and shapes must be ready
    shapes = fig.get("layout", {}).get("shapes", [])

    if not shapes or shape_idx >= len(shapes):
        logger.debug(
            f"shapes object too small: shape_idx: {shape_idx}, shapes:{shapes}. "
            "Might be a bug. might be the callback firing too early, see if the feature seems buggy"
        )
        return Patch()

    patch = Patch()

    # DELETE
    if "delete-button.n_clicks" in triggered_props:
        logger.info("Deleting shape")
        patch["layout"]["shapes"] = shapes[:shape_idx] + shapes[shape_idx + 1 :]
        return patch

    # SAVE / MODIFY
    if "shape-save-button.n_clicks" in triggered_props:
        logger.info("Saving shape modifications")

        shape_patch = patch["layout"]["shapes"][shape_idx]
        original_shape = shapes[shape_idx]

        # Name
        if new_name:
            shape_patch["label"] = {"text": new_name}

        # Color + opacity
        rgba_str = shape_manager.build_rgba_string(new_color)
        if rgba_str:
            shape_type = original_shape.get("type", "rect")
            shape_patch["line"] = {"color": rgba_str, "width": 2}
            if shape_type in ("rect", "circle"):
                shape_patch["fillcolor"] = rgba_str

        # Global / local y-axis
        if global_value and "global" in global_value:
            shape_patch["yref"] = "paper"
            shape_patch["y0"] = 0
            shape_patch["y1"] = 1
        else:
            shape_patch["yref"] = original_shape.get("yref", "y")
            shape_patch["y0"] = original_shape.get("y0", 0)
            shape_patch["y1"] = original_shape.get("y1", 1)

        # Lock shape
        shape_patch["editable"] = False

        return patch

    return Patch()
