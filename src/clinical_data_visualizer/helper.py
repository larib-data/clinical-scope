import contextlib
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer.database_options_xlsx import xlsx_to_database_options

logger = logging.getLogger(__name__)


# ==================================================================================================
def time_it(func: Callable) -> Callable:
    """Decorator to measure and log execution time using import-style function identifier."""

    def arg_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()

        func_name = func.__name__
        try:
            module_name = func.__module__
        except AttributeError:
            module_name = "Unknown"

        logger.debug("%.3fs to run %s from %s", end - start, func_name, module_name)
        return result

    return arg_wrapper


# ==================================================================================================
def save_df(df: pd.DataFrame, path: str | Path) -> None:
    """
    Save *df* to *path* as CSV (``.csv``) or parquet (any other recognised extension).

    Args:
        df: DataFrame to save.
        path: Destination path.  Extension must be ``.csv`` or ``.parquet``.

    Raises:
        ValueError: If *path* has an unsupported extension.

    """
    path = Path(path)
    if path.suffix == ".csv":
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
    elif path.suffix == ".parquet":
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    else:
        msg = f"Unsupported file format '{path.suffix}'. Use '.csv' or '.parquet'."
        raise ValueError(msg)
    logger.info("Saved %d rows to %s", len(df), path)


# ==================================================================================================
def folder_name_matches_keywords(folder_name: str, keywords: list[str]) -> bool:
    """Check if *folder_name* contains every keyword (case-insensitive)."""
    name_lower = folder_name.lower()
    return all(kw.lower() in name_lower for kw in keywords)


# ==================================================================================================
def find_files(
    folder_path: Path,
    extensions: list[str],
    datasource_name: str,
    *,
    multi: bool = False,
    keywords: list[str] | None = None,
) -> list[Path] | Path | None:
    """
    Find data files in *folder_path*.

    When *multi* is ``True``, return **all** files matching *extensions*
    (sorted alphabetically), or ``None`` if none found.

    When *multi* is ``False``, return a **single** file (tiered disambiguation):

    1. Collect files matching *extensions* (or all files if none given).
    2. If one match, return it.
    3. Deduplicate by stem: when multiple extensions exist for the same stem,
       keep the most preferred one (earliest in *extensions*).
    4. If one stem remains, return it.
    5. If *keywords* is given, try each keyword in order to narrow the set;
       return immediately if exactly one match remains.
    6. Warn and return ``None`` if still ambiguous.
    """
    if multi:
        ext_set = {e.lower() for e in extensions}
        files = sorted(
            f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in ext_set
        )
        if not files:
            logger.debug("Could not find any %s files in folder '%s'", datasource_name, folder_path)
            return None
        logger.debug("Found %s: %s in folder %s", datasource_name, files, folder_path)
        return files

    # --- single-file mode ---
    if extensions:
        suffix_set = {s.lower() for s in extensions}
        matches = [
            f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in suffix_set
        ]
    else:
        matches = [f for f in folder_path.iterdir() if f.is_file()]

    if not matches:
        logger.warning("No file for '%s' found in folder '%s'.", datasource_name, folder_path)
        return None

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    # Deduplicate by stem: keep most preferred extension per stem
    if extensions:
        suffix_rank = {s.lower(): i for i, s in enumerate(extensions)}
        max_rank = len(extensions)
        by_stem: dict[str, Path] = {}
        for f in matches:
            stem = f.stem.lower()
            rank = suffix_rank.get(f.suffix.lower(), max_rank)
            if stem not in by_stem or rank < suffix_rank.get(
                by_stem[stem].suffix.lower(), max_rank
            ):
                by_stem[stem] = f
        matches = list(by_stem.values())

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    # Keyword filtering on stem (ordered by preference)
    if keywords:
        for kw in keywords:
            kw_lower = kw.lower()
            kw_matches = [f for f in matches if kw_lower in f.stem.lower()]
            if len(kw_matches) == 1:
                logger.info("Selected file for '%s': %s", datasource_name, kw_matches[0])
                return kw_matches[0]
            if kw_matches:
                matches = kw_matches

    logger.warning(
        "Multiple '%s' files found in '%s', could not resolve a unique match: %s",
        datasource_name,
        folder_path,
        [f.name for f in matches],
    )
    return None


# ==================================================================================================
def load_options(path: Path | None) -> dict:
    """Load JSON options from a file if the path exists."""
    if path and path.exists():
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    return {}


def build_patient_options(
    patient_folder: str | Path,
    path_patient_options: str | Path | None = None,
) -> dict:
    """
    Build a patient_options dict from a folder path and an optional JSON file.

    ``data_folder`` is always set from *patient_folder*.
    Any other keys present in the JSON file are preserved.
    """
    opts = load_options(Path(path_patient_options)) if path_patient_options else {}
    opts["data_folder"] = str(patient_folder)
    return opts


# ==================================================================================================
def load_database_options_from_path(path: Path) -> dict:
    """
    Load database options from a JSON or XLSX file.

    This is the canonical entry point for loading database options from a file
    path, supporting both formats accepted by the Dash UI file upload.

    Args:
        path: Path to a ``.json`` or ``.xlsx`` database options file.

    Returns:
        Parsed database options dictionary.

    Raises:
        ValueError: If the file extension is not supported.
        FileNotFoundError: If the path does not exist.

    """

    if not path.exists():
        msg = f"Database options file not found: {path}"
        raise FileNotFoundError(msg)

    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_options(path)
    if suffix == ".xlsx":
        return xlsx_to_database_options(path)
    msg = f"Unsupported file extension '{suffix}'. Expected .json or .xlsx."
    raise ValueError(msg)


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
    with contextlib.suppress(ValueError, TypeError):
        data.index = pd.to_datetime(data.index) + pd.to_timedelta(shift, unit="s")


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

    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning(
            "apply_timezone_to_dataframe: index is not a DatetimeIndex (%s), skipping.",
            type(df.index).__name__,
        )
        return df

    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone)

    return df


def find_datetime_col(columns: list[str]) -> str | None:
    """Find the best datetime column by priority: exact matches, then partial matches."""
    lower_map = {c.lower(): c for c in columns}

    # Priority 1: exact matches (highest to lowest priority)
    for name in ["datetime", "date_datetime", "time_datetime", "timestamp", "date"]:
        if name in lower_map:
            return lower_map[name]

    # Priority 2: contains "datetime"
    for col in columns:
        if "datetime" in col.lower():
            return col

    # Priority 3: contains "timestamp"
    for col in columns:
        if "timestamp" in col.lower():
            return col

    # Priority 4: contains "date"
    for col in columns:
        if "date" in col.lower():
            return col

    # Priority 5: contains "time" (but not "timeout", "timer", etc.)
    for col in columns:
        if re.search(r"time(?!out|r|stamp)", col.lower()):
            return col

    return None


def load_csv_with_datetime_index(
    file_path: str | Path, dt_col: str | None = None, **kwargs
) -> pd.DataFrame:
    # First pass: peek at columns
    df = pd.read_csv(file_path, nrows=0)

    if dt_col is None:
        dt_col = find_datetime_col(df.columns.tolist())

    if dt_col is not None:
        df = pd.read_csv(file_path, index_col=dt_col, parse_dates=True, **kwargs)
    else:
        # Fall back to first column and hope for the best
        df = pd.read_csv(file_path, index_col=0, parse_dates=True, **kwargs)

    return df
