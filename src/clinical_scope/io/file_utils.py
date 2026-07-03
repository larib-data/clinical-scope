"""
File I/O utilities for reading, writing, and discovering data files.

This module provides functions for saving DataFrames, finding files in folders,
and loading CSV files with datetime indices.
"""

import logging
import re
import warnings
from pathlib import Path

import pandas as pd

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


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
_JUNK_FILENAME_RE = re.compile("|".join(cst.JUNK_FILENAME_PATTERNS))


def is_junk_file(path: Path) -> bool:
    """Return True if *path* is VCS/OS housekeeping cruft (e.g. ``.gitkeep``), not real data."""
    return bool(_JUNK_FILENAME_RE.match(path.name))


def folder_has_real_content(folder_path: Path) -> bool:
    """Return True if *folder_path* contains at least one non-junk file (not recursive)."""
    return any(f.is_file() and not is_junk_file(f) for f in folder_path.iterdir())


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
    6. If *extensions* is given, narrow the set by the first prefered extension that is available
       in the files. Return directly if only one remains.
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
        # No extension filter: all non-junk files are candidates.
        matches = [f for f in folder_path.iterdir() if f.is_file() and not is_junk_file(f)]

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
                logger.info("Selected file by keyword for '%s': %s", datasource_name, kw_matches[0])
                return kw_matches[0]
            if kw_matches:
                matches = kw_matches

    if extensions:
        suffix_rank = {s.lower(): i for i, s in enumerate(extensions)}
        matches.sort(key=lambda f: suffix_rank.get(f.suffix.lower(), len(extensions)))
        if suffix_rank.get(matches[0].suffix.lower(), len(extensions)) < suffix_rank.get(
            matches[1].suffix.lower(), len(extensions)
        ):
            logger.info(
                "Selected file for '%s' by extension preference: %s", datasource_name, matches[0]
            )
            return matches[0]

    logger.warning(
        "Multiple '%s' files found in '%s', could not resolve a unique match: %s",
        datasource_name,
        folder_path,
        [f.name for f in matches],
    )
    return None


# ==================================================================================================
# Datetime-column detection (ADR 0004): tiered name search gated by content validation.
# Name lists and validation thresholds live in constants.py (DATETIME_* constants).

_DATETIME_SUBSTRING_TIER_RES = [
    re.compile(pattern) for pattern in cst.DatetimeColumnDetection.SUBSTRING_TIERS
]


def _validate_parsed_datetimes(parsed: pd.Series) -> bool:
    """Gate a parsed datetime Series: ≥90% valid in-range values, ≥90% non-decreasing."""
    if len(parsed) == 0:
        return False
    valid = parsed.dropna()
    in_range = valid[
        (valid.dt.year >= cst.DatetimeColumnDetection.MIN_YEAR)
        & (valid.dt.year <= cst.DatetimeColumnDetection.MAX_YEAR)
    ]
    if len(in_range) < cst.DatetimeColumnDetection.MIN_VALID_FRACTION * len(parsed):
        return False
    if len(in_range) > 1:
        sorted_fraction = (in_range.diff().iloc[1:] >= pd.Timedelta(0)).mean()
        if sorted_fraction < cst.DatetimeColumnDetection.MIN_SORTED_FRACTION:
            return False
    return True


def _try_parse_datetime_column(series: pd.Series) -> pd.Series | None:
    """Parse a non-numeric Series as datetimes; return the parsed Series or None if gated out."""
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = series
    else:
        try:
            # Probing arbitrary columns triggers pandas' "could not infer format"
            # warning on every garbage candidate — noise, not signal, here.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                parsed = pd.to_datetime(series, errors="coerce")
        except (ValueError, TypeError, OverflowError):
            return None
    return parsed if _validate_parsed_datetimes(parsed) else None


def _pick_best_candidate(passing: list[tuple[str, pd.Series]]) -> tuple[str, pd.Series]:
    """
    Tiebreak same-tier candidates that all passed validation.

    Prefer the highest uniqueness (penalizes batchy DB-artifact columns), then
    utc-named columns (unambiguous vs DST-prone naive-local), then column order.
    A utc-named winner that's still tz-naive after parsing gets localized to UTC.
    """
    best_uniqueness = max(parsed.nunique() for _, parsed in passing)
    top = [(col, parsed) for col, parsed in passing if parsed.nunique() == best_uniqueness]
    utc_named = [(col, parsed) for col, parsed in top if "utc" in str(col).lower()]
    col, parsed = (utc_named or top)[0]
    if "utc" in str(col).lower() and parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize("UTC")
    return col, parsed


def _find_datetime_col_parsed(df: pd.DataFrame) -> tuple[str, pd.Series]:
    """
    Detect the datetime column, returning ``(column_name, parsed_series)``.

    Walks the name tiers (exact, then substring buckets), validating content at every
    tier; numeric columns are deferred to the epoch tier. Raises ValueError when no
    column passes validation (fail loudly — never guess a time axis).
    """
    lower_names = {col: str(col).lower().strip() for col in df.columns}

    # Name tiers: one tier per exact name (in priority order), then each substring
    # bucket — each name/pattern is its own tier so list order is a real priority,
    # not just documentation; a lower-priority name never competes via uniqueness
    # against a higher-priority one that's also present and valid.
    name_tiers = [
        [col for col in df.columns if lower_names[col] == name]
        for name in cst.DatetimeColumnDetection.EXACT_NAMES
    ]
    name_tiers += [
        [col for col in df.columns if pattern.search(lower_names[col])]
        for pattern in _DATETIME_SUBSTRING_TIER_RES
    ]
    # Widen tier: every column, ignoring name (numeric ones still deferred to epoch tier).
    name_tiers.append(list(df.columns))

    for tier in name_tiers:
        passing = [
            (col, parsed)
            for col in tier
            if not pd.api.types.is_numeric_dtype(df[col])
            and (parsed := _try_parse_datetime_column(df[col])) is not None
        ]
        if passing:
            return _pick_best_candidate(passing)

    # Numeric-epoch tier, tried last: nanosecond epochs only (~1.6e18 is unambiguous
    # against real measurement data), gated by the same validation.
    epoch_passing = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        try:
            parsed = pd.to_datetime(df[col], unit="ns", errors="coerce")
        except (ValueError, TypeError, OverflowError):
            continue
        if _validate_parsed_datetimes(parsed):
            epoch_passing.append((col, parsed))
    if epoch_passing:
        return _pick_best_candidate(epoch_passing)

    msg = (
        "No datetime column detected: no column passed content validation "
        f"(≥90% parseable in [{cst.DatetimeColumnDetection.MIN_YEAR}, "
        f"{cst.DatetimeColumnDetection.MAX_YEAR}], ≥90% non-decreasing). "
        f"Columns: {list(df.columns)}"
    )
    raise ValueError(msg)


def set_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return *df* indexed by its detected datetime column.

    Short-circuits when the index is already a DatetimeIndex; otherwise detects,
    parses, and sets the best-validated datetime column (raises if none passes).
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    col, parsed = _find_datetime_col_parsed(df)
    df = df.copy()
    df[col] = parsed
    return df.set_index(col)


# ==================================================================================================
def load_csv_with_datetime_index(
    file_path: str | Path, dt_col: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Load a CSV file and set a datetime column as the index.

    When *dt_col* is ``None``, auto-detects the datetime column with
    ``set_datetime_index`` (raises if no column passes validation).
    """
    if dt_col is not None:
        return pd.read_csv(file_path, index_col=dt_col, parse_dates=True, **kwargs)

    return set_datetime_index(pd.read_csv(file_path, **kwargs))


# ==================================================================================================
def load_parquet_with_datetime_index(
    file_path: str | Path, dt_col: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Load a parquet file and ensure it is indexed by datetime.

    Files already carrying a DatetimeIndex (e.g. written by our own extract) are
    returned as-is; otherwise the datetime column is detected with
    ``set_datetime_index`` (raises if no column passes validation). *dt_col*
    bypasses detection and sets that column directly.
    """
    df = pd.read_parquet(file_path, **kwargs)
    if dt_col is not None:
        df[dt_col] = pd.to_datetime(df[dt_col])
        return df.set_index(dt_col)
    return set_datetime_index(df)


# ==================================================================================================
def get_column_name_from_pattern(columns: pd.Index | list[str], pattern: str) -> str | None:
    """Find a column name matching a pattern (supports wildcard suffix '*')."""
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
