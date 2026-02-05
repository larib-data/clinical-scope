# === Imports === #
import base64
import json
import re
import webbrowser
from pathlib import Path

import dash_bootstrap_components as dbc
import dash_daq as daq
from dash import (
    ALL,
    MATCH,
    Dash,
    Input,
    Output,
    Patch,
    State,
    callback,
    callback_context,
    dcc,
    exceptions,
    html,
    no_update,
)
from clinical_data_visualizer import logger_config

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
from clinical_data_visualizer import wrapper
from clinical_data_visualizer.dash_api import (
    datetime_utils,
    ui_components,
    validation,
)
from clinical_data_visualizer.dash_api import (
    helper_api as ui_helper,
)
from clinical_data_visualizer.signal_container import PlotModel

# === Configure the logger and add new app run message === #
logs_path_root = logger_config.get_logs_path()
logs_path = logs_path_root / "app/dash_api.log"
logger = logger_config.setup_logging(logs_path, debug=True)
logger.info("========================================")
logger.info("New app run")
logger.info("========================================")


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

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)

app.layout = html.Div(
    [
        dcc.Store(id="folder-visu-path", data=""),
        dcc.Store(id="schema-registry", data={}),
        html.H2("Database Options"),
        dcc.Upload(
            id="db-options-upload",
            children=html.Button("Upload database_options.json"),
            multiple=False,
        ),
        html.Div(id="db-options-status"),
        dcc.Store(id="db-options-store"),
        html.Hr(),
        html.H2("Patient Options"),
        html.Div(id="patient-options-ui"),
        html.Button("Process visualization", id="process-button"),
        html.Div(id="validation-errors"),
        html.Div(id="process-status"),
        html.Div(id="process-status-annotation"),
        dcc.Dropdown(
            id="shape-selector",
            options=[],  # dynamically populated from store
            value=None,
            clearable=False,
        ),
        html.Button("Modify", id="modify-button"),
        html.Button("Delete", id="delete-button"),
        # Modal (initially hidden)
        html.Div(
            id="shape-edit-popup",
            style=EDIT_SHAPE_POPUP_STYLE,
            children=[
                html.Div(
                    [
                        html.H4("Edit Shape", style={"margin-bottom": "20px"}),
                        # Main row: left & right
                        html.Div(
                            [
                                # Left column: name + checkbox
                                html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.Label("Name:"),
                                                dcc.Input(
                                                    id="shape-name-input",
                                                    placeholder="New Shape name",
                                                    style={"width": "100%"},
                                                ),
                                            ],
                                            style={"margin-bottom": "15px"},
                                        ),
                                        html.Div(
                                            [
                                                html.Label("Global (full y-axis):"),
                                                dcc.Checklist(
                                                    id="shape-global-input",
                                                    options=[
                                                        {"label": "Global", "value": "global"}
                                                    ],
                                                    value=[],
                                                ),
                                            ],
                                            style={"margin-bottom": "0px"},
                                        ),
                                    ],
                                    style={
                                        "flex": "1",
                                        "display": "flex",
                                        "flexDirection": "column",
                                    },
                                ),
                                # Right column: color picker
                                html.Div(
                                    [
                                        html.Label("Color:"),
                                        daq.ColorPicker(
                                            id="shape-color-input",
                                            value={
                                                "hex": "#ff0000",
                                                "rgb": {"r": 255, "g": 0, "b": 0, "a": 0.5},
                                            },
                                            size=120,
                                        ),
                                    ],
                                    style={
                                        "flex": "1",
                                        "display": "flex",
                                        "flexDirection": "column",
                                        "alignItems": "center",
                                    },
                                ),
                            ],
                            style={"display": "flex", "gap": "20px"},
                        ),  # gap between columns
                        # Buttons row
                        html.Div(
                            [
                                html.Button("Save", id="shape-save-button"),
                                html.Button("Cancel", id="shape-cancel-button"),
                            ],
                            style={"margin-top": "20px", "textAlign": "left"},
                        ),
                    ],
                    style={
                        "background": "white",
                        "padding": "20px",
                        "border-radius": "10px",
                        "width": "500px",
                        "max-width": "90vw",
                    },
                )
            ],
        ),
        html.Hr(),
        html.Div(id="visualization-container"),
        dcc.Store(id="annotations-store", data={}),
    ]
)


@callback(
    Output("db-options-store", "data"),
    Output("db-options-status", "children"),
    Input("db-options-upload", "contents"),
    State("db-options-upload", "filename"),
    prevent_initial_call=True,
)
def load_db_options(contents, filename):
    try:
        if not contents:
            return None, None

        _, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)

        if not filename.endswith(".json"):
            raise ValueError("Invalid file type")

        database_options_dict = json.loads(decoded.decode("utf-8"))
        logger.debug("loaded database_options_dict: %r", database_options_dict)

        return (
            database_options_dict,
            html.Div(
                f"Successfully loaded {filename}", style={"color": "green", "fontWeight": "bold"}
            ),
        )

    except Exception as e:
        logger.exception("Failed to load database options: ")
        return (
            None,
            html.Div(f"Error loading file: {e!s}", style={"color": "red", "fontWeight": "bold"}),
        )


@callback(
    Output("patient-options-ui", "children"),
    Output("schema-registry", "data"),
    Input("db-options-store", "data"),
    prevent_initial_call=True,
)
def build_patient_options_ui(database_options):
    if not database_options:
        return None, {}

    components = []
    schema_lookup = {}

    # Global options
    components.append(html.H3("Global Patient Options"))
    component, schema = ui_components.build_ui_and_schema_registry(
        cst.PatientOptions, prefix="global"
    )
    components.append(component)
    schema_lookup = schema_lookup | schema

    # Per-datasource options
    components.append(html.H3("Specific Options"))

    requested_data_sources = database_options.keys()
    for data_source in datasource.DataSource.AVAILABLE:
        if data_source.NAME not in requested_data_sources:
            continue

        components.append(html.H4(data_source.DESCRIPTION))
        component, schema = ui_components.build_ui_and_schema_registry(
            data_source.OPTIONS.PatientOptionsDataSourceRelative,
            prefix=f"specific.{data_source.NAME}",
        )
        components.append(component)
        schema_lookup = schema_lookup | schema

    schema_data = {k: v.__name__ for k, v in schema_lookup.items()}

    return components, schema_data


@callback(
    Output("visualization-container", "children"),
    Output("validation-errors", "children"),
    Output("process-status", "children"),
    Output("folder-visu-path", "data"),
    Input("process-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def process_visualization(n_clicks, db_options, schema_data, values, ids):
    if not db_options:
        return None, "Database options not loaded", None, None

    # Rehydrate schema classes from schema_data
    # schema_data = {component_id: class_name_as_string}
    SCHEMA_CLASS_LOOKUP = {}
    for k, v in schema_data.items():
        if k.startswith("global"):
            SCHEMA_CLASS_LOOKUP[k] = getattr(cst.PatientOptions, v)
        if k.startswith("specific"):
            parts = k.split(".")
            datasource_name = parts[1] if len(parts) > 1 else None
            datasource_class = datasource.DataSource.get_subclass_by_name(datasource_name)
            logger.debug(f"parts: {parts}")
            logger.debug(f"datasource_name: {datasource_name}")
            logger.debug(f"datasource_class: {datasource_class}")
            SCHEMA_CLASS_LOOKUP[k] = getattr(
                datasource_class.OPTIONS.PatientOptionsDataSourceRelative, v
            )

    # Map IDs to values
    logger.debug(f"ids: {ids}")
    logger.debug(f"values: {values}")
    values_by_id = {i["name"]: v for i, v in zip(ids, values)}

    # Validate
    validated_dict, errors = validation.validate_and_collect(values_by_id, SCHEMA_CLASS_LOOKUP)
    logger.debug(f"errors: {errors}")
    logger.debug(f"validated_dict: {validated_dict}")

    if errors:
        return None, html.Ul([html.Li(e) for e in errors]), None, None

    # Save JSON exactly as before
    patient_options_path = (
        Path(validated_dict["data_folder"]) / cst.FOLDER_NAME_VISU / "patient_options.json"
    )
    name_folder_visu = str(Path(validated_dict["data_folder"]) / cst.FOLDER_NAME_VISU)
    annotations_data = ui_helper.load_annotations(name_folder_visu)
    ui_helper.save_json(validated_dict, patient_options_path)

    try:
        model = wrapper.main(
            patient_options=validated_dict,
            database_options_global=db_options,
        )
        PlotModel.to_html(model, validated_dict)
        graphs = []

        for mod in model:
            fig = mod.figure

            # Default shapes / annotations
            stored = annotations_data.get("by_figure", {}).get(mod.name, {})
            fig.update_layout(
                annotations=stored.get("annotations", []),
                shapes=stored.get("shapes", []),
                uirevision=mod.name,  # preserve shapes across updates
            )

            # Determine dragmode per figure type
            default_dragmode = "drawline" if mod.name == "time_series" else "drawrect"

            fig.update_layout(
                dragmode=default_dragmode,
                newshape=dict(
                    fillcolor="rgba(0,255,0,0.25)",
                    line=dict(color="green", width=2),
                    layer="above",
                ),
            )

            graphs.append(
                dcc.Graph(
                    id={"type": "graph", "name": mod.name},
                    figure=fig,
                    config={
                        "displayModeBar": True,
                        "modeBarButtonsToAdd": [
                            "drawline",  # time point
                            "drawrect",  # time range
                            # "drawopenpath",  # existing freeform
                            # "eraseshape",
                        ],
                    },
                    style={"marginBottom": "40px"},
                )
            )

    except Exception:
        logger.exception("Could not make the plot: ")
        return (
            None,
            None,
            html.Div("Visualization crashed. See logs.", style={"color": "red"}),
            None,
        )

    return (
        graphs,
        None,
        html.Div("Visualization suceeded", style={"color": "green"}),
        name_folder_visu,
    )


@callback(
    Output("annotations-store", "data", allow_duplicate=True),
    Input({"type": "graph", "name": ALL}, "relayoutData"),
    State({"type": "graph", "name": ALL}, "figure"),
    State({"type": "graph", "name": ALL}, "id"),
    State("annotations-store", "data"),
    prevent_initial_call=True,
)
def sync_plotly_annotations(relayout_list, figures, graph_ids, store):
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
        user_annotations = [ann for ann in layout_annotations if ui_helper.is_user_annotation(ann)]
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
    if not relayout or "shapes" not in fig.get("layout", {}):
        raise exceptions.PreventUpdate

    patch = Patch()
    shapes = fig["layout"]["shapes"]

    for idx, s in enumerate(shapes):
        # 1. Lock shape
        logger.debug(s)
        if not s.get("editable", True):
            continue

        patch["layout"]["shapes"][idx]["editable"] = False

        shape_type = s.get("type", "rect")

        # 3. Fill/line for rectangles/circles
        if shape_type in ["rect", "circle"]:
            pass

        # 4. Line shapes
        elif shape_type == "line":
            x0, x1 = s.get("x0"), s.get("x1")
            # Force vertical line if x0 != x1
            if x0 != x1:
                try:
                    dt0 = datetime_utils.parse_datetime(x0) if isinstance(x0, str) else x0
                    dt1 = datetime_utils.parse_datetime(x1) if isinstance(x1, str) else x1
                    midpoint = dt0 + (dt1 - dt0) / 2
                    patch["layout"]["shapes"][idx]["x0"] = datetime_utils.format_datetime(midpoint)
                    patch["layout"]["shapes"][idx]["x1"] = datetime_utils.format_datetime(midpoint)
                except Exception:
                    # fallback: ignore if parsing fails
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
    store = store.copy() if store else {"by_figure": {}}

    for fig, gid in zip(figures, ids):
        fig_name = gid["name"]
        shapes = fig.get("layout", {}).get("shapes", [])

        # Only update if different from existing
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
    # Persist immediately
    if folder_visu_path:
        path = Path(folder_visu_path) / "annotations.json"
        with path.open("w") as f:
            json.dump(store, f, indent=2, default=str)

    return


@callback(Output("shape-selector", "options"), Input("annotations-store", "data"))
def update_shape_options(store):
    if not store or "by_figure" not in store:
        return []

    options = []

    for fig_name, fig_data in store["by_figure"].items():
        for i, shape in enumerate(fig_data.get("shapes", [])):
            if shape is None:
                continue

            # Name
            name = shape.get("label", {}).get("text") or f"Shape {i}"

            # Extract color
            color = shape.get("line", {}).get("color") or shape.get("fillcolor") or "gray"

            square_color = ui_components.parse_color(color)

            # Prepend colored square
            label = html.Span(
                [
                    html.Span("■", style={"color": square_color, "margin-right": "6px"}),
                    f"{fig_name} - {name}",
                ]
            )

            options.append({"label": label, "value": f"{fig_name}|{i}"})

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
    triggered = callback_context.triggered_id

    hidden_style = {**EDIT_SHAPE_POPUP_STYLE, "display": "none"}

    if not selected_value or not store:
        return hidden_style, no_update, no_update, no_update

    if triggered != "modify-button":
        return hidden_style, no_update, no_update, no_update

    fig_name, shape_idx = selected_value.split("|")
    shape_idx = int(shape_idx)

    # Get shape from annotations-store
    shapes = store.get("by_figure", {}).get(fig_name, {}).get("shapes", [])
    if shape_idx >= len(shapes):
        return hidden_style, no_update, no_update, no_update

    shape = shapes[shape_idx]

    # Prefill name
    name = shape.get("label", {}).get("text", "")

    # Prefill global checkbox
    is_global = shape.get("yref") == "paper"
    global_value = ["global"] if is_global else []

    # Prefill color
    color_str = shape.get("line", {}).get("color") or shape.get("fillcolor")
    color_value = no_update
    if color_str:
        # Match rgba(r,g,b,a)
        match = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", color_str)
        if match:
            r, g, b, a = match.groups()
            color_value = {
                "hex": f"#{int(r):02x}{int(g):02x}{int(b):02x}",
                "rgb": {"r": int(r), "g": int(g), "b": int(b), "a": float(a)},
            }

    return (
        {**EDIT_SHAPE_POPUP_STYLE, "display": "block"},
        name,
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
    ctx = callback_context
    triggered_props = ctx.triggered_prop_ids
    logger.debug(f"ctx.outputs_list: {ctx.outputs_list}")
    current_fig_name = (ctx.outputs_list).get("id", {}).get("name")

    # Guard 1 — Only react to Save or Delete explicitly
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

    # Guard 2 — Selection must exist
    if not selected_value:
        logger.debug(f"selected_value empty: {selected_value}")
        return Patch()

    try:
        selected_fig_name, shape_idx = selected_value.split("|")
        shape_idx = int(shape_idx)
    except Exception:
        logger.debug(f"Invalid selected_value format: {selected_value}")
        return Patch()

    # Guard 3 — selected fig must be the correct one
    if selected_fig_name != current_fig_name:
        return Patch()

    # Guard 4 — Figure and shapes must be ready
    shapes = fig.get("layout", {}).get("shapes", [])

    if not shapes or shape_idx >= len(shapes):
        logger.debug(
            f"shapes object too small: shape_idx: {shape_idx}, shapes:{shapes}. "
            "Might be a bug. might be the callback firing too early, see if the feature seems buggy"
        )
        return Patch()

    patch = Patch()

    # =================================================
    # DELETE
    # =================================================
    if "delete-button.n_clicks" in triggered_props:
        logger.info("Deleting shape")

        patch["layout"]["shapes"] = shapes[:shape_idx] + shapes[shape_idx + 1 :]
        return patch

    # =================================================
    # SAVE / MODIFY
    # =================================================
    if "shape-save-button.n_clicks" in triggered_props:
        logger.info("Saving shape modifications")

        shape_patch = patch["layout"]["shapes"][shape_idx]
        original_shape = shapes[shape_idx]

        # ----------------------
        # Name
        # ----------------------
        if new_name:
            shape_patch["label"] = {"text": new_name}

        # ----------------------
        # Color + opacity
        # ----------------------
        if new_color and "rgb" in new_color:
            r = new_color["rgb"]["r"]
            g = new_color["rgb"]["g"]
            b = new_color["rgb"]["b"]
            a = new_color["rgb"]["a"]

            rgba_str = f"rgba({r},{g},{b},{a})"
            shape_type = original_shape.get("type", "rect")

            shape_patch["line"] = {"color": rgba_str, "width": 2}

            if shape_type in ("rect", "circle"):
                shape_patch["fillcolor"] = rgba_str

        # ----------------------
        # Global / local y-axis
        # ----------------------
        if global_value and "global" in global_value:
            shape_patch["yref"] = "paper"
            shape_patch["y0"] = 0
            shape_patch["y1"] = 1
        else:
            shape_patch["yref"] = original_shape.get("yref", "y")
            shape_patch["y0"] = original_shape.get("y0", 0)
            shape_patch["y1"] = original_shape.get("y1", 1)

        # ----------------------
        # Lock shape
        # ----------------------
        shape_patch["editable"] = False

        return patch

    return Patch()

HOST = "127.0.0.1"
PORT = 8050

webbrowser.open_new_tab(f"http://{HOST}:{PORT}")

app.run(
    host=HOST,
    port=PORT,
    debug=False,
    use_reloader=False
)
