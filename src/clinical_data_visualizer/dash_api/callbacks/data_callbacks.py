"""
Data-related callbacks for Dash API visualization.

Contains callbacks for loading database options, building patient options UI,
and processing visualizations.
"""

import base64
import json
import logging
from pathlib import Path

from dash import ALL, Input, Output, State, callback, dcc, html

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
from clinical_data_visualizer import wrapper
from clinical_data_visualizer.dash_api import helper_api as ui_helper, ui_components, validation
from clinical_data_visualizer.signal_container import PlotModel

logger = logging.getLogger(__name__)


@callback(
    Output("db-options-store", "data"),
    Output("db-options-status", "children"),
    Input("db-options-upload", "contents"),
    State("db-options-upload", "filename"),
    prevent_initial_call=True,
)
def load_db_options(contents, filename):
    """Load and parse uploaded database options JSON file."""
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
    """Build the patient options UI based on loaded database options."""
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


def _rehydrate_schema_classes(schema_data: dict) -> dict:
    """Rehydrate schema classes from schema_data dictionary."""
    schema_class_lookup = {}
    for k, v in schema_data.items():
        if k.startswith("global"):
            schema_class_lookup[k] = getattr(cst.PatientOptions, v)
        if k.startswith("specific"):
            parts = k.split(".")
            datasource_name = parts[1] if len(parts) > 1 else None
            datasource_class = datasource.DataSource.get_subclass_by_name(datasource_name)
            logger.debug(f"parts: {parts}")
            logger.debug(f"datasource_name: {datasource_name}")
            logger.debug(f"datasource_class: {datasource_class}")
            schema_class_lookup[k] = getattr(
                datasource_class.OPTIONS.PatientOptionsDataSourceRelative, v
            )
    return schema_class_lookup


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
    """Process visualization request with validated patient options."""
    if not db_options:
        return None, "Database options not loaded", None, None

    schema_class_lookup = _rehydrate_schema_classes(schema_data)

    # Map IDs to values
    logger.debug(f"ids: {ids}")
    logger.debug(f"values: {values}")
    values_by_id = {i["name"]: v for i, v in zip(ids, values)}

    # Validate
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)
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
        graphs = _build_graphs(model, annotations_data)

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


def _build_graphs(model, annotations_data: dict) -> list:
    """Build list of dcc.Graph components from model."""
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
                    ],
                },
                style={"marginBottom": "40px"},
            )
        )

    return graphs
