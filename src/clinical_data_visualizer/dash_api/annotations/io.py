"""
Annotation persistence: save / load JSON to the patient folder.

The annotation file is always named ``annotations.json`` and placed directly
inside the patient data folder (next to the datasource sub-folders and the
``cdv_visu/`` parquet cache).

File format: a bare JSON list of annotation dicts.

Group metadata is runtime-only (held in ``annotation-groups-store``); it is
not persisted.  On load, groups are derived from the ``group_id`` / ``group_name``
fields embedded in each annotation.
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
    Write annotations to ``<patient_folder>/annotations.json`` as a bare JSON list.

    Returns the path that was written.
    """
    path = get_annotation_path(patient_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump([a.to_dict() for a in annotations], fh, indent=2, ensure_ascii=False)
    logger.info("Saved %d annotation(s) to %s", len(annotations), path)
    return path


def load_annotations(patient_folder: str | Path) -> list[Annotation]:
    """
    Load annotations from ``<patient_folder>/annotations.json``.

    Returns an empty list when the file does not exist or cannot be parsed.
    Accepts both bare-list files and the legacy ``{"annotations": [...]}`` envelope.
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

    ann_dicts = raw.get("annotations", []) if isinstance(raw, dict) else raw

    annotations = []
    for i, d in enumerate(ann_dicts):
        try:
            annotations.append(Annotation.from_dict(d))
        except Exception:  # noqa: BLE001
            logger.warning("Skipping malformed annotation record #%d in %s", i, path, exc_info=True)
    logger.info("Loaded %d annotation(s) from %s", len(annotations), path)
    return annotations
