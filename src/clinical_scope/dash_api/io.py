"""Patient options persistence: load patient_options.json from the patient folder."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from clinical_scope.io.paths import get_patient_options_path

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def load_patient_options(
    patient_folder: str | Path, output_root: str | Path | None = None
) -> dict | None:
    """
    Load patient_options.json from the patient's clinical_scope_output/ folder.

    When ``output_root`` is set the file is read from
    ``<output_root>/<patient_folder_name>/clinical_scope_output/`` instead of inside the
    patient folder (mirrors how it was written under redirection — see ADR 0003).

    Returns None if the file does not exist (expected: no history yet).
    Raises ValueError if the file exists but cannot be parsed or is not a dict.
    Extra or missing fields relative to the current database options are
    left to the caller to handle — this function returns the raw dict as-is.
    """
    path = get_patient_options_path(patient_folder, output_root)
    if not path.exists():
        logger.info("No saved patient options at %s", path)
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        msg = f"Cannot read patient options from {path}: {e}"
        raise ValueError(msg) from e
    if not isinstance(data, dict):
        msg = f"Patient options file {path} is not a JSON object (got {type(data).__name__})"
        raise TypeError(msg)
    return data
