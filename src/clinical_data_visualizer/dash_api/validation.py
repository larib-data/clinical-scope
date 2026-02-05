"""
Validation utilities for Dash API visualization.

This module contains validation functions for user input, schema validation,
and type checking.
"""

from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer.dash_api import (
    helper_api as ui_helper,
)

# ==================================================================================================
# Validation Functions
# ==================================================================================================


def validate_timestamp(value, mandatory: bool = True) -> bool:
    """
    Validate timestamp format.

    Args:
        value: Timestamp string to validate
        mandatory: Whether the value is mandatory (default: True)

    Returns:
        bool: True if valid or not mandatory, False otherwise
    """
    if not value:
        return not mandatory
    try:
        pd.Timestamp(value)
        return True
    except Exception:
        return False


def validate_value(schema_class, value) -> tuple[bool, str]:
    """
    Validate a value against a schema class.

    Args:
        schema_class: The schema class defining validation rules
        value: The value to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
        If valid, error_message is None
    """
    name = schema_class.NAME
    mandatory = schema_class.MANDATORY
    t = schema_class.API_TYPE

    if value in ("", None):
        if mandatory:
            return False, f"{name} is mandatory"
        return True, ""

    try:
        if t in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY):
            pd.Timestamp(value)

        elif t == cst.ApiType.INT:
            int(value)

        elif t == cst.ApiType.FLOAT:
            float(value)

        elif t == cst.ApiType.PATH_FILE:
            p = ui_helper.format_path(value)
            if not p.is_file():
                return False, f"{name} must be an existing file"
            if hasattr(schema_class, "EXTENSION") and p.suffix != schema_class.EXTENSION:
                return False, f"{name} must end with {schema_class.EXTENSION}"

        elif t == cst.ApiType.PATH_FOLDER:
            p = ui_helper.format_path(value)
            if not p.is_dir():
                return False, f"{name} must be an existing folder"

    except Exception as e:
        return False, str(e)

    return True, ""


def collect_dash_values(values: dict, schemas: dict) -> tuple[dict, list]:
    """
    Collect and validate Dash component values.

    Args:
        values: Dictionary of component values
        schemas: Dictionary of schema classes for validation

    Returns:
        Tuple[dict, list]: (validated_values, errors)
        validated_values: Dictionary of validated field names to values
        errors: List of error messages
    """
    result = {}
    errors = []

    for field_id, value in values.items():
        schema = schemas[field_id]
        valid, error = validate_value(schema, value)

        if not valid:
            errors.append(f"{schema.DESCRIPTION}: {error}")
        else:
            result[schema.NAME] = value

    return result, errors


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
        ext = getattr(schema, "EXTENSION", None)

        if value in ("", None):
            if mandatory:
                errors.append(f"{description} is mandatory")
            continue

        try:
            if api_type in (cst.ApiType.TIMESTAMP, cst.ApiType.DAY):
                pd.Timestamp(value)
            elif api_type == cst.ApiType.INT:
                int(value)
            elif api_type == cst.ApiType.FLOAT:
                float(value)
            elif api_type == cst.ApiType.PATH_FILE:
                p = Path(value)
                if not p.is_file():
                    errors.append(f"{description} must be an existing file")
                if ext and p.suffix != ext:
                    errors.append(f"{description} must end with {ext}")
            elif api_type == cst.ApiType.PATH_FOLDER:
                p = Path(value)
                if not p.is_dir():
                    errors.append(f"{description} must be an existing folder")
            # add other API_TYPE checks here if needed
        except Exception as e:
            errors.append(f"{description}: {e!s}")

        if all(name not in e for e in errors):
            if is_global:
                validated_dict[name] = value
            else:
                if specific_name not in validated_dict:
                    validated_dict[specific_name] = {}
                validated_dict[specific_name][name] = value

    return validated_dict, errors
