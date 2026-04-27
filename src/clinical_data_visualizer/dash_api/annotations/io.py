"""
Annotation persistence: save / load JSON to the patient folder.

The annotation file is always named ``annotations.json`` and placed directly
inside the patient data folder (next to the datasource sub-folders and the
``cdv_visu/`` parquet cache).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer.dash_api.annotations.model import Annotation

logger = logging.getLogger(__name__)

ANNOTATION_FILE_NAME = cst.ANNOTATION_FILE_NAME


def get_annotation_path(patient_folder: str | Path) -> Path:
    """Return the expected path for the annotation file."""
    return Path(patient_folder) / ANNOTATION_FILE_NAME


def save_annotations(annotations: list[Annotation], patient_folder: str | Path) -> Path:
    """
    Write annotations to ``<patient_folder>/annotations.json``.

    Returns the path that was written.
    """
    path = get_annotation_path(patient_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [a.to_dict() for a in annotations]
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Saved %d annotation(s) to %s", len(annotations), path)
    return path


def load_annotations(patient_folder: str | Path) -> list[Annotation]:
    """
    Load annotations from ``<patient_folder>/annotations.json``.

    Returns an empty list if the file does not exist or cannot be parsed.
    """
    path = get_annotation_path(patient_folder)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load annotations from %s", path, exc_info=True)
        return []
    else:
        annotations = []
        for i, d in enumerate(raw):
            try:
                annotations.append(Annotation.from_dict(d))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed annotation record #%d in %s", i, path, exc_info=True
                )
        logger.info("Loaded %d annotation(s) from %s", len(annotations), path)
        return annotations
