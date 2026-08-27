"""
Callbacks for the global user options of the person at the keyboard (``user_options``).

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
from clinical_scope import user_options
from clinical_scope.dash_api import helper_api as ui_helper
from clinical_scope.dash_api import ui_components
from clinical_scope.dash_api.styles import (
    ANNOTATION_MODAL_STYLE_HIDDEN,
    ANNOTATION_MODAL_STYLE_SHOWN,
)

logger = logging.getLogger(__name__)

_SAVE_HTML = cst.UserOptions.SaveHtmlOnProcess.NAME
_INSPECT_PRUNING = cst.UserOptions.InspectConfiguredColumnsOnly.NAME


def _option_key(widget_id: dict[str, str]) -> str:
    """Extract the bare option name from a ``prefix.name`` pattern-matching widget id."""
    return widget_id["name"].split(".")[-1]


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
    # Decode each modal widget value to its Python form (BOOL checklist [True]/[] → bool),
    # then hold the whole set to what the schema allows.
    edited = dict(store or {})
    for value, widget_id in zip(widget_values, widget_ids, strict=False):
        key = _option_key(widget_id)
        edited[key] = ui_components.from_widget_value(user_options.api_type(key), value)
    updated, corrections = user_options.validate(edited)

    # A correction can land back on the value already in the store (invalid entry falls back
    # to an already-stored default) — updated == store alone would then wrongly skip the
    # resync, leaving the widget showing raw invalid text.
    if updated == store and not corrections:
        return no_update

    ui_helper.save_user_options(updated)
    logger.debug("user_options persisted: %s", updated)
    return updated


# ==================================================================================================
@callback(
    Output({"type": "user-option", "name": ALL}, "value"),
    Output("save-html-indicator", "children"),
    Output("inspect-pruning-indicator", "children"),
    Input("user-options-store", "data"),
    State({"type": "user-option", "name": ALL}, "id"),
    prevent_initial_call=False,
)
def reflect_user_options(
    store: dict[str, Any] | None, widget_ids: list[dict[str, str]]
) -> tuple[list[Any], str, str]:
    """Mirror the store onto the modal widgets and the Process-/Inspect-side indicators."""
    store = store or {}
    defaults = user_options.defaults()
    values: list[Any] = []
    for widget_id in widget_ids:
        key = _option_key(widget_id)
        # A key absent from the store (older options file) shows its schema default, not a blank.
        stored = store.get(key, defaults.get(key))
        values.append(ui_components.to_widget_value(user_options.api_type(key), stored))
    save_html_indicator = ui_components.save_html_indicator_text(bool(store.get(_SAVE_HTML)))
    pruning_indicator = ui_components.inspect_pruning_indicator_text(
        bool(store.get(_INSPECT_PRUNING))
    )
    return values, save_html_indicator, pruning_indicator
