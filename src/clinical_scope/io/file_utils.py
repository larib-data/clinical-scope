"""
File I/O utilities for reading, writing, and discovering data files.

This module provides functions for saving DataFrames, finding files in folders,
and loading CSV files with datetime indices.
"""

import logging
import re
import warnings
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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


def _name_tiers(columns: list[str]) -> list[list[str]]:
    """
    Build the datetime-column name-priority tiers (exact names, then substring buckets).

    Shared by full-frame detection (:func:`_find_datetime_col_parsed`) and
    schema-only detection (:func:`_detect_datetime_column_from_parquet`), so both walk
    the same priority order without duplicating it. Each name/pattern is its own tier
    so list order is a real priority: a lower-priority name never competes via
    uniqueness against a higher-priority one that's also present and valid.
    """
    lower_names = {col: str(col).lower().strip() for col in columns}
    tiers = [
        [col for col in columns if lower_names[col] == name]
        for name in cst.DatetimeColumnDetection.EXACT_NAMES
    ]
    tiers += [
        [col for col in columns if pattern.search(lower_names[col])]
        for pattern in _DATETIME_SUBSTRING_TIER_RES
    ]
    # Widen tier: every column, ignoring name (numeric ones still deferred to epoch tier).
    tiers.append(list(columns))
    return tiers


def _find_datetime_col_parsed(df: pd.DataFrame) -> tuple[str, pd.Series]:
    """
    Detect the datetime column, returning ``(column_name, parsed_series)``.

    Walks the name tiers (exact, then substring buckets), validating content at every
    tier; numeric columns are deferred to the epoch tier. Raises ValueError when no
    column passes validation (fail loudly — never guess a time axis).
    """
    for tier in _name_tiers(list(df.columns)):
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


# ==================================================================================================
# Parquet datetime row-pushdown (issue #57): prune out-of-window rows at read time via
# row-group statistics, instead of loading the full file and filtering afterwards.


def resolve_stored_datetime_index(path: Path) -> tuple[str, str | None] | None:
    """
    Return the parquet file's materialized DatetimeIndex column and tz, if any.

    ``(index_column_name, tz)`` if *path* already stores a materialized DatetimeIndex
    column (e.g. written by our own ``to_parquet``), else ``None``. ``tz`` is ``None``
    for a tz-naive stored index. Returns ``None`` (not a
    materialized index) for a plain ``RangeIndex`` — pandas records that as a
    descriptor dict rather than a physical column name.
    """
    schema = pq.ParquetFile(path).schema_arrow
    pandas_metadata = schema.pandas_metadata
    if not pandas_metadata:
        return None
    index_cols = pandas_metadata.get("index_columns") or []
    if len(index_cols) != 1 or not isinstance(index_cols[0], str):
        return None
    col = index_cols[0]
    field = schema.field(col)
    if not pa.types.is_timestamp(field.type):
        return None
    return col, (str(field.type.tz) if field.type.tz else None)


def _is_numeric_pa_type(field_type: pa.DataType) -> bool:
    """
    Schema-only "numeric, defer to the epoch tier" predicate for a pyarrow field type.

    Must agree with :func:`_find_datetime_col_parsed`'s ``pd.api.types.is_numeric_dtype``
    check on every dtype that can appear in a clinical parquet export — the two datetime
    detectors (schema-only vs. full-frame) rely on picking the same candidate column.
    See :class:`tests.datasource.test_datetime_pushdown.TestNumericTypeClassificationAgreement`.
    """
    return pa.types.is_integer(field_type) or pa.types.is_floating(field_type)


def _sample_parquet_columns(parquet_file: pq.ParquetFile, columns: list[str]) -> pd.DataFrame:
    """
    Read a bounded, spread sample of *columns* for datetime detection.

    Reads whole row groups (parquet's random-access unit) evenly spread across the file,
    head-slicing each to ``SAMPLE_ROWS_PER_BLOCK`` — contiguous slices preserve duplicate-value
    runs, so the uniqueness and sorted checks in :func:`_pick_best_candidate` /
    :func:`_validate_parsed_datetimes` stay meaningful. The whole file is read only when it
    fits the decode budget or has a single row group. When it has several, at least
    ``SAMPLE_MIN_GROUPS`` are sampled even if the budget alone would pick fewer (huge row
    groups), so detection always sees two independent places.
    """
    md = parquet_file.metadata
    n_groups = md.num_row_groups
    cst_det = cst.DatetimeColumnDetection
    if n_groups <= 1 or md.num_rows <= cst_det.SAMPLE_MAX_ROW_DECODED:
        return parquet_file.read(columns=columns).to_pandas()

    rows_per_group = md.row_group(0).num_rows
    budget_groups = max(1, cst_det.SAMPLE_MAX_ROW_DECODED // rows_per_group)
    n = min(cst_det.SAMPLE_MAX_GROUPS, n_groups, budget_groups)
    n = max(n, min(cst_det.SAMPLE_MIN_GROUPS, n_groups))  # ≥2 places when ≥2 groups exist
    indices = sorted({round(k * (n_groups - 1) / (n - 1)) for k in range(n)})
    block = cst_det.SAMPLE_ROWS_PER_BLOCK
    tables = [parquet_file.read_row_group(i, columns=columns).slice(0, block) for i in indices]
    return pa.concat_tables(tables).to_pandas()


def _detect_datetime_column_from_parquet(
    path: Path,
) -> tuple[str, str, str | None, bool] | None:
    """
    Detect the datetime column of a parquet file without a materialized index.

    Mirrors :func:`_find_datetime_col_parsed`'s tiered name search, but reads only
    each tier's candidate columns (progressively widening) to validate content,
    rather than loading the whole file uparquet_fileront.

    Returns ``(column_name, kind, tz, physically_naive)`` where *kind* is
    ``"timestamp"`` (direct range filter, *tz* set for tz-aware columns) or
    ``"epoch_ns"`` (nanosecond-epoch numeric column, *tz* is ``None``) — both safe for
    an unambiguous parquet row filter. Any other resolved type (e.g. a string datetime
    column, unparsed) is not pushdown-safe and yields ``None``, so the caller falls
    back to a full unfiltered read.

    *tz* is the *semantic* timezone (from :func:`_pick_best_candidate`, which
    force-localizes a tz-naive utc-named column to UTC — matching what
    :func:`set_datetime_index` does downstream) and can therefore diverge from the
    column's on-disk type, which stays physically tz-naive. *physically_naive* flags
    that case so the caller can strip the tz label back off before filtering — pyarrow
    filter values must match the physical on-disk type exactly.

    Candidate columns are validated on a bounded sample (:func:`_sample_parquet_columns`),
    not the whole file, so this pick can diverge from the downstream full-frame
    :func:`set_datetime_index` — which would filter one column and index another (silent row
    loss). To stay safe, detection only ever consults the **highest-priority tier that has any
    named candidate**, and commits only if that tier yields **exactly one** sample-validated
    column; otherwise it abstains (returns ``None`` → full read, full-frame decides):

    - **zero passing** there — a higher-priority column we couldn't confirm on the sample
      (e.g. valid over the whole file but garbage in exactly the sampled row groups) may still
      validate on the full frame and outrank any lower-tier pick, so we must not look lower.
    - **more than one** — the sample-based uniqueness tiebreak in :func:`_pick_best_candidate`
      isn't stable, so the pick could differ from the full frame's.
    """
    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow

    def _is_numeric(col: str) -> bool:
        return _is_numeric_pa_type(schema.field(col).type)

    columns = list(schema.names)
    for tier in _name_tiers(columns):
        candidates = [col for col in tier if not _is_numeric(col)]
        if not candidates:
            continue
        sample = _sample_parquet_columns(parquet_file, candidates)
        passing = [
            (col, parsed)
            for col in candidates
            if (parsed := _try_parse_datetime_column(sample[col])) is not None
        ]
        if len(passing) != 1:
            return None
        col, parsed = _pick_best_candidate(passing)
        field_type = schema.field(col).type
        if pa.types.is_timestamp(field_type):
            # Use the resolved parsed tz, not the raw physical field's — _pick_best_candidate
            # force-localizes utc-named naive columns to UTC, matching what the real pipeline
            # (set_datetime_index) later does, and the row-filter bounds must agree with that.
            # The physical on-disk type stays naive though, so flag it for the caller.
            tz = parsed.dt.tz
            return col, "timestamp", (str(tz) if tz else None), field_type.tz is None
        return col, "other", None, False

    numeric_cols = [col for col in columns if _is_numeric(col)]
    if numeric_cols:
        sample = _sample_parquet_columns(parquet_file, numeric_cols)
        epoch_passing = []
        for col in numeric_cols:
            try:
                parsed = pd.to_datetime(sample[col], unit="ns", errors="coerce")
            except (ValueError, TypeError, OverflowError):
                continue
            if _validate_parsed_datetimes(parsed):
                epoch_passing.append((col, parsed))
        if len(epoch_passing) > 1:  # no named tier hid a candidate here — only the tiebreak can
            return None
        if epoch_passing:
            col, _parsed = _pick_best_candidate(epoch_passing)
            return col, "epoch_ns", None, True

    return None


def read_parquet_with_datetime_pushdown(
    path: Path,
    bounds_fn: Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None],
) -> pd.DataFrame:
    """
    Read a parquet file, pushing a datetime window down as a row filter when possible.

    *bounds_fn* is called with the resolved datetime column's timezone (``None`` if
    tz-naive or epoch-based) and must return conservative-loose ``(start, end)``
    bounds expressed in that same tz — either side may be ``None`` — or ``None`` if no
    window is set. Tries, in order: the file's own materialized DatetimeIndex column
    (no data read yet), then a tiered name-based scan reading only candidate columns
    (mirrors :func:`set_datetime_index`'s detection). Falls back to an unfiltered full
    read when no window is set, detection doesn't resolve, or the resolved column's
    type can't be range-compared unambiguously (e.g. a string datetime column) —
    under-pruning only costs a few extra rows, so a fallback is always correctness-safe.
    """
    stored_index = resolve_stored_datetime_index(path)
    if stored_index is not None:
        col, tz = stored_index
        kind = "timestamp"
        physically_naive = tz is None
    else:
        detected = _detect_datetime_column_from_parquet(path)
        if detected is None:
            return pd.read_parquet(path)
        col, kind, tz, physically_naive = detected

    bounds = bounds_fn(tz if kind == "timestamp" else None)
    if bounds is None or kind == "other":
        return pd.read_parquet(path)

    start, end = bounds
    if kind == "epoch_ns":
        start = None if start is None else start.value
        end = None if end is None else end.value
    elif kind == "timestamp" and physically_naive:
        # tz may be a *semantic* tz forced by name detection (e.g. a naive column named
        # "*utc*") while the on-disk column itself has no stored tz — bounds_fn then
        # returns tz-aware bounds that pyarrow can't compare against the physical type.
        # Strip the tz label (keep the wall-clock reading) to match the physical column.
        if start is not None and start.tzinfo is not None:
            start = start.tz_localize(None)
        if end is not None and end.tzinfo is not None:
            end = end.tz_localize(None)

    filters = [
        f
        for f in [
            (col, ">=", start) if start is not None else None,
            (col, "<=", end) if end is not None else None,
        ]
        if f is not None
    ]
    if not filters:
        return pd.read_parquet(path)

    total_rows = pq.ParquetFile(path).metadata.num_rows
    df = pd.read_parquet(path, filters=filters)
    pruned_pct = 100 * (1 - len(df) / total_rows) if total_rows else 0.0
    logger.info(
        "Parquet pushdown on '%s': read %d/%d rows (%.0f%% pruned).",
        path,
        len(df),
        total_rows,
        pruned_pct,
    )
    return df


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
    file_path: str | Path,
    dt_col: str | None = None,
    bounds_fn: Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None]
    | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Load a parquet file and ensure it is indexed by datetime.

    Files already carrying a DatetimeIndex (e.g. written by our own extract) are
    returned as-is; otherwise the datetime column is detected with
    ``set_datetime_index`` (raises if no column passes validation). *dt_col*
    bypasses detection and sets that column directly. *bounds_fn*, if given (and
    *dt_col* is not), pushes the datetime window down as a row filter at read time —
    see :func:`read_parquet_with_datetime_pushdown`.
    """
    if bounds_fn is not None and dt_col is None:
        df = read_parquet_with_datetime_pushdown(Path(file_path), bounds_fn)
    else:
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
