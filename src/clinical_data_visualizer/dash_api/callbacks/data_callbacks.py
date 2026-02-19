"""
Data-related callbacks for Dash API visualization.

Contains callbacks for loading database options, building patient options UI,
and processing visualizations.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from plotly_resampler import FigureResampler

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.datasource_list as datasource
from clinical_data_visualizer import wrapper
from clinical_data_visualizer.dash_api import helper_api as ui_helper
from clinical_data_visualizer.dash_api import ui_components, validation
from clinical_data_visualizer.signal_container import PlotModel

logger = logging.getLogger(__name__)

# Server-side cache for FigureResampler objects, keyed by UUID.
# Suitable for single-user desktop app.
FIGURE_RESAMPLER_CACHE = {}


def _validate_json_file(decoded_content: bytes, filename: str) -> dict[str, Any]:
    """Validate and parse JSON file."""
    if not filename.endswith(".json"):
        msg = "Invalid file type"
        raise ValueError(msg)
    return json.loads(decoded_content.decode("utf-8"))


@callback(
    Output("db-options-store", "data"),
    Output("db-options-status", "children"),
    Input("db-options-upload", "contents"),
    Input("default-viz-button", "n_clicks"),
    State("db-options-upload", "filename"),
    prevent_initial_call=True,
)
def load_db_options(
    contents: str | None,
    n_clicks: int | None,  # noqa: ARG001
    filename: str,
) -> tuple[dict[str, Any] | None, html.Div | None]:
    """Load database options from uploaded file or generate defaults."""
    triggered = ctx.triggered_id

    if triggered == "default-viz-button":
        return (
            datasource.generate_default_database_options(),
            html.Div(
                "Using default visualization (all sources)",
                style={"color": "green", "fontWeight": "bold"},
            ),
        )

    if not contents:
        return None, None

    try:
        _, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)
        database_options_dict = _validate_json_file(decoded, filename)
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
def build_patient_options_ui(
    database_options: dict[str, Any] | None,
) -> tuple[list[Any] | None, dict[str, str]]:
    """Build the patient options UI based on loaded database options."""
    if not database_options:
        return None, {}

    components = []
    schema_lookup = {}

    header_style = {
        "borderBottom": "2px solid #dee2e6",
        "paddingBottom": "8px",
        "marginBottom": "12px",
    }
    card_style = {
        "border": "1px solid #dee2e6",
        "borderRadius": "6px",
        "padding": "12px 16px",
        "backgroundColor": "#f8f9fa",
        "marginBottom": "16px",
    }

    # Global options
    components.append(html.H3("Global Patient Options", style=header_style))
    component, schema = ui_components.build_ui_and_schema_registry(
        cst.PatientOptions, prefix="global"
    )
    components.append(html.Div(component, style=card_style))
    schema_lookup = schema_lookup | schema

    # Per-datasource options
    components.append(html.H3("Specific Options", style=header_style))

    datasource_cards = []
    requested_data_sources = database_options.keys()
    for data_source in datasource.DataSource.AVAILABLE:
        if data_source.NAME not in requested_data_sources:
            continue

        component, schema = ui_components.build_ui_and_schema_registry(
            data_source.OPTIONS.PatientOptionsDataSourceRelative,
            prefix=f"specific.{data_source.NAME}",
        )
        datasource_cards.append(
            html.Div(
                [html.H5(data_source.DESCRIPTION), component],
                style={
                    "border": "1px solid #dee2e6",
                    "borderRadius": "6px",
                    "padding": "12px",
                    "backgroundColor": "#f8f9fa",
                },
            )
        )
        schema_lookup = schema_lookup | schema

    components.append(
        html.Div(
            datasource_cards,
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr",
                "gap": "12px",
            },
        )
    )

    schema_data = {k: v.__name__ for k, v in schema_lookup.items()}

    return components, schema_data


def _rehydrate_schema_classes(schema_data: dict) -> dict[str, type]:
    """Rehydrate schema classes from schema_data dictionary."""
    schema_class_lookup = {}
    for k, v in schema_data.items():
        if k.startswith("global"):
            schema_class_lookup[k] = getattr(cst.PatientOptions, v)
        elif k.startswith("specific"):
            parts = k.split(".")
            datasource_name = parts[1] if len(parts) > 1 else None
            datasource_class = datasource.DataSource.get_subclass_by_name(datasource_name)
            logger.debug("parts: %s", parts)
            logger.debug("datasource_name: %s", datasource_name)
            logger.debug("datasource_class: %s", datasource_class)
            schema_class_lookup[k] = getattr(
                datasource_class.OPTIONS.PatientOptionsDataSourceRelative, v
            )
    return schema_class_lookup


@callback(
    Output("visualization-container", "children"),
    Output("validation-errors", "children"),
    Output("process-status", "children"),
    Output("folder-visu-path", "data"),
    Output("shape-controls", "style"),
    Input("process-button", "n_clicks"),
    State("db-options-store", "data"),
    State("schema-registry", "data"),
    State({"type": "patient-option", "name": ALL}, "value"),
    State({"type": "patient-option", "name": ALL}, "id"),
    prevent_initial_call=True,
)
def process_visualization(
    n_clicks: int,  # noqa: ARG001
    db_options: dict[str, Any] | None,
    schema_data: dict[str, str],
    values: list[Any],
    ids: list[dict[str, str]],
) -> tuple[Any, Any, Any, str | None, dict]:
    """Process visualization request with validated patient options."""
    shape_hidden = {"display": "none"}
    if not db_options:
        return None, "Database options not loaded", None, None, shape_hidden

    schema_class_lookup = _rehydrate_schema_classes(schema_data)

    # Map IDs to values
    logger.debug("ids: %s", ids)
    logger.debug("values: %s", values)
    values_by_id = {i["name"]: v for i, v in zip(ids, values, strict=False)}

    # Validate
    validated_dict, errors = validation.validate_and_collect(values_by_id, schema_class_lookup)
    logger.debug("errors: %s", errors)
    logger.debug("validated_dict: %s", validated_dict)

    if errors:
        return None, html.Ul([html.Li(e) for e in errors]), None, None, shape_hidden

    # Save JSON exactly as before
    patient_options_path = (
        Path(validated_dict["data_folder"]) / cst.FOLDER_NAME_VISU / "patient_options.json"
    )
    name_folder_visu = str(Path(validated_dict["data_folder"]) / cst.FOLDER_NAME_VISU)
    annotations_data = ui_helper.load_annotations(name_folder_visu)
    ui_helper.save_json(validated_dict, patient_options_path)

    FIGURE_RESAMPLER_CACHE.clear()

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
            shape_hidden,
        )

    return (
        graphs,
        None,
        html.Div("Visualization suceeded", style={"color": "green"}),
        name_folder_visu,
        {"display": "block"},
    )


def _build_graphs(
    model: Any,
    annotations_data: dict[str, Any],
) -> list[html.Div]:
    """
    Build list of dcc.Graph + dcc.Store components from model.

    Time-series figures are wrapped with FigureResampler for dynamic
    downsampling on zoom/pan. A companion dcc.Store holds the cache UUID
    so the resample_on_zoom callback can retrieve the server-side object.
    """
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
            newshape={
                "fillcolor": "rgba(0,255,0,0.25)",
                "line": {"color": "green", "width": 2},
                "layer": "above",
            },
        )

        # Wrap time_series with FigureResampler for dynamic downsampling
        uid = None
        if mod.name == "time_series":
            uid = str(uuid4())
            fig = FigureResampler(fig)
            FIGURE_RESAMPLER_CACHE[uid] = fig

        # Set explicit CSS height so the container matches the figure's intended
        # height.  Without this, Plotly's default autosize=True sizes the figure
        # to its container, and an unsized container collapses to a default that
        # can hide the plot (especially for time-series with few subplots).
        graph_height = int(mod.computed_height) if mod.computed_height else None
        graph_style = {"marginBottom": "40px"}
        if graph_height:
            graph_style["height"] = f"{graph_height}px"

        graphs.append(
            html.Div(
                [
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
                        style=graph_style,
                    ),
                    dcc.Store(id={"type": "resampler-store", "name": mod.name}, data=uid),
                ]
            )
        )

    return graphs
