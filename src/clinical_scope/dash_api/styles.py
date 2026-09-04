"""
Shared style constants for the Dash application.

Centralises style dicts used across layout (core_api.py) and callbacks
(data_callbacks.py) so there is a single source of truth.
"""

# ---------------------------------------------------------------------------
# 1. Color palette
# ---------------------------------------------------------------------------
COLOR_BLUE = "#007bff"  # Upload config
COLOR_GREY = "#6c757d"  # Reload last config, Close
COLOR_GREEN = "#28a745"  # Default visualization
COLOR_ORANGE = "#fd7e14"  # Process visualization
COLOR_TEAL = "#17a2b8"  # Inspect data, Download CSV
COLOR_PURPLE = "#7c4dff"  # Annotation mode active

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

# Settings pill — stacked directly under the version badge (top-right); badge-matching styling.
BUTTON_GEAR: dict = {
    "position": "absolute",
    "top": "40px",
    "right": "10px",
    "cursor": "pointer",
    "fontSize": "12px",
    "fontFamily": "monospace",
    "padding": "4px 10px",
    "borderRadius": "4px",
    "border": "1px solid #ddd",
    "backgroundColor": "#f0f0f0",
    "color": "#666",
}

ROOT_CONTAINER: dict = {
    "padding": "20px 32px",
    "maxWidth": "1400px",
    "margin": "0 auto",
}

# Action panel: peer "cards" (one per action) sit side-by-side so they read as a choice.
# flex-start (not stretch) so each card takes only the height its own content needs.
ACTION_PANEL_ROW: dict = {
    "display": "flex",
    "gap": "16px",
    "alignItems": "flex-start",
    "marginTop": "16px",
    "marginBottom": "8px",
    "flexWrap": "wrap",
}

# One action + its options, boxed with a border only (transparent background).
ACTION_CARD: dict = {
    "display": "flex",
    "flexDirection": "column",
    "alignItems": "flex-start",
    "gap": "8px",
    "padding": "12px",
    "border": "1px solid #dee2e6",
    "borderRadius": "8px",
    "backgroundColor": "transparent",
}

# ---------------------------------------------------------------------------
# 6. Annotation styles
# ---------------------------------------------------------------------------

# The toolbar shares one flex row with a status message of unbounded length; without these the
# buttons give up width to it and wrap their own labels onto a second line.
_BUTTON_ANNOTATION_UNSHRINKABLE: dict = {"whiteSpace": "nowrap", "flexShrink": 0}

BUTTON_ANNOTATION_INACTIVE: dict = {
    **_BUTTON_BASE,
    **_BUTTON_ANNOTATION_UNSHRINKABLE,
    "backgroundColor": COLOR_GREY,
    "padding": "6px 14px",
    "fontSize": "13px",
}

BUTTON_ANNOTATION_ACTIVE: dict = {
    **_BUTTON_BASE,
    **_BUTTON_ANNOTATION_UNSHRINKABLE,
    "backgroundColor": COLOR_PURPLE,
    "padding": "6px 14px",
    "fontSize": "13px",
    "boxShadow": f"0 0 0 2px {COLOR_PURPLE}55",
}

BUTTON_ANNOTATION_SAVE: dict = {
    **_BUTTON_BASE,
    "backgroundColor": COLOR_GREY,
    "padding": "6px 12px",
    "fontSize": "13px",
    "marginLeft": "8px",
}

ANNOTATION_TOOLBAR_STYLE: dict = {
    "display": "flex",
    "alignItems": "center",
    "gap": "6px",
    "padding": "8px 12px",
    "border": "1px solid #dee2e6",
    "borderRadius": "6px",
    "backgroundColor": "#f8f9fa",
    "marginBottom": "12px",
    "flexWrap": "wrap",
    "position": "sticky",
    "top": "0",
    "zIndex": 1000,
}

# Annotation creation modal — smaller centered dialog
ANNOTATION_MODAL_STYLE_HIDDEN: dict = {
    "display": "none",
    "position": "fixed",
    "top": 0,
    "left": 0,
    "width": "100vw",
    "height": "100vh",
    "backgroundColor": "rgba(0,0,0,0.45)",
    "zIndex": 3000,
    "justifyContent": "center",
    "alignItems": "center",
}
ANNOTATION_MODAL_STYLE_SHOWN: dict = {
    **ANNOTATION_MODAL_STYLE_HIDDEN,
    "display": "flex",
}

ANNOTATION_MODAL_PANEL: dict = {
    "background": "white",
    "borderRadius": "8px",
    "padding": "24px",
    "width": "420px",
    "maxWidth": "95vw",
    "boxShadow": "0 8px 32px rgba(0,0,0,0.25)",
}

SETTINGS_MODAL_PANEL: dict = {
    **ANNOTATION_MODAL_PANEL,
    "width": "800px",
    # The settings list grows with every new user option; scroll rather than overflow the viewport.
    "maxHeight": "85vh",
    "overflowY": "auto",
}

# Header above each group of option widgets (SECTION on the schema classes).
OPTION_SECTION_HEADER: dict = {
    "fontSize": "12px",
    "fontWeight": "bold",
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
    "color": COLOR_GREY,
    "borderBottom": "1px solid #e9ecef",
    "paddingBottom": "4px",
    "marginTop": "16px",
    "marginBottom": "10px",
}

ANNOTATION_LIST_ROW: dict = {
    "display": "flex",
    "alignItems": "center",
    "gap": "8px",
    "padding": "6px 8px",
    "borderBottom": "1px solid #f0f0f0",
    "fontSize": "13px",
}

ANNOTATION_LIST_PANEL: dict = {
    "border": "1px solid #dee2e6",
    "borderRadius": "6px",
    "padding": "8px 12px",
    "backgroundColor": "#fff",
    "marginBottom": "16px",
    "maxHeight": "300px",
    "overflowY": "auto",
}

ANNOTATION_LIST_PANEL_HIDDEN: dict = {**ANNOTATION_LIST_PANEL, "display": "none"}

BUTTON_ANNOTATION_SMALL: dict = {
    **BUTTON_ANNOTATION_INACTIVE,
    "padding": "2px 7px",
    "fontSize": "11px",
}

BUTTON_ANNOTATION_ROW: dict = {**BUTTON_ANNOTATION_SMALL, "padding": "1px 5px", "fontSize": "10px"}

BUTTON_DISABLED_OVERLAY: dict = {"opacity": 0.4, "cursor": "not-allowed"}

# ---------------------------------------------------------------------------
# Colour picker (annotation & group creation modals)
# ---------------------------------------------------------------------------

# No "selected" variant by design: the hex field alone records the chosen colour.
COLOR_PRESET_SWATCH: dict = {
    "width": "22px",
    "height": "22px",
    "borderRadius": "50%",
    "cursor": "pointer",
    "flexShrink": 0,
}

# Square and inset in the hex field, so it reads as that field's value and not a seventh preset.
COLOR_PREVIEW_SWATCH: dict = {
    "width": "22px",
    "height": "22px",
    "borderRadius": "2px",
    "margin": "3px",
    "flexShrink": 0,
}

# Wrapper carrying the border, so the preview swatch and the text sit in one visual control.
COLOR_HEX_FIELD: dict = {
    "display": "flex",
    "alignItems": "center",
    "border": "1px solid #ced4da",
    "borderRadius": "4px",
    "overflow": "hidden",
}

COLOR_HEX_INPUT: dict = {
    "width": "80px",
    "padding": "4px 8px 4px 2px",
    "border": "none",
    "outline": "none",
    "fontSize": "12px",
    "fontFamily": "monospace",
}


# ---------------------------------------------------------------------------
# Graph config (dcc.Graph "config" prop)
# ---------------------------------------------------------------------------

# An armed annotation swallows the clicks and hover of the plot beneath it: plotly's editors
# are figure-wide and force `pointer-events: all` onto everything they arm.  Drag mode is
# what buys that back, by arming them only while the user is nudging — hence two configs
# derived from one base, so leaving the mode restores what the graph was built with.
GRAPH_CONFIG: dict = {"displayModeBar": True}

GRAPH_CONFIG_DRAGGABLE: dict = {
    **GRAPH_CONFIG,
    # `annotationPosition` also arms the subplot titles make_subplots puts in the same list;
    # they snap back on the next render, which is why it is affordable here and was not
    # affordable as a permanent setting.
    "edits": {"shapePosition": True, "annotationPosition": True},
}
