# === Imports === #
import json
import logging
from pathlib import Path
from typing import Any

# Cache path — contains only signal metadata (labels, colors, units, field mappings), no PHI.
_CACHED_DB_OPTIONS_PATH = Path.home() / ".clinical_scope" / "last_database_options.json"

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def get_cached_db_options_path() -> Path:
    return _CACHED_DB_OPTIONS_PATH


def save_cached_db_options(data: dict[str, Any]) -> None:
    try:
        save_json(data, _CACHED_DB_OPTIONS_PATH)
    except PermissionError:
        logger.exception("Could not save for cache the DB options")


def load_cached_db_options() -> dict[str, Any] | None:
    if _CACHED_DB_OPTIONS_PATH.exists():
        try:
            with _CACHED_DB_OPTIONS_PATH.open() as f:
                return json.load(f)
        except Exception:
            logger.exception("Failed to load cached database options:")
    return None


# ==================================================================================================
def save_json(data_json: dict[str, Any], json_path: Path) -> None:
    try:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        with Path.open(json_path, "w") as f:
            json.dump(data_json, f, indent=4, default=str)
    except Exception:
        logger.exception("❌ Error saving JSON file:")


# ==================================================================================================
# Normalise a pasted path: drop wrapping quotes/whitespace, expand ~ (backslashes kept).
def format_path(path: str) -> Path:
    path = path.strip()
    path = path.replace('"', "")
    path = path.replace("'", "")
    return Path(path.strip()).expanduser()
