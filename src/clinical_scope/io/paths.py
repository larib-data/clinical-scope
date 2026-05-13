"""
Patient folder path resolution helpers.

Single source of truth for every well-known path inside a patient folder.
All functions accept the patient data folder root and return an absolute Path.
"""

from __future__ import annotations

from pathlib import Path

import clinical_scope.constants as cst


def _get_output_folder(patient_folder: str | Path) -> Path:
    """Return ``<patient_folder>/clinical_scope_output/``."""
    return Path(patient_folder) / cst.FOLDER_NAME_OUTPUT


def get_visualization_path(patient_folder: str | Path) -> Path:
    """Return the HTML visualization output path."""
    return _get_output_folder(patient_folder) / cst.DEFAULT_NAME_VISUALIZATION


def get_database_options_path(patient_folder: str | Path) -> Path:
    """Return the cached database options path."""
    return _get_output_folder(patient_folder) / cst.DEFAULT_NAME_DATABASE_OPTIONS


def get_patient_options_path(patient_folder: str | Path) -> Path:
    """Return the saved patient options path."""
    return _get_output_folder(patient_folder) / cst.DEFAULT_NAME_PATIENT_OPTIONS


def get_annotations_path(patient_folder: str | Path) -> Path:
    """Return the annotations file path."""
    return _get_output_folder(patient_folder) / cst.ANNOTATION_FILE_NAME


def get_datasource_cache_path(patient_folder: str | Path, filename: str) -> Path:
    """Return ``<patient_folder>/clinical_scope_output/<filename>`` for parquet caches."""
    return _get_output_folder(patient_folder) / filename
