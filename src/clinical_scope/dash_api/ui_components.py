"""
UI component utilities for Dash API visualization.

This module contains functions for creating Dash UI components based on schemas.
"""

import logging
from typing import Any

from dash import dcc, html

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)

# ==================================================================================================
# UI Component Creation
# ==================================================================================================


def dash_widget_factory(schema_class: Any, component_id_prefix: str) -> html.Div:
    """
    Create a Dash input component based on a schema class.

    Args:
        schema_class: The schema class defining the component properties
        component_id_prefix: Prefix for the component ID

    Returns:
        html.Div: A Div containing the label and input component

    """
    t = schema_class.API_TYPE
    default = schema_class.DEFAULT
    description = schema_class.DESCRIPTION
    name = schema_class.NAME

    component_id = f"{component_id_prefix}.{name}"

    label = html.Label(description, style={"width": "300px", "display": "inline-block"})

    if t == cst.ApiType.BOOL:
        input_component = dcc.Checklist(
            options=[{"label": "", "value": True}],
            value=[True] if default else [],
            id={"type": "patient-option", "name": component_id},
            style={"display": "inline-block", "verticalAlign": "middle"},
        )

    elif t in (cst.ApiType.INT, cst.ApiType.FLOAT):
        input_component = dcc.Input(
            type="number",
            value=default,
            id={"type": "patient-option", "name": component_id},
            style={"width": "300px"},
        )

    elif t in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder="YYYY-MM-DD HH:MM:SS",
            id={"type": "patient-option", "name": component_id},
            style={"width": "300px"},
        )

    elif t in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder="Path...",
            id={"type": "patient-option", "name": component_id},
            style={"width": "500px"},
        )

    elif t == cst.ApiType.TIMEZONE:
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder="e.g. Europe/Paris",
            id={"type": "patient-option", "name": component_id},
            style={"width": "300px"},
        )

    else:
        msg = f"Unsupported API_TYPE: {t}"
        raise ValueError(msg)

    return html.Div(children=[label, input_component], style={"marginBottom": "8px"})


def build_ui_and_schema_registry(
    options_class: Any,
    prefix: str,
    extra_per_field: dict[str, list] | None = None,
) -> tuple[html.Div, dict]:
    """
    Build UI and schema registry from an options class.

    Args:
        options_class: The options class defining the fields
        prefix: Prefix for component IDs
        extra_per_field: Optional dict mapping component ID to extra Dash components
            to render inline (to the right) of that field's widget.

    """
    components = []
    schema_lookup = {}

    # Collect only nested classes that have NAME (ignore others)
    nested_classes = [
        getattr(options_class, attr)
        for attr in dir(options_class)
        if hasattr(getattr(options_class, attr), "NAME")
    ]

    # Sort by ORDER field
    nested_classes.sort(key=lambda cls: getattr(cls, "ORDER", 999))

    # Index-based iteration with lookahead for consecutive TIMESTAMP fields
    i = 0
    while i < len(nested_classes):
        schema_class = nested_classes[i]
        comp_id = f"{prefix}.{schema_class.NAME}"
        schema_lookup[comp_id] = schema_class

        # Check if current and next field are both TIMESTAMP → render side by side
        if (
            i + 1 < len(nested_classes)
            and schema_class.API_TYPE == cst.ApiType.TIMESTAMP
            and nested_classes[i + 1].API_TYPE == cst.ApiType.TIMESTAMP
        ):
            next_class = nested_classes[i + 1]
            next_comp_id = f"{prefix}.{next_class.NAME}"
            schema_lookup[next_comp_id] = next_class

            component_left = dash_widget_factory(schema_class, prefix)
            component_right = dash_widget_factory(next_class, prefix)
            row = html.Div(
                [component_left, component_right],
                style={"display": "flex", "gap": "24px", "marginBottom": "8px"},
            )
            components.append(row)
            i += 2
        else:
            widget = dash_widget_factory(schema_class, prefix)
            extras = (extra_per_field or {}).get(comp_id)
            if extras:
                # Strip marginBottom from widget; outer row owns the spacing
                widget.style = {k: v for k, v in widget.style.items() if k != "marginBottom"}
                component = html.Div(
                    [widget, *extras],
                    style={"display": "flex", "alignItems": "center", "marginBottom": "8px"},
                )
            else:
                component = widget
            components.append(component)
            i += 1

    return html.Div(components), schema_lookup
