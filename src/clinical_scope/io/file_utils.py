"""
File I/O utilities for reading, writing, and discovering data files.

This module provides functions for saving DataFrames, finding files in folders,
and loading CSV files with datetime indices.
"""

import logging
import re
from pathlib import Path

import pandas as pd

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
        # No extension filter: all files are candidates.
        # NOTE: if a datasource defines FILE_EXTENSIONS = [] with MULTI_FILE = False,
        # junk files (.DS_Store, etc.) will be included here. Always define FILE_EXTENSIONS.
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


# ==================================================================================================
def load_csv_with_datetime_index(
    file_path: str | Path, dt_col: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Load a CSV file and set a datetime column as the index.

    When *dt_col* is ``None``, auto-detects the best datetime column from
    headers (single pass: reads full file, then sets the index in-memory).
    """
    if dt_col is not None:
        return pd.read_csv(file_path, index_col=dt_col, parse_dates=True, **kwargs)

    # Single-pass: read everything, then detect and set index in-memory
    df = pd.read_csv(file_path, **kwargs)
    detected = find_datetime_col(df.columns.tolist())
    idx_col = detected if detected is not None else df.columns[0]

    df[idx_col] = pd.to_datetime(df[idx_col])
    return df.set_index(idx_col)


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
