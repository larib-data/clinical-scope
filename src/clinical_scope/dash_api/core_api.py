# === Imports === #
import sys
import webbrowser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import dash_bootstrap_components as dbc
from dash import Dash, dcc, html

from clinical_scope import logger_config

# Import callbacks to register them with the app
from clinical_scope.dash_api import callbacks  # noqa: F401
from clinical_scope.dash_api.annotations.model import (
    ANNOTATION_COLORS,
    AnnotationType,
)
from clinical_scope.dash_api.callbacks import default_mode
from clinical_scope.dash_api.helper_api import get_cached_db_options_path
from clinical_scope.dash_api.styles import (
    ACTION_BUTTONS_ROW,
    ANNOTATION_MODAL_PANEL,
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_TOOLBAR_STYLE,
    BUTTON_ANNOTATION_INACTIVE,
    BUTTON_ANNOTATION_SAVE,
    BUTTON_DEFAULT_VIZ,
    BUTTON_DOWNLOAD_CSV,
    BUTTON_INSPECT,
    BUTTON_MODAL_CLOSE,
    BUTTON_PROCESS,
    BUTTON_RELOAD,
    BUTTON_UPLOAD,
    COLOR_PURPLE,
    INSPECTION_MODAL_HEADER_ROW,
    INSPECTION_MODAL_PANEL,
    INSPECTION_MODAL_SCROLLABLE_BODY,
    INSPECTION_MODAL_STYLE_HIDDEN,
    ROOT_CONTAINER,
    VERSION_BADGE,
)

# === API Version === #
try:
    __version__ = version("clinical_scope")
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
    _assets_folder = str(Path(sys._MEIPASS) / "clinical_scope" / "dash_api" / "assets")  # noqa: SLF001
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

# ---------------------------------------------------------------------------
# Annotation toolbar — color swatches built from the preset palette
# ---------------------------------------------------------------------------
_COLOR_TYPE_LABELS = {
    AnnotationType.TIME_EVENT: "Time Event",
    AnnotationType.TIME_WINDOW: "Time Window",
    AnnotationType.POINT: "Point",
}

_annotation_type_buttons = [
    html.Button(
        label,
        id=f"annotation-type-btn-{ann_type.value}",
        n_clicks=0,
        style=BUTTON_ANNOTATION_INACTIVE,
    )
    for ann_type, label in _COLOR_TYPE_LABELS.items()
]

_annotation_toolbar = html.Div(
    id="annotation-toolbar",
    style={
        **ANNOTATION_TOOLBAR_STYLE,
        "display": "none",
        "justifyContent": "space-between",
        "alignItems": "center",
        "width": "100%",  # Force full width
        "boxSizing": "border-box",  # Include padding in width
        "padding": "8px 0",  # Optional: Add vertical padding
    },
    children=[
        # Left group: Annotate label + buttons
        html.Div(
            style={
                "display": "flex",
                "alignItems": "center",
                "gap": "8px",
                "flex": "1",  # Allow this group to grow
                "minWidth": "0",  # Prevent overflow
            },
            children=[
                html.Span(
                    "Annotate:", style={"fontWeight": "bold", "fontSize": "13px", "color": "#555"}
                ),
                *_annotation_type_buttons,
                html.Button(
                    "New Group",
                    id="new-group-btn",
                    n_clicks=0,
                    style=BUTTON_ANNOTATION_INACTIVE,
                ),
                html.Span(
                    "",
                    id="annotation-active-group-display",
                    style={
                        "fontSize": "12px",
                        "color": "#555",
                        "fontStyle": "italic",
                        "marginLeft": "4px",
                    },
                ),
            ],
        ),
        # Right group: Exit/Save buttons
        html.Div(
            style={
                "display": "flex",
                "alignItems": "center",
                "gap": "8px",
                "flex": "1",  # Allow this group to grow
                "justifyContent": "flex-end",  # Push to the right
                "minWidth": "0",  # Prevent overflow
            },
            children=[
                html.Button(
                    "Exit mode",
                    id="annotation-mode-deactivate",
                    n_clicks=0,
                    style={**BUTTON_ANNOTATION_INACTIVE, "display": "none"},
                ),
                html.Button(
                    "Save",
                    id="annotation-save-btn",
                    n_clicks=0,
                    style=BUTTON_ANNOTATION_SAVE,
                ),
                html.Span(
                    "",
                    id="annotation-count-badge",
                    style={
                        "fontSize": "12px",
                        "color": "#888",
                        "marginLeft": "4px",
                    },
                ),
                html.Span(
                    "",
                    id="annotation-save-status",
                    style={"fontSize": "12px", "color": "#28a745", "marginLeft": "8px"},
                ),
                html.Span(
                    "",
                    id="annotation-warning-msg",
                    style={
                        "fontSize": "12px",
                        "color": "#e67e00",
                        "marginLeft": "8px",
                        "fontStyle": "italic",
                    },
                ),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Annotation creation modal
# ---------------------------------------------------------------------------
_color_swatches = html.Div(
    [
        html.Div(
            id={"type": "annotation-color-swatch", "color": c},
            n_clicks=0,
            style={
                "width": "22px",
                "height": "22px",
                "borderRadius": "50%",
                "backgroundColor": c,
                "cursor": "pointer",
                "border": "2px solid transparent",
                "flexShrink": 0,
            },
        )
        for c in ANNOTATION_COLORS
    ],
    style={"display": "flex", "gap": "6px", "alignItems": "center"},
)

_annotation_modal = html.Div(
    id="annotation-modal",
    style=ANNOTATION_MODAL_STYLE_HIDDEN,
    children=[
        html.Div(
            [
                # Header
                html.Div(
                    [
                        html.H4("New Annotation", style={"margin": 0, "fontSize": "16px"}),
                        html.Button(
                            "×",  # noqa: RUF001
                            id="cancel-annotation-btn",
                            n_clicks=0,
                            style={
                                **BUTTON_MODAL_CLOSE,
                                "fontSize": "18px",
                                "padding": "2px 10px",
                                "lineHeight": "1",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "marginBottom": "16px",
                        "borderBottom": "1px solid #dee2e6",
                        "paddingBottom": "12px",
                    },
                ),
                # Position info (read-only, pre-filled)
                html.Div(
                    id="annotation-modal-position-display",
                    style={"fontSize": "12px", "color": "#666", "marginBottom": "12px"},
                ),
                # Label input
                html.Div(
                    [
                        html.Label(
                            "Label",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        dcc.Input(
                            id="annotation-label-input",
                            type="text",
                            placeholder="e.g. Alarm, Intervention…",
                            debounce=False,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid #ced4da",
                                "borderRadius": "4px",
                                "fontSize": "13px",
                                "boxSizing": "border-box",
                            },
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                # Color picker
                html.Div(
                    [
                        html.Label(
                            "Color",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        html.Div(
                            [
                                _color_swatches,
                                dcc.Input(
                                    id="annotation-color-input",
                                    type="text",
                                    value=ANNOTATION_COLORS[0],
                                    maxLength=7,
                                    style={
                                        "width": "90px",
                                        "padding": "4px 8px",
                                        "border": "1px solid #ced4da",
                                        "borderRadius": "4px",
                                        "fontSize": "12px",
                                        "fontFamily": "monospace",
                                    },
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center", "gap": "10px"},
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                # Global toggle (hidden for point annotations)
                html.Div(
                    id="annotation-global-checkbox-container",
                    children=[
                        dcc.Checklist(
                            id="annotation-global-checkbox",
                            options=[
                                {"label": " Apply to all subplots (global)", "value": "global"}
                            ],
                            value=[],
                            style={"fontSize": "13px"},
                        ),
                    ],
                    style={"marginBottom": "20px"},
                ),
                # Footer buttons
                html.Div(
                    [
                        html.Button(
                            "Cancel",
                            id="cancel-annotation-btn-footer",
                            n_clicks=0,
                            style=BUTTON_MODAL_CLOSE,
                        ),
                        html.Button(
                            "Create",
                            id="create-annotation-btn",
                            n_clicks=0,
                            style={
                                **BUTTON_MODAL_CLOSE,
                                "backgroundColor": COLOR_PURPLE,
                                "marginLeft": "8px",
                            },
                        ),
                    ],
                    style={"display": "flex", "justifyContent": "flex-end"},
                ),
            ],
            style=ANNOTATION_MODAL_PANEL,
        )
    ],
)

# ---------------------------------------------------------------------------
# Annotation group creation modal
# ---------------------------------------------------------------------------
_group_color_swatches = html.Div(
    [
        html.Div(
            id={"type": "group-color-swatch", "color": c},
            n_clicks=0,
            style={
                "width": "22px",
                "height": "22px",
                "borderRadius": "50%",
                "backgroundColor": c,
                "cursor": "pointer",
                "border": "2px solid transparent",
                "flexShrink": 0,
            },
        )
        for c in ANNOTATION_COLORS
    ],
    style={"display": "flex", "gap": "6px", "alignItems": "center"},
)

_annotation_group_modal = html.Div(
    id="annotation-group-modal",
    style=ANNOTATION_MODAL_STYLE_HIDDEN,
    children=[
        html.Div(
            [
                # Header
                html.Div(
                    [
                        html.H4("New Annotation Group", style={"margin": 0, "fontSize": "16px"}),
                        html.Button(
                            "×",  # noqa: RUF001
                            id="cancel-group-btn",
                            n_clicks=0,
                            style={
                                **BUTTON_MODAL_CLOSE,
                                "fontSize": "18px",
                                "padding": "2px 10px",
                                "lineHeight": "1",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "marginBottom": "16px",
                        "borderBottom": "1px solid #dee2e6",
                        "paddingBottom": "12px",
                    },
                ),
                # Name input
                html.Div(
                    [
                        html.Label(
                            "Group name",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        dcc.Input(
                            id="group-name-input",
                            type="text",
                            placeholder="e.g. Apnea, Intervention…",
                            debounce=False,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid #ced4da",
                                "borderRadius": "4px",
                                "fontSize": "13px",
                                "boxSizing": "border-box",
                            },
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                # Type dropdown
                html.Div(
                    [
                        html.Label(
                            "Annotation type",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        dcc.Dropdown(
                            id="group-type-dropdown",
                            options=[
                                {"label": "Time Event", "value": AnnotationType.TIME_EVENT.value},
                                {
                                    "label": "Time Window",
                                    "value": AnnotationType.TIME_WINDOW.value,
                                },
                                {"label": "Point", "value": AnnotationType.POINT.value},
                            ],
                            value=AnnotationType.TIME_EVENT.value,
                            clearable=False,
                            style={"fontSize": "13px"},
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                # Color picker
                html.Div(
                    [
                        html.Label(
                            "Color",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        html.Div(
                            [
                                _group_color_swatches,
                                dcc.Input(
                                    id="group-color-input",
                                    type="text",
                                    value=ANNOTATION_COLORS[0],
                                    maxLength=7,
                                    style={
                                        "width": "90px",
                                        "padding": "4px 8px",
                                        "border": "1px solid #ced4da",
                                        "borderRadius": "4px",
                                        "fontSize": "12px",
                                        "fontFamily": "monospace",
                                    },
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center", "gap": "10px"},
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                # Scope (time-based types only)
                html.Div(
                    [
                        html.Label(
                            "Scope",
                            style={"fontSize": "13px", "fontWeight": "bold", "marginBottom": "4px"},
                        ),
                        dcc.Checklist(
                            id="group-scope-is-global",
                            options=[
                                {"label": " Apply to all subplots (global)", "value": "global"}
                            ],
                            value=[],
                            style={"fontSize": "13px"},
                        ),
                        html.Div(
                            "Not applicable for Point annotations (always subplot-specific).",
                            style={"fontSize": "11px", "color": "#aaa", "marginTop": "4px"},
                        ),
                    ],
                    style={"marginBottom": "20px"},
                ),
                # Footer buttons
                html.Div(
                    [
                        html.Button(
                            "Cancel",
                            id="cancel-group-btn-footer",
                            n_clicks=0,
                            style=BUTTON_MODAL_CLOSE,
                        ),
                        html.Button(
                            "Create Group",
                            id="create-group-btn",
                            n_clicks=0,
                            style={
                                **BUTTON_MODAL_CLOSE,
                                "backgroundColor": COLOR_PURPLE,
                                "marginLeft": "8px",
                            },
                        ),
                    ],
                    style={"display": "flex", "justifyContent": "flex-end"},
                ),
            ],
            style=ANNOTATION_MODAL_PANEL,
        )
    ],
)

# ---------------------------------------------------------------------------
# Annotation list panel (shown below toolbar when annotations exist)
# ---------------------------------------------------------------------------
_annotation_list_panel = html.Div(
    id="annotation-list-panel",
    style={"marginBottom": "16px"},
    children=[],
)

app.layout = html.Div(
    [
        # Version display in top right corner
        html.Div(f"API Version: {__version__}", style=VERSION_BADGE),
        # Global annotation stores
        dcc.Store(id="annotation-store", data=[]),
        dcc.Store(id="annotation-mode-store", data=default_mode()),
        dcc.Store(id="annotation-modal-data", data={}),
        dcc.Store(id="annotation-expanded-groups-store", data=[]),
        dcc.Store(id="folder-visu-path", data=""),
        dcc.Store(id="display-timezone-store", data=None),
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
            id="patient-options-reload-status", style={"fontSize": "12px", "marginBottom": "8px"}
        ),
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
        html.Div(id="process-progress"),
        dcc.Interval(id="process-progress-interval", interval=500, disabled=True),
        html.Hr(),
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
                        # Body
                        html.Div(
                            [
                                dcc.Loading(
                                    type="default",
                                    children=html.Div(id="inspection-modal-content"),
                                ),
                                dcc.Download(id="inspection-download"),
                            ],
                            style=INSPECTION_MODAL_SCROLLABLE_BODY,
                        ),
                    ],
                    style=INSPECTION_MODAL_PANEL,
                )
            ],
        ),
        # Annotation modals (above visualization, below inspection modal in z-order)
        _annotation_modal,
        _annotation_group_modal,
        # Annotation toolbar + list (shown after visualization is generated)
        _annotation_toolbar,
        _annotation_list_panel,
        html.Div(id="visualization-container"),
        dcc.Store(id="inspection-results-store", data=None),
    ],
    style=ROOT_CONTAINER,
)

HOST = "127.0.0.1"
PORT = 8050


def main() -> None:
    webbrowser.open_new_tab(f"http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
