"""Schema-driven factory for the Dash input widgets used across the app."""

import logging
from typing import Any

from dash import dcc, html

import clinical_scope.constants as cst
from clinical_scope.dash_api.styles import OPTION_SECTION_HEADER

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
    Build the label + input widget for one schema class, as a single Div.

    Args:
        id_type: The ``type`` key of the pattern-matching widget id (scopes callbacks;
            e.g. "patient-option" vs "user-option")
        label_width: CSS width of the description label (widen it if a caller's
            descriptions don't fit on one line at the default)

    Raises:
        ValueError: if the schema's API_TYPE has no widget mapping.

    """
    api_type = schema_class.API_TYPE
    default = schema_class.DEFAULT
    description = schema_class.DESCRIPTION
    name = schema_class.NAME
    placeholder = getattr(schema_class, "PLACEHOLDER", None)

    component_id = f"{component_id_prefix}.{name}"

    label = html.Label(
        description, style={"width": label_width, "display": "inline-block", "flexShrink": "0"}
    )

    if api_type == cst.ApiType.BOOL:
        input_component = dcc.Checklist(
            options=[{"label": "", "value": True}],
            value=to_widget_value(api_type, default),
            id={"type": id_type, "name": component_id},
            style={"display": "inline-block", "verticalAlign": "middle"},
        )

    elif api_type in (cst.ApiType.INT, cst.ApiType.FLOAT):
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

    elif api_type == cst.ApiType.CHOICE:
        input_component = dcc.Dropdown(
            options=[{"label": label, "value": value} for value, label in schema_class.CHOICES],
            value=default,
            clearable=False,  # a closed set always has a current value
            id={"type": id_type, "name": component_id},
            style={"width": "320px", "flexShrink": "0"},
        )

    elif api_type in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY, cst.ApiType.TIMEZONE):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder=placeholder,
            debounce=True,
            id={"type": id_type, "name": component_id},
            style={"width": "300px"},
        )

    elif api_type in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER):
        input_component = dcc.Input(
            type="text",
            value=default,
            placeholder=placeholder,
            debounce=0.1,
            id={"type": id_type, "name": component_id},
            style={"width": "450px", "flexShrink": "0"},
        )

    else:
        msg = f"Unsupported API_TYPE: {api_type}"
        raise ValueError(msg)

    container_style = {"marginBottom": "8px"}
    # A Dropdown renders as a block element, so it needs the same flex row as the path inputs.
    if api_type in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER, cst.ApiType.CHOICE):
        container_style |= {"display": "flex", "alignItems": "center"}
    return html.Div(children=[label, input_component], style=container_style)


def _widget_with_extras(
    schema_class: Any, prefix: str, id_type: str, label_width: str, extras: list | None
) -> html.Div:
    """Build one field's widget, appended with its extra components on the same line, if any."""
    widget = dash_widget_factory(schema_class, prefix, id_type, label_width)
    if not extras:
        return widget
    widget.style = {key: value for key, value in widget.style.items() if key != "marginBottom"}
    return html.Div(
        [widget, *extras],
        style={"display": "flex", "alignItems": "flex-start", "marginBottom": "8px"},
    )


def build_ui_and_schema_registry(
    options_class: Any,
    prefix: str,
    extra_per_field: dict[str, list] | None = None,
    id_type: str = "patient-option",
    label_width: str = "300px",
) -> tuple[html.Div, dict]:
    """
    Build every field widget for an options class, ordered by section then by ORDER.

    A schema class may declare a ``SECTION``, ranked by the options class's ``SECTION_ORDER``;
    a header is emitted on each change, and ORDER only ranks fields inside their own section.
    Classes without SECTION all share one implicit section, so they render by ORDER alone.

    Args:
        extra_per_field: Optional dict mapping component ID to extra Dash components
            to render inline (to the right) of that field's widget.
        id_type: The ``type`` key of the generated widget ids (scopes callbacks).
        label_width: CSS width passed through to each field's description label.

    Returns:
        The container Div, and a ``{component_id: schema_class}`` lookup the callbacks
        use to validate the values those widgets produce.

    """
    components = []
    schema_lookup = {}
    current_section = None

    nested_classes = [
        getattr(options_class, attr)
        for attr in dir(options_class)
        if hasattr(getattr(options_class, attr), "NAME")
    ]

    section_order = getattr(options_class, "SECTION_ORDER", ())

    def layout_rank(schema_class: Any) -> tuple[int, int]:
        section = getattr(schema_class, "SECTION", None)
        section_rank = section_order.index(section) if section in section_order else 0
        return section_rank, getattr(schema_class, "ORDER", 999)

    nested_classes.sort(key=layout_rank)

    # Index-based iteration with lookahead: consecutive TIMESTAMP fields render side by side.
    field_index = 0
    while field_index < len(nested_classes):
        schema_class = nested_classes[field_index]
        component_id = f"{prefix}.{schema_class.NAME}"
        schema_lookup[component_id] = schema_class

        section = getattr(schema_class, "SECTION", None)
        if section is not None and section != current_section:
            components.append(html.Div(section, style=OPTION_SECTION_HEADER))
            current_section = section

        if (
            field_index + 1 < len(nested_classes)
            and schema_class.API_TYPE == cst.ApiType.TIMESTAMP
            and nested_classes[field_index + 1].API_TYPE == cst.ApiType.TIMESTAMP
        ):
            next_class = nested_classes[field_index + 1]
            next_component_id = f"{prefix}.{next_class.NAME}"
            schema_lookup[next_component_id] = next_class

            left_extras = (extra_per_field or {}).get(component_id)
            right_extras = (extra_per_field or {}).get(next_component_id)
            if left_extras or right_extras:
                # Extras don't fit the compact side-by-side row (pushes it to two lines) —
                # one row per field instead, each keeping its own extras on one line.
                components.append(
                    _widget_with_extras(schema_class, prefix, id_type, label_width, left_extras)
                )
                components.append(
                    _widget_with_extras(next_class, prefix, id_type, label_width, right_extras)
                )
            else:
                component_left = dash_widget_factory(schema_class, prefix, id_type, label_width)
                component_right = dash_widget_factory(next_class, prefix, id_type, label_width)
                row = html.Div(
                    [component_left, component_right],
                    style={
                        "display": "flex",
                        "gap": "24px",
                        "marginBottom": "8px",
                        "alignItems": "center",
                    },
                )
                components.append(row)
            field_index += 2
        else:
            extras = (extra_per_field or {}).get(component_id)
            components.append(
                _widget_with_extras(schema_class, prefix, id_type, label_width, extras)
            )
            field_index += 1

    return html.Div(components), schema_lookup
