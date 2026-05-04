"""
Shared style constants for the Dash application.

Centralises style dicts used across layout (core_api.py) and callbacks
(data_callbacks.py, shape_callbacks.py) so there is a single source of truth.

Sections
--------
1. Color palette
2. Button styles
3. Card & section header styles
4. Modal styles
5. Layout styles
"""

# ---------------------------------------------------------------------------
# 1. Color palette
# ---------------------------------------------------------------------------
COLOR_BLUE = "#007bff"  # Upload config
COLOR_GREY = "#6c757d"  # Reload last config, Close
COLOR_GREEN = "#28a745"  # Default visualization
COLOR_ORANGE = "#fd7e14"  # Process visualization
COLOR_TEAL = "#17a2b8"  # Inspect data, Download CSV

# ---------------------------------------------------------------------------
# 2. Button styles
# ---------------------------------------------------------------------------
_BUTTON_BASE: dict = {
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "cursor": "pointer",
}

BUTTON_UPLOAD: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_BLUE,
    "padding": "6px 16px",
    "marginRight": "10px",
}

BUTTON_RELOAD: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_GREY,
    "padding": "6px 16px",
    "marginRight": "10px",
    "marginLeft": "10px",
}

BUTTON_DEFAULT_VIZ: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_GREEN,
    "padding": "6px 16px",
    "marginLeft": "10px",
}

BUTTON_PROCESS: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_ORANGE,
    "padding": "10px 28px",
    "fontSize": "16px",
    "fontWeight": "bold",
}

BUTTON_INSPECT: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_TEAL,
    "padding": "10px 22px",
    "fontSize": "15px",
    "fontWeight": "bold",
    "marginLeft": "12px",
}

BUTTON_DOWNLOAD_CSV: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_TEAL,
    "padding": "6px 14px",
    "fontSize": "14px",
}

BUTTON_MODAL_CLOSE: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_GREY,
    "padding": "6px 14px",
    "fontSize": "14px",
}

# ---------------------------------------------------------------------------
# 3. Card & section header styles
# ---------------------------------------------------------------------------
SECTION_HEADER_STYLE: dict = {
    "borderBottom": "2px solid #dee2e6",
    "paddingBottom": "8px",
    "marginBottom": "12px",
}

CARD_STYLE: dict = {
    "border": "1px solid #dee2e6",
    "borderRadius": "6px",
    "padding": "12px 16px",
    "backgroundColor": "#f8f9fa",
    "marginBottom": "16px",
}

DATASOURCE_CARD_STYLE: dict = {
    "border": "1px solid #dee2e6",
    "borderRadius": "6px",
    "padding": "12px",
    "backgroundColor": "#f8f9fa",
}

# ---------------------------------------------------------------------------
# 4. Modal styles
# ---------------------------------------------------------------------------

# Inspection modal — full-screen overlay
INSPECTION_MODAL_STYLE_HIDDEN: dict = {
    "display": "none",
    "position": "fixed",
    "top": 0,
    "left": 0,
    "width": "100vw",
    "height": "100vh",
    "backgroundColor": "rgba(0,0,0,0.5)",
    "zIndex": 2000,
    "justifyContent": "center",
    "alignItems": "center",
}
INSPECTION_MODAL_STYLE_SHOWN: dict = {
    **INSPECTION_MODAL_STYLE_HIDDEN,
    "display": "flex",
}

INSPECTION_MODAL_PANEL: dict = {
    "background": "white",
    "borderRadius": "8px",
    "padding": "24px",
    "width": "90vw",
    "maxWidth": "1700px",
    "maxHeight": "80vh",
    "display": "flex",
    "flexDirection": "column",
    "overflowY": "hidden",
    "boxShadow": "0 8px 32px rgba(0,0,0,0.25)",
}

INSPECTION_MODAL_SCROLLABLE_BODY: dict = {
    "overflowY": "auto",
    "flex": "1",
}

INSPECTION_MODAL_HEADER_ROW: dict = {
    "display": "flex",
    "justifyContent": "space-between",
    "alignItems": "center",
    "marginBottom": "16px",
    "borderBottom": "2px solid #dee2e6",
    "paddingBottom": "12px",
}

# Shape edit popup — positioned overlay
EDIT_SHAPE_POPUP_STYLE: dict = {
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

EDIT_SHAPE_POPUP_PANEL: dict = {
    "background": "white",
    "padding": "20px",
    "borderRadius": "10px",
    "width": "500px",
    "maxWidth": "90vw",
}

# ---------------------------------------------------------------------------
# 5. Layout styles
# ---------------------------------------------------------------------------
VERSION_BADGE: dict = {
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
}

ROOT_CONTAINER: dict = {
    "padding": "20px 32px",
    "maxWidth": "1400px",
    "margin": "0 auto",
}

ACTION_BUTTONS_ROW: dict = {
    "display": "flex",
    "alignItems": "center",
    "marginTop": "16px",
    "marginBottom": "8px",
}
