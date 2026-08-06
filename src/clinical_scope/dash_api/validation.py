"""Validate raw Dash widget values against their option schema classes."""

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

import clinical_scope.constants as cst
from clinical_scope.dash_api import helper_api as ui_helper
from clinical_scope.dash_api import ui_components


def _validate_by_type(
    value: Any,
    api_type: cst.ApiType,
    extension: str | None = None,
    choices: tuple | None = None,
) -> str | None:
    """
    Validate a non-empty value against its API type.

    Returns a message fragment describing the failure (meant to be appended to a field
    name), or None when the value is valid. Emptiness is the caller's concern.
    """
    try:
        if api_type == cst.ApiType.CHOICE:
            allowed = [choice_value for choice_value, _ in choices or ()]
            if value not in allowed:
                return f"must be one of {allowed}"

        elif api_type in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY):
            pd.Timestamp(value)

        elif api_type == cst.ApiType.TIMEZONE:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, KeyError):
                return f"is not a valid IANA timezone: {value!r}"

        elif api_type == cst.ApiType.INT:
            int(value)

        elif api_type == cst.ApiType.FLOAT:
            float(value)

        elif api_type == cst.ApiType.PATH_FILE:
            path = ui_helper.format_path(value)
            if not path.is_file():
                return "must be an existing file"
            if extension and path.suffix != extension:
                return f"must end with {extension}"

        elif api_type == cst.ApiType.PATH_FOLDER:
            path = ui_helper.format_path(value)
            if not path.is_dir():
                return "must be an existing folder"

    except (ValueError, TypeError, AttributeError):
        return str(value)

    return None


def validate_value(schema_class: Any, value: Any) -> tuple[bool, str]:
    """
    Validate a value against a schema class.

    Returns ``(is_valid, error_message)``; the message is empty when valid. An empty
    value passes unless the schema marks the field MANDATORY.
    """
    name = schema_class.NAME
    mandatory = schema_class.MANDATORY
    api_type = schema_class.API_TYPE
    extension = getattr(schema_class, "EXTENSION", None)
    choices = getattr(schema_class, "CHOICES", None)

    if value in ("", None):
        if mandatory:
            return False, f"{name} is mandatory"
        return True, ""

    error = _validate_by_type(value, api_type, extension, choices)
    if error:
        return False, f"{name} {error}"

    return True, ""


def validate_and_collect(values_dict: dict, schema_lookup: dict) -> tuple[dict, list]:
    """
    Validate a whole form's worth of widget values in one pass.

    Both arguments are keyed by component id (``global.<field>`` or
    ``specific.<datasource>.<field>``). Returns ``(validated_dict, errors)``, where
    validated_dict re-nests the flat ids into the patient_options shape: global fields
    at the top level, per-datasource fields under their datasource name. Fields that
    fail validation are omitted from the dict and reported in errors instead, so a
    non-empty errors list means the dict is incomplete.
    """
    validated_dict = {}
    errors = []

    for component_id, value in values_dict.items():
        parts = component_id.split(".")
        is_global = parts[0] == cst.PatientOptions.GLOBAL
        datasource_name = None if is_global else parts[1]

        schema = schema_lookup[component_id]
        name = getattr(schema, "NAME", component_id)
        description = getattr(schema, "DESCRIPTION", name)
        mandatory = getattr(schema, "MANDATORY", True)
        api_type = getattr(schema, "API_TYPE", None)
        extension = getattr(schema, "EXTENSION", None)
        choices = getattr(schema, "CHOICES", None)

        if value in ("", None):
            if mandatory:
                errors.append(f"{description} is mandatory")
            continue

        error = _validate_by_type(value, api_type, extension, choices)
        if error:
            errors.append(f"{description} {error}")
            continue

        # Normalize path values: strip surrounding quotes (e.g. Windows copy-paste)
        if api_type in (cst.ApiType.PATH_FILE, cst.ApiType.PATH_FOLDER):
            stored_value = str(ui_helper.format_path(value))
        else:
            stored_value = ui_components.from_widget_value(api_type, value)

        if is_global:
            validated_dict[name] = stored_value
        else:
            if datasource_name not in validated_dict:
                validated_dict[datasource_name] = {}
            validated_dict[datasource_name][name] = stored_value

    return validated_dict, errors
