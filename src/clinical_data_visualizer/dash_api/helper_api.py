# === Imports === #
import json
import logging
from pathlib import Path
from typing import Any

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def save_json(data_json: dict[str, Any], json_path: Path):
    try:
        with Path.open(json_path, "w") as f:
            json.dump(data_json, f, indent=4, default=str)
    except Exception:
        logger.exception("❌ Error saving JSON file:")


# ==================================================================================================
# a bit like quick fixes, for windows, for know place at the code where we want a function that tolerate '"' and delete them  # noqa: E501
def format_path(path: str) -> Path:
    path = path.replace('"', "")
    path = path.replace("'", "")
    return Path(path)


# ==================================================================================================
def load_annotations(folder_visu_path):
    path = Path(folder_visu_path) / "annotations.json"
    if path.exists():
        with path.open() as f:
            return json.load(f)
    return {"by_figure": {}}


# ==================================================================================================
def is_user_annotation(ann: dict) -> bool:
    """
    Heuristic to detect user-created annotation vs system annotation (subplot titles).
    """
    # User annotations have x and y in data coordinates (numbers), not 'paper'
    if (
        ann.get("xref") == "paper"
        and ann.get("yref") == "paper"
        and not ann.get("showarrow")
        and ann.get("font", {}).get("size") == 16
    ):
        return False
    return not ("x" not in ann or "y" not in ann)
