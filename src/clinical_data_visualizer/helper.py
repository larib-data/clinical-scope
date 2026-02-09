import json
import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

import clinical_data_visualizer.constants as cst

logger = logging.getLogger(__name__)


# ==================================================================================================
def time_it(func):
    """Decorator to measure and log execution time using import-style function identifier."""

    def arg_wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()

        func_name = func.__name__
        try:
            module_name = func.__module__
        except Exception:
            module_name = "Unknown"

        logger.debug("⏳ %.3fs to run %s from %s", end - start, func_name, module_name)
        return result

    return arg_wrapper


# ==================================================================================================
def find_folder(folder_path: Path, keyword: str, description: str = "folder") -> Path | None:
    """
    Find a subfolder in `folder_path` whose name contains `keyword`.

    Returns the folder path if exactly one match is found.
    Returns None and logs warnings if not found or ambiguous.
    """
    matches = [f for f in folder_path.iterdir() if f.is_dir() and keyword in f.name.lower()]

    if not matches:
        logger.warning(
            "⚠️ No %s with keyword '%s' found in folder '%s'.", description, keyword, folder_path
        )
        return None

    if len(matches) > 1:
        logger.warning(
            "⚠️ Multiple %s with keyword '%s' found in folder '%s'. Cannot determine which to use.",
            description,
            keyword,
            folder_path,
        )
        return None

    selected = matches[0]
    logger.info("📁 Selected %s: %s", description, selected)
    return selected


# ==================================================================================================
def find_file(
    folder_path: Path,
    keyword: str,
    data_source_name: str,
    preferred_suffixes: list[str] | None = None,
) -> Path | None:
    """
    Find a file in `folder_path` matching `keyword`.

    Returns selected Path or None, and logs warnings if not found or ambiguous.
    """
    matches = [f for f in folder_path.iterdir() if keyword in f.name.lower()]

    if not matches:
        logger.warning(
            "⚠️ No file for '%s' found in folder '%s' (keyword='%s').",
            data_source_name,
            folder_path,
            keyword,
        )
        return None

    if len(matches) == 1:
        selected_path = matches[0]
    elif preferred_suffixes:
        selected_path = None
        for suffix in preferred_suffixes:
            filtered = [f for f in matches if f.suffix.lower() == suffix.lower()]
            if len(filtered) == 1:
                selected_path = filtered[0]
                break

        if selected_path is None:
            logger.warning(
                "⚠️ Multiple '%s' files found in '%s' (keyword='%s'), "
                "and suffix preferences could not resolve a unique match.",
                data_source_name,
                folder_path,
                keyword,
            )
            return None
    else:
        logger.warning(
            "⚠️ Multiple '%s' files found in '%s' (keyword='%s'), "
            "and no suffix preference provided.",
            data_source_name,
            folder_path,
            keyword,
        )
        return None

    logger.info("📄 Selected file for '%s': %s", data_source_name, selected_path)
    return selected_path


# ==================================================================================================
def find_file_list(
    folder_path: Path, extension: str | list[str], description: str
) -> list[Path] | None:
    """
    Find and return all files in `folder_path` ending with `extension`, sorted alphabetically. Logs results using `description`.

    folder_path: Folder to search in.
    extension: File extension pattern (e.g., ".csv") or list of extensions (e.g., [".csv", ".parquet"])
    description: Human-readable description for logging.

    Return: Sorted list of matching Path objects, or None if none found.

    """  # noqa: E501
    # Normalize extension to always be a list
    extensions = [extension] if isinstance(extension, str) else extension

    # Collect all matching files across all extensions
    files = []
    for ext in extensions:
        files.extend(folder_path.glob(f"*{ext}"))

    # Sort alphabetically
    files = sorted(files)

    if not files:
        logger.debug("Could not find any %s in folder '%s'", description, folder_path)
        return None
    logger.debug("Found %s: %s in folder %s", description, files, folder_path)
    return files


# ==================================================================================================
def load_options(path: Path | None) -> dict:
    """Load JSON options from a file if the path exists."""
    if path and path.exists():
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    return {}


# ==================================================================================================
def wrap_label(text: str, max_line_length: int = 12, break_chars: str = r"[ \-_]") -> str:
    """
    Wrap a long label into multiple HTML lines (<br>) at allowed break characters.
    Used for axis titles or legends in Plotly figures.

    Args:
        text: The text to wrap.
        max_line_length: Maximum characters per line before wrapping.
        break_chars: Regex pattern of allowed break characters (default: space, hyphen, underscore).

    Returns:
        Wrapped text string with <br> line breaks.

    """
    tokens = re.split(f"({break_chars})", text)
    lines = []
    current_line = ""

    for token in tokens:
        if len(current_line + token) <= max_line_length:
            current_line += token
        else:
            if current_line.strip():
                lines.append(current_line.strip())
            current_line = token

    if current_line.strip():
        lines.append(current_line.strip())

    return "<br>".join(lines)


# ==================================================================================================
def print_out_figure(path_output: Path, fig_list: list) -> None:
    with Path.open(path_output, "w") as file_out:
        for fig in fig_list:
            file_out.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))


# ==================================================================================================
def to_float_seconds(
    x: np.ndarray | pd.DatetimeIndex | pd.Series,
) -> np.ndarray | pd.DatetimeIndex | pd.Series:
    if np.issubdtype(x.dtype, np.number):
        return x.astype(np.float64)

    if isinstance(x, pd.DatetimeIndex):
        if x.tz is not None:
            x = x.tz_convert(cst.LIBRARY_TZ)
        return x.view(np.int64) / 1e9

    if isinstance(x, (pd.Series, np.ndarray)):
        if np.issubdtype(x.dtype, np.datetime64):
            return x.astype("datetime64[ns]").astype(np.float64) / 1e9
        if np.issubdtype(x.dtype, object):
            # Convert Timestamps to library tz before converting to np.datetime64 (just for consistency then during comparison)  # noqa: E501
            x_ns = np.array(
                [ts.tz_convert(cst.LIBRARY_TZ).value if ts.tzinfo else ts.value for ts in x],
                dtype=np.int64,
            )
            return x_ns / 1e9

    msg = f"Unsupported type for time conversion: {type(x)}"
    raise TypeError(msg)


# ==================================================================================================
def shift_data_by_seconds(data: pd.DataFrame, shift: float) -> None:
    if shift == 0.0:
        return
    if pd.api.types.is_datetime64_any_dtype(data.index):
        data.index = data.index + pd.to_timedelta(shift, unit="s")
        return
    try:
        data.index = pd.to_datetime(data.index) + pd.to_timedelta(shift, unit="s")
        return
    except Exception:
        return


# ==================================================================================================
def filter_data_by_timestamps(
    data: pd.DataFrame,
    time_start: pd.Timestamp | None,
    time_end: pd.Timestamp | None,
    filter_date: bool = True,
) -> pd.DataFrame:
    """Filter data between time_start and time_end timestamps using a hardcoded library timezone."""
    if not pd.api.types.is_datetime64_any_dtype(data.index):
        logger.warning("Data index is not datetime. Skipping filtering.")
        return data

    filtered = data.copy()

    # Ensure index is in the library timezone
    if filtered.index.tz is None:
        msg = "Dataframe 'data' index should be timezone-aware"
        raise ValueError(msg)
    filtered.index = filtered.index.tz_convert(cst.LIBRARY_TZ)

    # Localize or convert input timestamps
    if time_start is not None:
        if time_start.tzinfo is None:
            time_start = time_start.tz_localize(cst.DISPLAY_TIMEZONE)
        time_start = time_start.tz_convert(cst.LIBRARY_TZ)

    if time_end is not None:
        if time_end.tzinfo is None:
            time_end = time_end.tz_localize(cst.DISPLAY_TIMEZONE)
        time_end = time_end.tz_convert(cst.LIBRARY_TZ)

    if not filter_date:
        idx_times = filtered.index.time
        if time_start is not None:
            start_time = time_start.time()
            filtered = filtered[[t >= start_time for t in idx_times]]
        if time_end is not None:
            end_time = time_end.time()
            filtered = filtered[[t <= end_time for t in filtered.index.time]]
    else:
        if time_start is not None:
            filtered = filtered[filtered.index >= time_start]
        if time_end is not None:
            filtered = filtered[filtered.index <= time_end]

    return filtered


def change_ndarray_timezone(
    array: np.ndarray, array_timezone: str, new_timezone: str
) -> tuple[np.ndarray, str]:
    """
    Adjust a timezone-naive np.ndarray of datetime64[ns] values to appear as if in new_timezone.

    Args:
        array: Timezone-naive np.ndarray of datetime64[ns] values.
        array_timezone: Original timezone of the array (e.g., "UTC", "Europe/Paris").
        new_timezone: Target timezone for display (e.g., "America/New_York").

    Returns:
        tuple: (adjusted_array, new_timezone)
            - adjusted_array: The array with timestamps adjusted to appear as if in new_timezone.
            - new_timezone: The target timezone (for reference).

    """
    if array_timezone is None or array_timezone == new_timezone:
        return array, new_timezone

    dt_index = pd.to_datetime(array).tz_localize(array_timezone)
    dt_index_new_tz = dt_index.tz_convert(new_timezone)
    adjusted_array = dt_index_new_tz.tz_localize(None).to_numpy()

    return adjusted_array, new_timezone


def get_column_name_from_pattern(columns: pd.Index | list[str], pattern: str) -> str | None:
    if pattern[-1] == "*":
        prefix = pattern.rstrip("*")
        matching_columns = [col for col in columns if col.startswith(prefix)]

        if len(matching_columns) == 1:
            return matching_columns[0]
        if len(matching_columns) == 0:
            logger.warning("No column found in dataframe from the pattern %s", pattern)
        else:
            logger.warning(
                "More than one column found in dataframe with the pattern %s. -> Ignored", pattern
            )
        return None
    # Could not find any pattern, consider there was none
    return pattern


def apply_timezone_to_dataframe(
    df: pd.DataFrame,
    database_options_specific: dict,
    default_timezone: str,
    options_module=None,  # noqa: ANN001
) -> pd.DataFrame:
    """Apply timezone to DataFrame index if not already set."""
    timezone = default_timezone

    if options_module and hasattr(options_module, "DatabaseOptionsAdditionalInformations"):
        additional_info_class = options_module.DatabaseOptionsAdditionalInformations
        if hasattr(additional_info_class, "TIMEZONE"):
            timezone = database_options_specific.get(
                cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
            ).get(
                additional_info_class.TIMEZONE,
                default_timezone,
            )

    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone)

    return df
