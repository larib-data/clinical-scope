"""
Configuration file parsing utilities.

This module provides functions for loading JSON and XLSX configuration files,
including database options and patient options.
"""

import json
import logging
from pathlib import Path

from clinical_data_visualizer.database_options_parser import validate_database_options_structure
from clinical_data_visualizer.database_options_xlsx import xlsx_to_database_options

logger = logging.getLogger(__name__)


# ==================================================================================================
def load_options(path: Path | None) -> dict:
    """Load JSON options from a file if the path exists."""
    if path and path.exists():
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    return {}


# ==================================================================================================
def build_patient_options(
    patient_folder: str | Path,
    path_patient_options: str | Path | None = None,
) -> dict:
    """
    Build a patient_options dict from a folder path and an optional JSON file.

    ``data_folder`` is always set from *patient_folder*.
    Any other keys present in the JSON file are preserved.
    """
    opts = load_options(Path(path_patient_options)) if path_patient_options else {}
    opts["data_folder"] = str(patient_folder)
    return opts


# ==================================================================================================
def load_database_options_from_path(path: Path) -> dict:
    """
    Load database options from a JSON or XLSX file.

    This is the canonical entry point for loading database options from a file
    path, supporting both formats accepted by the Dash UI file upload.

    Args:
        path: Path to a ``.json`` or ``.xlsx`` database options file.

    Returns:
        Parsed database options dictionary.

    Raises:
        ValueError: If the file extension is not supported.
        FileNotFoundError: If the path does not exist.

    """

    if not path.exists():
        msg = f"Database options file not found: {path}"
        raise FileNotFoundError(msg)

    suffix = path.suffix.lower()
    if suffix == ".json":
        db_options = load_options(path)
    elif suffix == ".xlsx":
        db_options = xlsx_to_database_options(path)
    else:
        msg = f"Unsupported file extension '{suffix}'. Expected .json or .xlsx."
        raise ValueError(msg)

    for w in validate_database_options_structure(db_options):
        logger.warning("database_options validation: %s", w)

    return db_options
