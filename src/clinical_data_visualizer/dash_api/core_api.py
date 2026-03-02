# === Imports === #
import sys
import webbrowser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import dash_bootstrap_components as dbc
import dash_daq as daq
from dash import Dash, dcc, html

from clinical_data_visualizer import logger_config

# Import callbacks to register them with the app
from clinical_data_visualizer.dash_api import callbacks  # noqa: F401
from clinical_data_visualizer.dash_api.helper_api import get_cached_db_options_path
from clinical_data_visualizer.dash_api.styles import (
    INSPECTION_MODAL_STYLE_HIDDEN,
)

# === API Version === #
try:
    __version__ = version("clinical_data_visualizer")
except PackageNotFoundError:
    __version__ = "0.0.0-dev (not installed)"

# === Configure the logger and add new app run message === #
logs_path_root = logger_config.get_logs_path()
logs_path = logs_path_root / "app/dash_api.log"
logger = logger_config.setup_logging(logs_path, debug=True)
logger.info("========================================")
logger.info("New app run - Version %s", __version__)
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

# Resolve assets folder: PyInstaller bundles files under sys._MEIPASS
if getattr(sys, "frozen", False):
    _assets_folder = str(Path(sys._MEIPASS) / "clinical_data_visualizer" / "dash_api" / "assets")  # noqa: SLF001
else:
    _assets_folder = str(Path(__file__).parent / "assets")

# Show "Reload last config" button only when a cached config exists at layout render time.
_reload_btn_style = {
    "backgroundColor": "#6c757d",
    "color": "white",
    "border": "none",
    "padding": "6px 16px",
    "borderRadius": "4px",
    "cursor": "pointer",
    "display": "inline-block" if get_cached_db_options_path().exists() else "none",
    "margin-right": "10px",
    "margin-left": "10px",
}

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    assets_folder=_assets_folder,
)

app.layout = html.Div(
    [
        # Version display in top right corner
        html.Div(
            f"API Version: {__version__}",
            style={
                "position": "absolute",
                "top": "10px",
                "right": "10px",
                "color": "#666",
                "fontSize": "12px",
                "fontFamily": "monospace",
                "backgroundColor": "#f0f0f0",
                "padding": "4px 8px",
                "borderRadius": "4px",
                "border": "1px solid #ddd",
            },
        ),
        dcc.Store(id="folder-visu-path", data=""),
        dcc.Store(id="schema-registry", data={}),
        html.H2("Database Options"),
        html.Div(
            [
                dcc.Upload(
                    id="db-options-upload",
                    children=html.Button(
                        "Upload config file",
                        style={
                            "backgroundColor": "#007bff",
                            "color": "white",
                            "border": "none",
                            "padding": "6px 16px",
                            "borderRadius": "4px",
                            "cursor": "pointer",
                            "margin-right": "10px",
                        },
                    ),
                    multiple=False,
                    accept=".json,.xlsx",
                ),
                html.Button(
                    "Reload last config",
                    id="reload-cached-db-button",
                    style=_reload_btn_style,
                ),
                html.Button(
                    "Default visualization (all sources)",
                    id="default-viz-button",
                    style={
                        "backgroundColor": "#28a745",
                        "color": "white",
                        "border": "none",
                        "padding": "6px 16px",
                        "borderRadius": "4px",
                        "cursor": "pointer",
                        "margin-left": "10px",
                    },
                ),
            ],
            style={"display": "flex", "alignItems": "center"},
        ),
        html.Div(id="db-options-status"),
        dcc.Store(id="db-options-store"),
        html.Hr(),
        html.H2("Patient Options"),
        html.Div(id="patient-options-ui"),
        html.Div(
            [
                html.Button(
                    "Process visualization",
                    id="process-button",
                    style={
                        "backgroundColor": "#fd7e14",
                        "color": "white",
                        "border": "none",
                        "padding": "10px 28px",
                        "borderRadius": "4px",
                        "cursor": "pointer",
                        "fontSize": "16px",
                        "fontWeight": "bold",
                    },
                ),
                html.Button(
                    "Inspect data",
                    id="inspect-button",
                    style={
                        "backgroundColor": "#17a2b8",
                        "color": "white",
                        "border": "none",
                        "padding": "10px 22px",
                        "borderRadius": "4px",
                        "cursor": "pointer",
                        "fontSize": "15px",
                        "fontWeight": "bold",
                        "marginLeft": "12px",
                    },
                ),
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "marginTop": "16px",
                "marginBottom": "8px",
            },
        ),
        html.Div(id="validation-errors"),
        dcc.Loading(
            type="default",
            children=html.Div(id="process-status"),
        ),
        dcc.Loading(
            type="default",
            children=html.Div(id="inspect-status"),
        ),
        html.Div(
            id="shape-controls",
            style={"display": "none"},
            children=[
                dcc.Dropdown(
                    id="shape-selector",
                    options=[],
                    value=None,
                    clearable=False,
                ),
                html.Button("Modify", id="modify-button"),
                html.Button("Delete", id="delete-button"),
            ],
        ),
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
        # Inspection modal
        html.Div(
            id="inspection-modal",
            style=INSPECTION_MODAL_STYLE_HIDDEN,
            children=[
                html.Div(
                    [
                        # Header row
                        html.Div(
                            [
                                html.H3("Data Inspection", style={"margin": 0}),
                                html.Div(
                                    [
                                        html.Button(
                                            "Download CSV",
                                            id="inspect-download-btn",
                                            style={
                                                "backgroundColor": "#17a2b8",
                                                "color": "white",
                                                "border": "none",
                                                "padding": "6px 14px",
                                                "borderRadius": "4px",
                                                "cursor": "pointer",
                                                "fontSize": "14px",
                                            },
                                        ),
                                        html.Button(
                                            "Close",
                                            id="inspection-modal-close",
                                            style={
                                                "backgroundColor": "#6c757d",
                                                "color": "white",
                                                "border": "none",
                                                "padding": "6px 14px",
                                                "borderRadius": "4px",
                                                "cursor": "pointer",
                                                "fontSize": "14px",
                                            },
                                        ),
                                    ],
                                    style={"display": "flex", "gap": "8px"},
                                ),
                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "alignItems": "center",
                                "marginBottom": "16px",
                                "borderBottom": "2px solid #dee2e6",
                                "paddingBottom": "12px",
                            },
                        ),
                        dcc.Loading(
                            type="default",
                            children=html.Div(id="inspection-modal-content"),
                        ),
                        dcc.Download(id="inspection-download"),
                    ],
                    style={
                        "background": "white",
                        "borderRadius": "8px",
                        "padding": "24px",
                        "width": "90vw",
                        "maxWidth": "1700px",
                        "maxHeight": "80vh",
                        "overflowY": "auto",
                        "boxShadow": "0 8px 32px rgba(0,0,0,0.25)",
                    },
                )
            ],
        ),
        html.Hr(),
        html.Div(id="visualization-container"),
        dcc.Store(id="annotations-store", data={}),
        dcc.Store(id="inspection-results-store", data=None),
    ],
    style={"padding": "20px 32px", "maxWidth": "1400px", "margin": "0 auto"},
)

HOST = "127.0.0.1"
PORT = 8050

if __name__ == "__main__":
    webbrowser.open_new_tab(f"http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
