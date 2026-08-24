"""
Timezone and time conversion utilities for clinical data processing.

Covers conversion between time representations, timestamp shifting, time-range filtering,
and the display formatting helpers built on them.
"""

import contextlib
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


# ==================================================================================================
def resolve_display_timezone(display_timezone: str | None) -> str:
    """
    Return a usable IANA timezone name, falling back to ``cst.DISPLAY_TIMEZONE``.

    An absent value is the normal case and stays silent; a present-but-invalid name
    (hand-edited file, programmatic call) is logged rather than left to raise deep inside
    pandas/zoneinfo.
    """
    if not display_timezone:
        return cst.DISPLAY_TIMEZONE
    try:
        ZoneInfo(display_timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        logger.warning(
            "display_timezone %r is not a valid IANA name; using %s",
            display_timezone,
            cst.DISPLAY_TIMEZONE,
        )
        return cst.DISPLAY_TIMEZONE
    return display_timezone


# ==================================================================================================
def to_float_seconds(
    time_values: np.ndarray | pd.DatetimeIndex | pd.Series,
) -> np.ndarray | pd.DatetimeIndex | pd.Series:
    """Convert time data to float seconds (epoch) for comparison operations."""
    if np.issubdtype(time_values.dtype, np.number):
        return time_values.astype(np.float64)

    if isinstance(time_values, pd.DatetimeIndex):
        if time_values.tz is not None:
            time_values = time_values.tz_convert(cst.LIBRARY_TZ)
        return time_values.view(np.int64) / 1e9

    if isinstance(time_values, (pd.Series, np.ndarray)):
        if np.issubdtype(time_values.dtype, np.datetime64):
            return time_values.astype("datetime64[ns]").astype(np.float64) / 1e9
        if np.issubdtype(time_values.dtype, object):
            # Convert to library tz first so later comparisons are on a consistent tz.
            epoch_ns = np.array(
                [
                    timestamp.tz_convert(cst.LIBRARY_TZ).value
                    if timestamp.tzinfo
                    else timestamp.value
                    for timestamp in time_values
                ],
                dtype=np.int64,
            )
            return epoch_ns / 1e9

    msg = f"Unsupported type for time conversion: {type(time_values)}"
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

    # Shallow copy since below only rebinds the index or row-filters, never mutates columns.
    filtered = data.copy(deep=False)
    resolved_timezone = resolve_display_timezone(display_timezone)

    if filtered.index.tz is None:
        msg = "Dataframe 'data' index should be timezone-aware"
        raise ValueError(msg)
    filtered.index = filtered.index.tz_convert(cst.LIBRARY_TZ)

    if time_start is not None:
        if time_start.tzinfo is None:
            time_start = time_start.tz_localize(resolved_timezone)
        time_start = time_start.tz_convert(cst.LIBRARY_TZ)

    if time_end is not None:
        if time_end.tzinfo is None:
            time_end = time_end.tz_localize(resolved_timezone)
        time_end = time_end.tz_convert(cst.LIBRARY_TZ)

    if not filter_date:
        index_times = filtered.index.time
        if time_start is not None:
            start_time = time_start.time()
            filtered = filtered[[time_value >= start_time for time_value in index_times]]
        if time_end is not None:
            end_time = time_end.time()
            filtered = filtered[[time_value <= end_time for time_value in filtered.index.time]]
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

    """
    if array_timezone is None or array_timezone == new_timezone:
        return array, new_timezone

    datetime_index = pd.to_datetime(array).tz_localize(array_timezone)
    datetime_index_new_tz = datetime_index.tz_convert(new_timezone)
    adjusted_array = datetime_index_new_tz.tz_localize(None).to_numpy()

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
    resolved_timezone = resolve_display_timezone(display_timezone)
    display_datetimes = pd.to_datetime(utc_float_seconds, unit="s", utc=True).tz_convert(
        resolved_timezone
    )
    return np.array(display_datetimes.strftime(fmt))


# ==================================================================================================
def _try_parse_timestamp(ts_str: str) -> pd.Timestamp | None:
    """Parse *ts_str*, or return ``None`` for anything not a real timestamp (NaT included)."""
    try:
        timestamp = pd.Timestamp(ts_str)
    except (ValueError, TypeError, OverflowError):
        # e.g. a numeric loop-plot x value or mid-typed form text — expected, not an error.
        return None
    return None if pd.isna(timestamp) else timestamp


# ==================================================================================================
def to_naive_display_ts(ts_str: str, display_timezone: str | None = None, sep: str = "T") -> str:
    """
    Convert a tz-aware ISO timestamp to a naive string in display-TZ wall-clock time.

    Plotly trace x-data is stored as timezone-naive datetime64 (wall-clock in display TZ,
    produced by :func:`change_ndarray_timezone`).  Annotation x values are stored as tz-aware
    ISO strings.  This converts them to the same naive format so Plotly aligns shapes and
    annotations correctly with the trace data.  Non-datetime values (e.g. loop-plot numeric x)
    are returned unchanged.

    ``sep`` selects the date/time separator (default ``"T"``); the patient-options form
    passes ``sep=" "`` to match its ``PLACEHOLDER_TIMESTAMP`` spelling.
    """
    timestamp = _try_parse_timestamp(ts_str)
    if timestamp is None or timestamp.tzinfo is None:
        return ts_str
    resolved_timezone = resolve_display_timezone(display_timezone)
    try:
        return timestamp.tz_convert(resolved_timezone).tz_localize(None).isoformat(sep=sep)
    except Exception:
        logger.warning(
            "Could not convert annotation timestamp %r to display timezone %r",
            ts_str,
            resolved_timezone,
            exc_info=True,
        )
        return ts_str


# ==================================================================================================
def to_aware_display_ts(ts_str: str, display_timezone: str | None = None) -> str:
    """
    Convert a naive wall-clock string (as typed in the display timezone) to a tz-aware ISO string.

    Inverse of :func:`to_naive_display_ts`; used when saving patient-options datetime
    filters, since the form only ever holds naive text but the saved file stores an instant.

    Idempotent: an already tz-aware input (e.g. a pasted offset) passes through unchanged, as
    do non-datetime or unparseable values (empty field, mid-typing).
    """
    timestamp = _try_parse_timestamp(ts_str)
    if timestamp is None or timestamp.tzinfo is not None:
        return ts_str
    resolved_timezone = resolve_display_timezone(display_timezone)
    try:
        return timestamp.tz_localize(resolved_timezone).isoformat()
    except Exception:
        logger.warning(
            "Could not localize timestamp %r to display timezone %r",
            ts_str,
            resolved_timezone,
            exc_info=True,
        )
        return ts_str


# ==================================================================================================
def _resolve_effective_tz(
    database_options_specific: dict,
    options_module,  # noqa: ANN001
    default_timezone: str,
) -> str:
    """Return the database_options timezone override if set, else default_timezone."""
    override = None
    if options_module and hasattr(options_module, "DatabaseOptionsAdditionalInformations"):
        additional_info_class = options_module.DatabaseOptionsAdditionalInformations
        if hasattr(additional_info_class, "TIMEZONE"):
            override = database_options_specific.get(
                cst.DatabaseOptions.ADDITIONAL_INFORMATIONS, {}
            ).get(additional_info_class.TIMEZONE)
    return override if override is not None else default_timezone


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

    timezone = _resolve_effective_tz(database_options_specific, options_module, default_timezone)

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

    # Shallow-copy before rebinding the index: `df.index = …` mutates in place, and the
    # no-copy `_format` overrides (servo_u, eit) pass their caller's
    # DataFrame straight in — without this, localization would tz-shift the original.
    localized_index = df.index.tz_localize(timezone)
    df = df.copy(deep=False)
    df.index = localized_index
    return df


# ==================================================================================================
# Display formatting helpers
# ==================================================================================================

_TS_FMT = "%y-%m-%d %H:%M:%S %Z"  # compact, 2-digit year, timezone abbreviation


def fmt_ts(timestamp: object) -> str:
    """Format a pandas Timestamp (or datetime-like) to a compact, human-readable string."""
    try:
        return timestamp.strftime(_TS_FMT).rstrip()
    except Exception:  # noqa: BLE001
        return str(timestamp)


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
    resolved_timezone = resolve_display_timezone(display_timezone)
    result = df.copy(deep=False)
    result.index = df.index.tz_convert(resolved_timezone)
    return result


def _date_range(df: pd.DataFrame) -> tuple[str, str] | None:
    """Return (compact_min, compact_max) of the DataFrame index, or None if empty."""
    if df.empty:
        return None
    try:
        return (fmt_ts(df.index.min()), fmt_ts(df.index.max()))
    except Exception:  # noqa: BLE001
        return None


def _first_last_timestamp(df: pd.DataFrame, column: str) -> tuple[str | None, str | None]:
    """Return (first, last) compact timestamp strings for valid (non-NaN) values in a column."""
    if column not in df.columns:
        return None, None
    valid_index = df.index[df[column].notna()]
    if valid_index.empty:
        return None, None
    return fmt_ts(valid_index.min()), fmt_ts(valid_index.max())
