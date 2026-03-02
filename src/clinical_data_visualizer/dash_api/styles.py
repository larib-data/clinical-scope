"""
Shared style constants for the Dash application.

Centralises style dicts used across layout (core_api.py) and callbacks
(data_callbacks.py) so there is a single source of truth.
"""

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
