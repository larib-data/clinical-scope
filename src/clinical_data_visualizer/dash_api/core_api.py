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
    ACTION_BUTTONS_ROW,
    BUTTON_DEFAULT_VIZ,
    BUTTON_DOWNLOAD_CSV,
    BUTTON_INSPECT,
    BUTTON_MODAL_CLOSE,
    BUTTON_PROCESS,
    BUTTON_RELOAD,
    BUTTON_UPLOAD,
    EDIT_SHAPE_POPUP_PANEL,
    EDIT_SHAPE_POPUP_STYLE,
    INSPECTION_MODAL_HEADER_ROW,
    INSPECTION_MODAL_PANEL,
    INSPECTION_MODAL_STYLE_HIDDEN,
    ROOT_CONTAINER,
    VERSION_BADGE,
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

# Resolve assets folder: PyInstaller bundles files under sys._MEIPASS
if getattr(sys, "frozen", False):
    _assets_folder = str(Path(sys._MEIPASS) / "clinical_data_visualizer" / "dash_api" / "assets")  # noqa: SLF001
else:
    _assets_folder = str(Path(__file__).parent / "assets")

# Show "Reload last config" button only when a cached config exists at layout render time.
_reload_btn_style = {
    **BUTTON_RELOAD,
    "display": "inline-block" if get_cached_db_options_path().exists() else "none",
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
        html.Div(f"API Version: {__version__}", style=VERSION_BADGE),
        dcc.Store(id="folder-visu-path", data=""),
        dcc.Store(id="schema-registry", data={}),
        html.H2("Database Options"),
        html.Div(
            [
                dcc.Upload(
                    id="db-options-upload",
                    children=html.Button("Upload config file", style=BUTTON_UPLOAD),
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
                    style=BUTTON_DEFAULT_VIZ,
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
                    style=BUTTON_PROCESS,
                ),
                html.Button(
                    "Inspect data",
                    id="inspect-button",
                    style=BUTTON_INSPECT,
                ),
            ],
            style=ACTION_BUTTONS_ROW,
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
                    style=EDIT_SHAPE_POPUP_PANEL,
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
                                            style=BUTTON_DOWNLOAD_CSV,
                                        ),
                                        html.Button(
                                            "Close",
                                            id="inspection-modal-close",
                                            style=BUTTON_MODAL_CLOSE,
                                        ),
                                    ],
                                    style={"display": "flex", "gap": "8px"},
                                ),
                            ],
                            style=INSPECTION_MODAL_HEADER_ROW,
                        ),
                        dcc.Loading(
                            type="default",
                            children=html.Div(id="inspection-modal-content"),
                        ),
                        dcc.Download(id="inspection-download"),
                    ],
                    style=INSPECTION_MODAL_PANEL,
                )
            ],
        ),
        html.Hr(),
        html.Div(id="visualization-container"),
        dcc.Store(id="annotations-store", data={}),
        dcc.Store(id="inspection-results-store", data=None),
    ],
    style=ROOT_CONTAINER,
)

HOST = "127.0.0.1"
PORT = 8050

if __name__ == "__main__":
    webbrowser.open_new_tab(f"http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
