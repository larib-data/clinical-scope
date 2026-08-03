"""
Callbacks for global per-user preferences (``user_options``).

The ``user-options-store`` is the single source of truth. The settings modal is
the only editing surface; a read-only indicator next to the Process button
mirrors the ``save_html_on_process`` flag one-way so you can see what Process
will do. Changes are persisted to ``~/.clinical_scope/user_options.json``
immediately (write-through is cheap and keeps the file authoritative).
"""

import logging
from typing import Any

from dash import ALL, Input, Output, State, callback, ctx, no_update

import clinical_scope.constants as cst
from clinical_scope.dash_api import helper_api as ui_helper
from clinical_scope.dash_api import ui_components
from clinical_scope.dash_api.styles import (
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_MODAL_STYLE_SHOWN,
)

logger = logging.getLogger(__name__)

_SAVE_HTML = cst.UserOptions.SaveHtmlOnProcess.NAME
_HEIGHT = cst.UserOptions.DefaultSubplotHeight.NAME


def _field_by_name(name: str) -> Any | None:
    """Return the UserOptions nested schema class whose NAME matches, or None."""
    return next((f for f in ui_helper.iter_user_option_fields() if name == f.NAME), None)


def _option_key(widget_id: dict[str, str]) -> str:
    """Extract the bare option name from a ``prefix.name`` pattern-matching widget id."""
    return widget_id["name"].split(".")[-1]


def _api_type(name: str) -> str | None:
    """API_TYPE of the named UserOptions field, or None if unknown."""
    return getattr(_field_by_name(name), "API_TYPE", None)


def _clamp_height(value: Any) -> int:
    """Coerce a subplot-height input to an int within the UI bounds."""
    if value is None:
        return cst.DEFAULT_SUBPLOT_HEIGHT
    return max(
        cst.UserOptions.DefaultSubplotHeight.MIN,
        min(cst.UserOptions.DefaultSubplotHeight.MAX, int(value)),
    )


# ==================================================================================================
@callback(
    Output("settings-modal", "style"),
    Input("settings-open-btn", "n_clicks"),
    Input("settings-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_settings_modal(open_clicks: int, close_clicks: int) -> dict:  # noqa: ARG001
    """Show the settings modal on gear click, hide it on close."""
    if ctx.triggered_id == "settings-open-btn":
        return ANNOTATION_MODAL_STYLE_SHOWN
    return ANNOTATION_MODAL_STYLE_HIDDEN


# ==================================================================================================
@callback(
    Output("user-options-store", "data"),
    Input({"type": "user-option", "name": ALL}, "value"),
    State({"type": "user-option", "name": ALL}, "id"),
    State("user-options-store", "data"),
    prevent_initial_call=True,
)
def persist_user_options(
    widget_values: list[Any],
    widget_ids: list[dict[str, str]],
    store: dict[str, Any] | None,
) -> dict[str, Any] | Any:
    """Persist a settings-modal change to the store and to disk."""
    updated = dict(store or {})

    # Decode each modal widget value to its Python form (BOOL checklist [True]/[] → bool).
    for value, wid in zip(widget_values, widget_ids, strict=False):
        key = _option_key(wid)
        updated[key] = ui_components.from_widget_value(_api_type(key), value)

    if _HEIGHT in updated:
        updated[_HEIGHT] = _clamp_height(updated[_HEIGHT])

    if updated == store:
        return no_update

    ui_helper.save_user_options(updated)
    logger.debug("user_options persisted: %s", updated)
    return updated


# ==================================================================================================
@callback(
    Output({"type": "user-option", "name": ALL}, "value"),
    Output("save-html-indicator", "children"),
    Input("user-options-store", "data"),
    State({"type": "user-option", "name": ALL}, "id"),
    prevent_initial_call=False,
)
def reflect_user_options(
    store: dict[str, Any] | None, widget_ids: list[dict[str, str]]
) -> tuple[list[Any], str]:
    """Mirror the store onto the modal widgets and the Process-side indicator."""
    store = store or {}
    values: list[Any] = []
    for wid in widget_ids:
        key = _option_key(wid)
        values.append(ui_components.to_widget_value(_api_type(key), store.get(key)))
    indicator = ui_components.save_html_indicator_text(bool(store.get(_SAVE_HTML)))
    return values, indicator
