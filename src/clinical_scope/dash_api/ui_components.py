"""Schema-driven factory for the Dash input widgets used across the app."""

import logging
from typing import Any

from dash import dcc, html

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)

# ==================================================================================================
# UI Component Creation
# ==================================================================================================


def save_html_indicator_text(enabled: bool) -> str:
    """Read-only label mirroring the save_html_on_process user option beside Process."""
    return f"HTML export on Process: {'on' if enabled else 'off'}"


# Widget value contract: BOOL renders as a dcc.Checklist whose value is a list
# ([True] when checked, [] when not); every other API_TYPE round-trips as its scalar.
# These two functions are the single owner of that mapping — keep them inverse.
def to_widget_value(api_type: str | None, value: Any) -> Any:
    """Encode a stored/Python value into the shape api_type's Dash widget expects."""
    if api_type == cst.ApiType.BOOL:
        return [True] if value else []
    return value


def from_widget_value(api_type: str | None, value: Any) -> Any:
    """Decode a Dash widget value back to its Python form (inverse of to_widget_value)."""
    if api_type == cst.ApiType.BOOL:
        return len(value or []) > 0
    return value


def dash_widget_factory(
    schema_class: Any,
    component_id_prefix: str,
    id_type: str = "patient-option",
    label_width: str = "300px",
) -> html.Div:
    """
    Create a Dash input component based on a schema class.

    Args:
        schema_class: The schema class defining the component properties
        component_id_prefix: Prefix for the component ID
        id_type: The ``type`` key of the pattern-matching widget id (scopes callbacks;
            e.g. "patient-option" vs "user-option")
        label_width: CSS width of the description label (widen it if a caller's
            descriptions don't fit on one line at the default)

    Returns:
        html.Div: A Div containing the label and input component

    """
    t = schema_class.API_TYPE
    default = schema_class.DEFAULT
    description = schema_class.DESCRIPTION
    name = schema_class.NAME
    placeholder = getattr(schema_class, "PLACEHOLDER", None)

    component_id = f"{component_id_prefix}.{name}"

    label = html.Label(
        description, style={"width": label_width, "display": "inline-block", "flexShrink": "0"}
    )

    if t == cst.ApiType.BOOL:
        input_component = dcc.Checklist(
            options=[{"label": "", "value": True}],
            value=to_widget_value(t, default),
            id={"type": id_type, "name": component_id},
            style={"display": "inline-block", "verticalAlign": "middle"},
        )

    elif t in (cst.ApiType.INT, cst.ApiType.FLOAT):
        input_component = dcc.Input(
            type="number",
            value=default,
            placeholder=placeholder,
            min=getattr(schema_class, "MIN", None),
            max=getattr(schema_class, "MAX", None),
            debounce=True,
            id={"type": id_type, "name": component_id},
            style={"width": "300px"},
        )

    elif t in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY, cst.ApiType.TIMEZONE):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder=placeholder,
            id={"type": id_type, "name": component_id},
            style={"width": "300px"},
        )

    elif t in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder=placeholder,
            debounce=0.1,
            id={"type": id_type, "name": component_id},
            style={"width": "450px", "flexShrink": "0"},
        )

    else:
        msg = f"Unsupported API_TYPE: {t}"
        raise ValueError(msg)

    container_style = {"marginBottom": "8px"}
    if t in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER):
        container_style |= {"display": "flex", "alignItems": "center"}
    return html.Div(children=[label, input_component], style=container_style)


def build_ui_and_schema_registry(
    options_class: Any,
    prefix: str,
    extra_per_field: dict[str, list] | None = None,
    id_type: str = "patient-option",
    label_width: str = "300px",
) -> tuple[html.Div, dict]:
    """
    Build UI and schema registry from an options class.

    Args:
        options_class: The options class defining the fields
        prefix: Prefix for component IDs
        extra_per_field: Optional dict mapping component ID to extra Dash components
            to render inline (to the right) of that field's widget.
        id_type: The ``type`` key of the generated widget ids (scopes callbacks).
        label_width: CSS width passed through to each field's description label.

    """
    components = []
    schema_lookup = {}

    nested_classes = [
        getattr(options_class, attr)
        for attr in dir(options_class)
        if hasattr(getattr(options_class, attr), "NAME")
    ]

    nested_classes.sort(key=lambda cls: getattr(cls, "ORDER", 999))

    # Index-based iteration with lookahead: consecutive TIMESTAMP fields render side by side.
    i = 0
    while i < len(nested_classes):
        schema_class = nested_classes[i]
        comp_id = f"{prefix}.{schema_class.NAME}"
        schema_lookup[comp_id] = schema_class

        if (
            i + 1 < len(nested_classes)
            and schema_class.API_TYPE == cst.ApiType.TIMESTAMP
            and nested_classes[i + 1].API_TYPE == cst.ApiType.TIMESTAMP
        ):
            next_class = nested_classes[i + 1]
            next_comp_id = f"{prefix}.{next_class.NAME}"
            schema_lookup[next_comp_id] = next_class

            component_left = dash_widget_factory(schema_class, prefix, id_type, label_width)
            component_right = dash_widget_factory(next_class, prefix, id_type, label_width)
            row = html.Div(
                [component_left, component_right],
                style={"display": "flex", "gap": "24px", "marginBottom": "8px"},
            )
            components.append(row)
            i += 2
        else:
            widget = dash_widget_factory(schema_class, prefix, id_type, label_width)
            extras = (extra_per_field or {}).get(comp_id)
            if extras:
                widget.style = {k: v for k, v in widget.style.items() if k != "marginBottom"}
                component = html.Div(
                    [widget, *extras],
                    style={"display": "flex", "alignItems": "flex-start", "marginBottom": "8px"},
                )
            else:
                component = widget
            components.append(component)
            i += 1

    return html.Div(components), schema_lookup
