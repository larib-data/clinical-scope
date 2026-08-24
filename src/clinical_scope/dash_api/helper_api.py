# === Imports === #
import json
import logging
from pathlib import Path
from typing import Any

import clinical_scope.constants as cst

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def get_cached_database_options_path() -> Path:
    """Return the cache path for database options (signal metadata only, no PHI)."""
    return Path.home() / cst.CLINICAL_SCOPE_DIR_NAME / cst.CACHED_DATABASE_OPTIONS_FILE_NAME


def save_cached_database_options(data: dict[str, Any]) -> None:
    try:
        save_json(data, get_cached_database_options_path())
    except PermissionError:
        logger.exception("Could not save for cache the DB options")


def load_cached_database_options() -> dict[str, Any] | None:
    path = get_cached_database_options_path()
    if path.exists():
        try:
            with path.open() as file:
                return json.load(file)
        except Exception:
            logger.exception("Failed to load cached database options:")
    return None


# ==================================================================================================
def get_user_options_path() -> Path:
    """Return the cache path for the global user options (signal-free, no PHI)."""
    return Path.home() / cst.CLINICAL_SCOPE_DIR_NAME / cst.USER_OPTIONS_FILE_NAME


def iter_user_option_fields() -> list[Any]:
    """Return the UserOptions nested schema classes (those exposing a NAME)."""
    return [
        getattr(cst.UserOptions, attr)
        for attr in dir(cst.UserOptions)
        if hasattr(getattr(cst.UserOptions, attr), "NAME")
    ]


def user_options_defaults() -> dict[str, Any]:
    """Build the default user_options dict from the UserOptions schema classes."""
    return {field.NAME: field.DEFAULT for field in iter_user_option_fields()}


def save_user_options(data: dict[str, Any]) -> None:
    """Persist the user_options dict to its cache path (best-effort)."""
    try:
        save_json(data, get_user_options_path())
    except PermissionError:
        logger.exception("Could not save the user options")


def load_user_options() -> dict[str, Any]:
    """Load user options, filling any missing/unknown keys from schema defaults."""
    options = user_options_defaults()
    path = get_user_options_path()
    if path.exists():
        try:
            with path.open() as file:
                stored = json.load(file)
            options.update({key: value for key, value in stored.items() if key in options})
        except Exception:
            logger.exception("Failed to load user options:")
    return options


# ==================================================================================================
def save_json(data_json: dict[str, Any], json_path: Path) -> None:
    try:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        with Path.open(json_path, "w") as file:
            json.dump(data_json, file, indent=4, default=str)
    except Exception:
        logger.exception("❌ Error saving JSON file:")


# ==================================================================================================
def format_path(path: str) -> Path:
    """
    Normalise a pasted path.

    Drops wrapping quotes and whitespace and expands ``~``; backslashes are kept as-is.
    """
    path = path.strip()
    path = path.replace('"', "")
    path = path.replace("'", "")
    return Path(path.strip()).expanduser()
