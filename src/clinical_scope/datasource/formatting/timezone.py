"""
Timezone and time conversion utilities for clinical data processing.

This module provides functions for converting time representations,
shifting timestamps, and filtering data by time ranges.

Also includes display formatting helpers that were previously in datasource_base.py.
"""

import contextlib
import logging

import numpy as np
import pandas as pd

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


# ==================================================================================================
def to_float_seconds(
    x: np.ndarray | pd.DatetimeIndex | pd.Series,
) -> np.ndarray | pd.DatetimeIndex | pd.Series:
    """Convert time data to float seconds (epoch) for comparison operations."""
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
    """Shift the DataFrame index by a given number of seconds (in-place)."""
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
    display_timezone: str | None = None,
) -> pd.DataFrame:
    """Filter data between time_start and time_end timestamps using a hardcoded library timezone."""
    if not pd.api.types.is_datetime64_any_dtype(data.index):
        logger.warning("Data index is not datetime. Skipping filtering.")
        return data

    filtered = data.copy()
    tz = display_timezone or cst.DISPLAY_TIMEZONE

    # Ensure index is in the library timezone
    if filtered.index.tz is None:
        msg = "Dataframe 'data' index should be timezone-aware"
        raise ValueError(msg)
    filtered.index = filtered.index.tz_convert(cst.LIBRARY_TZ)

    # Localize or convert input timestamps
    if time_start is not None:
        if time_start.tzinfo is None:
            time_start = time_start.tz_localize(tz)
        time_start = time_start.tz_convert(cst.LIBRARY_TZ)

    if time_end is not None:
        if time_end.tzinfo is None:
            time_end = time_end.tz_localize(tz)
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


# ==================================================================================================
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


# ==================================================================================================
def loop_time_to_display_strings(
    utc_float_seconds: np.ndarray,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    display_timezone: str | None = None,
) -> np.ndarray:
    """
    Convert an array of UTC epoch float seconds to display-timezone datetime strings.

    Used for loop hover customdata and slider-callback customdata so both come
    from a single, testable conversion path.
    """
    tz = display_timezone or cst.DISPLAY_TIMEZONE
    dt_display = pd.to_datetime(utc_float_seconds, unit="s", utc=True).tz_convert(tz)
    return np.array(dt_display.strftime(fmt))


# ==================================================================================================
def to_naive_display_ts(ts_str: str, display_timezone: str | None = None) -> str:
    """
    Convert a tz-aware ISO timestamp to a naive string in display-TZ wall-clock time.

    Plotly trace x-data is stored as timezone-naive datetime64 (wall-clock in display TZ,
    produced by :func:`change_ndarray_timezone`).  Annotation x values are stored as tz-aware
    ISO strings.  This converts them to the same naive format so Plotly aligns shapes and
    annotations correctly with the trace data.  Non-datetime values (e.g. loop-plot numeric x)
    are returned unchanged.
    """
    tz = display_timezone or cst.DISPLAY_TIMEZONE
    try:
        ts = pd.Timestamp(ts_str)
    except (ValueError, TypeError, OverflowError):
        # ts_str is not a parseable datetime (e.g. a numeric loop-plot x value) — expected path.
        return ts_str
    try:
        if pd.isna(ts) or ts.tzinfo is None:
            return ts_str
        return ts.tz_convert(tz).tz_localize(None).isoformat()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not convert annotation timestamp %r to display timezone %r",
            ts_str,
            tz,
            exc_info=True,
        )
        return ts_str


# ==================================================================================================
def apply_timezone_to_dataframe(
    df: pd.DataFrame,
    database_options_specific: dict,
    default_timezone: str,
    options_module=None,  # noqa: ANN001
) -> pd.DataFrame:
    """Apply timezone to DataFrame index if not already set."""
    override_timezone = None

    if options_module and hasattr(options_module, "DatabaseOptionsAdditionalInformations"):
        additional_info_class = options_module.DatabaseOptionsAdditionalInformations
        if hasattr(additional_info_class, "TIMEZONE"):
            override_timezone = database_options_specific.get(
                cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
            ).get(additional_info_class.TIMEZONE)

    timezone = override_timezone if override_timezone is not None else default_timezone

    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning(
            "apply_timezone_to_dataframe: index is not a DatetimeIndex (%s), skipping.",
            type(df.index).__name__,
        )
        return df

    if df.index.tz is not None:
        if override_timezone is not None and override_timezone != str(df.index.tz):
            source = getattr(options_module, "DATASOURCE_NAME", "unknown")
            logger.warning(
                "[%s] Timezone override %r (from database options) ignored: "
                "data is already tz-aware (%s).",
                source,
                override_timezone,
                df.index.tz,
            )
        return df

    df.index = df.index.tz_localize(timezone)
    return df


# ==================================================================================================
# Display formatting helpers (moved from datasource_base.py)
# ==================================================================================================

_TS_FMT = "%y-%m-%d %H:%M:%S %Z"  # compact, 2-digit year, timezone abbreviation


def fmt_ts(ts: object) -> str:
    """Format a pandas Timestamp (or datetime-like) to a compact, human-readable string."""
    try:
        return ts.strftime(_TS_FMT).rstrip()
    except Exception:  # noqa: BLE001
        return str(ts)


def _to_display_tz(df: pd.DataFrame, display_timezone: str | None = None) -> pd.DataFrame:
    """
    Return a shallow copy of *df* with its index converted to the display timezone.

    Used in :meth:`DataSourceBase.inspect` so that reported timestamps match
    the timezone shown in the Dash plots.  The copy is shallow (data arrays are
    shared) so it is cheap even for wide, high-frequency DataFrames.
    If the index is tz-naive or not a DatetimeIndex, *df* is returned unchanged.
    """
    if not (isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None):
        return df
    tz = display_timezone or cst.DISPLAY_TIMEZONE
    result = df.copy(deep=False)
    result.index = df.index.tz_convert(tz)
    return result


def _date_range(df: pd.DataFrame) -> tuple[str, str] | None:
    """Return (compact_min, compact_max) of the DataFrame index, or None if empty."""
    if df.empty:
        return None
    try:
        return (fmt_ts(df.index.min()), fmt_ts(df.index.max()))
    except Exception:  # noqa: BLE001
        return None


def _first_last_timestamp(df: pd.DataFrame, col: str) -> tuple[str | None, str | None]:
    """Return (first, last) compact timestamp strings for valid (non-NaN) values in a column."""
    if col not in df.columns:
        return None, None
    valid_index = df.index[df[col].notna()]
    if valid_index.empty:
        return None, None
    return fmt_ts(valid_index.min()), fmt_ts(valid_index.max())
