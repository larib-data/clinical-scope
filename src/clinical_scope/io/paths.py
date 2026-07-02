"""
Patient folder path resolution helpers.

Single source of truth for every well-known path inside a patient folder.
All functions accept the patient data folder root and return an absolute Path.
"""

from __future__ import annotations

from pathlib import Path

import clinical_scope.constants as cst


def get_output_base(patient_folder: str | Path, output_root: str | Path | None = None) -> Path:
    """
    Return the folder under which ``clinical_scope_output/`` lives.

    Without ``output_root`` this is the patient folder itself (legacy in-folder layout).
    With it, output is rehomed to ``<output_root>/<patient_folder_name>/`` so a read-only
    patient folder stays untouched while the leaf name is reused verbatim (the resulting
    ``output_root`` is structurally a Database folder). See ADR 0003.
    """
    if output_root:
        return Path(output_root) / Path(patient_folder).name
    return Path(patient_folder)


def _get_output_folder(patient_folder: str | Path, output_root: str | Path | None = None) -> Path:
    """Return the ``clinical_scope_output/`` folder (see :func:`get_output_base`)."""
    return get_output_base(patient_folder, output_root) / cst.FOLDER_NAME_OUTPUT


def get_visualization_path(
    patient_folder: str | Path, output_root: str | Path | None = None
) -> Path:
    """Return the HTML visualization output path."""
    return _get_output_folder(patient_folder, output_root) / cst.DEFAULT_NAME_VISUALIZATION


def get_database_options_path(
    patient_folder: str | Path, output_root: str | Path | None = None
) -> Path:
    """Return the cached database options path."""
    return _get_output_folder(patient_folder, output_root) / cst.DEFAULT_NAME_DATABASE_OPTIONS


def get_patient_options_path(
    patient_folder: str | Path, output_root: str | Path | None = None
) -> Path:
    """Return the saved patient options path."""
    return _get_output_folder(patient_folder, output_root) / cst.DEFAULT_NAME_PATIENT_OPTIONS


def get_annotations_path(patient_folder: str | Path, output_root: str | Path | None = None) -> Path:
    """Return the annotations file path."""
    return _get_output_folder(patient_folder, output_root) / cst.ANNOTATION_FILE_NAME


def get_datasource_cache_path(
    patient_folder: str | Path, filename: str, output_root: str | Path | None = None
) -> Path:
    """Return ``<output_folder>/<filename>`` for parquet caches."""
    return _get_output_folder(patient_folder, output_root) / filename
