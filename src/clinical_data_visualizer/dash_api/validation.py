"""
Validation utilities for Dash API visualization.

This module contains validation functions for user input, schema validation,
and type checking.
"""

from typing import Any

import pandas as pd

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer.dash_api import helper_api as ui_helper


def _validate_by_type(
    value: Any, api_type: cst.ApiType, extension: str | None = None
) -> str | None:
    """
    Validate a value based on its API type.

    Args:
        value: The value to validate (assumed non-empty)
        api_type: The cst.ApiType enum value
        extension: Optional file extension requirement

    Returns:
        Error message string if invalid, None if valid

    """
    try:
        if api_type in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY):
            pd.Timestamp(value)

        elif api_type == cst.ApiType.INT:
            int(value)

        elif api_type == cst.ApiType.FLOAT:
            float(value)

        elif api_type == cst.ApiType.PATH_FILE:
            p = ui_helper.format_path(value)
            if not p.is_file():
                return "must be an existing file"
            if extension and p.suffix != extension:
                return f"must end with {extension}"

        elif api_type == cst.ApiType.PATH_FOLDER:
            p = ui_helper.format_path(value)
            if not p.is_dir():
                return "must be an existing folder"

    except (ValueError, TypeError, AttributeError):
        return str(value)

    return None


def validate_value(schema_class: Any, value: Any) -> tuple[bool, str]:
    """
    Validate a value against a schema class.

    Args:
        schema_class: The schema class defining validation rules
        value: The value to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
        If valid, error_message is empty string

    """
    name = schema_class.NAME
    mandatory = schema_class.MANDATORY
    api_type = schema_class.API_TYPE
    extension = getattr(schema_class, "EXTENSION", None)

    if value in ("", None):
        if mandatory:
            return False, f"{name} is mandatory"
        return True, ""

    error = _validate_by_type(value, api_type, extension)
    if error:
        return False, f"{name} {error}"

    return True, ""


def validate_and_collect(values_dict: dict, schema_lookup: dict) -> tuple[dict, list]:
    """
    Validate and collect user input values from Dash components.

    Args:
        values_dict: Dictionary of component values {component_id: value}
        schema_lookup: Dictionary of schema classes {component_id: schema_class}

    Returns:
        Tuple[dict, list]: (validated_dict, errors)
        validated_dict: Dictionary of validated values organized by field name
        errors: List of error messages

    """
    validated_dict = {}
    errors = []

    for comp_id, value in values_dict.items():
        parts = comp_id.split(".")
        is_global = parts[0] == "global"
        specific_name = None if is_global else parts[1]

        schema = schema_lookup[comp_id]
        name = getattr(schema, "NAME", comp_id)
        description = getattr(schema, "DESCRIPTION", name)
        mandatory = getattr(schema, "MANDATORY", True)
        api_type = getattr(schema, "API_TYPE", None)
        extension = getattr(schema, "EXTENSION", None)

        # Check mandatory
        if value in ("", None):
            if mandatory:
                errors.append(f"{description} is mandatory")
            continue

        # Validate by type
        error = _validate_by_type(value, api_type, extension)
        if error:
            errors.append(f"{description} {error}")
            continue

        # Store validated value
        if is_global:
            validated_dict[name] = value
        else:
            if specific_name not in validated_dict:
                validated_dict[specific_name] = {}
            validated_dict[specific_name][name] = value

    return validated_dict, errors
