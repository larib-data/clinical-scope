"""
UI component utilities for Dash API visualization.

This module contains functions for creating Dash UI components based on schemas
and managing UI-related utilities.
"""

import logging
import re

from dash import dcc, html

import clinical_data_visualizer.constants as cst

logger = logging.getLogger(__name__)

# ==================================================================================================
# UI Component Creation
# ==================================================================================================


def dash_widget_factory(schema_class, component_id_prefix: str):
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

    label = html.Label(description, style={"width": "200px", "display": "inline-block"})

    if t == cst.ApiType.BOOL:
        input_component = dcc.Checklist(
            options=[{"label": "", "value": True}],
            value=[True] if default else [],
            id={"type": "patient-option", "name": component_id},
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

    else:
        raise ValueError(f"Unsupported API_TYPE: {t}")

    return html.Div(children=[label, input_component], style={"marginBottom": "8px"})


def build_ui_and_schema_registry(options_class, prefix: str):
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

    for schema_class in nested_classes:
        comp_id = f"{prefix}.{schema_class.NAME}"
        component = dash_widget_factory(schema_class, prefix)
        components.append(component)
        schema_lookup[comp_id] = schema_class

    return html.Div(components), schema_lookup


def parse_color(color: str) -> str:
    """
    Parse color strings (rgb/rgba/hex) into a standardized format.

    Args:
        color: Color string in rgb, rgba, or hex format

    Returns:
        str: Standardized color string
    """
    # Parse rgb/rgba strings
    r, g, b, a = 128, 128, 128, 1  # default gray
    if color.startswith("rgba"):
        match = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", color)
        if match:
            r, g, b, a = match.groups()
        color_out = f"rgba({r},{g},{b},{a})"
    if color.startswith("rgb"):
        match = re.match(r"rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)", color)
        if match:
            r, g, b = match.groups()
            a = 1
        color_out = f"rgba({r},{g},{b},{a})"
    else:
        color_out = color

    return color_out
