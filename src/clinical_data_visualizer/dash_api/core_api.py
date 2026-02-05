# === Imports === #
import webbrowser

import dash_bootstrap_components as dbc
import dash_daq as daq
from dash import Dash, dcc, html

from clinical_data_visualizer import logger_config

# Import callbacks to register them with the app
from clinical_data_visualizer.dash_api import callbacks  # noqa: F401

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
            options=[],
            value=None,
            clearable=False,
        ),
        html.Button("Modify", id="modify-button"),
        html.Button("Delete", id="delete-button"),
        # Shape edit modal
        html.Div(
            id="shape-edit-popup",
            style=EDIT_SHAPE_POPUP_STYLE,
            children=[
                html.Div(
                    [
                        html.H4("Edit Shape", style={"margin-bottom": "20px"}),
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
                                                    options=[{"label": "Global", "value": "global"}],
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
                        ),
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

HOST = "127.0.0.1"
PORT = 8050

webbrowser.open_new_tab(f"http://{HOST}:{PORT}")

app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
