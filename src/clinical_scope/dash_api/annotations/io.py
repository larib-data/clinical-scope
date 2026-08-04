"""
Annotation persistence: save / load JSON to the patient folder.

The annotation file is always named ``annotations.json`` and lives in the patient's
``clinical_scope_output/`` folder, alongside the parquet cache.

File format: a JSON object with an ``"annotations"`` key containing a list of
annotation dicts.  This envelope allows future extension with additional fields
(e.g. ``"version"``).

Group metadata is not persisted: on load, groups are derived from the ``group_id`` /
``group_name`` fields embedded in each annotation.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import clinical_scope.constants as cst
from clinical_scope.dash_api.annotations.model import Annotation
from clinical_scope.io.paths import get_annotations_path

if TYPE_CHECKING:
    from pathlib import Path

ANNOTATION_KEY = cst.ANNOTATION_KEY

logger = logging.getLogger(__name__)

ANNOTATION_FILE_NAME = cst.ANNOTATION_FILE_NAME


def save_annotations(annotations: list[Annotation], patient_folder: str | Path) -> Path:
    """
    Write annotations to ``<patient_folder>/clinical_scope_output/annotations.json``.

    Returns the path that was written.
    """
    path = get_annotations_path(patient_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            {ANNOTATION_KEY: [annotation.to_dict() for annotation in annotations]},
            file,
            indent=2,
            ensure_ascii=False,
        )
    logger.info("Saved %d annotation(s) to %s", len(annotations), path)
    return path


# ==================================================================================================
# Internal: core annotation loading logic
# ==================================================================================================


def _load_annotations_from_path(path: Path) -> list[Annotation]:
    """
    Load annotations from a JSON file at the given path.

    Returns an empty list when the file does not exist or cannot be parsed; malformed
    individual records are skipped rather than raising.

    Internal helper — callers should use the package-level :func:`load_annotations`
    (wrapper.py), which supports multi-source auto-detection.
    """
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as file:
            raw = json.load(file)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load annotations from %s", path, exc_info=True)
        return []

    if not isinstance(raw, dict) or ANNOTATION_KEY not in raw:
        logger.warning(
            "Annotations file %s does not contain an '%s' key, got %s",
            path,
            ANNOTATION_KEY,
            type(raw).__name__,
        )
        return []

    annotation_dicts = raw[ANNOTATION_KEY]
    if not isinstance(annotation_dicts, list):
        logger.warning(
            "Annotations file %s 'annotations' key is not a list, got %s",
            path,
            type(annotation_dicts).__name__,
        )
        return []

    annotations = []
    for index, annotation_dict in enumerate(annotation_dicts):
        try:
            annotations.append(Annotation.from_dict(annotation_dict))
        except Exception:  # noqa: BLE001
            logger.warning(
                "Skipping malformed annotation record #%d in %s", index, path, exc_info=True
            )
    logger.info("Loaded %d annotation(s) from %s", len(annotations), path)
    return annotations
