"""File I/O utilities for reading, writing, and discovering data files."""

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
    return all(keyword.lower() in name_lower for keyword in keywords)


# ==================================================================================================
_JUNK_FILENAME_RE = re.compile("|".join(cst.JUNK_FILENAME_PATTERNS))


def is_junk_file(path: Path) -> bool:
    """Return True if *path* is VCS/OS cruft or documentation (``.gitkeep``, ``readme.txt``)."""
    return bool(_JUNK_FILENAME_RE.match(path.name))


def folder_has_real_content(folder_path: Path) -> bool:
    """Return True if *folder_path* contains at least one non-junk file (not recursive)."""
    return any(entry.is_file() and not is_junk_file(entry) for entry in folder_path.iterdir())


# ==================================================================================================
def deduplicate_by_stem(files: list[Path], extensions: list[str]) -> list[Path]:
    """
    Keep one file per stem, preferring the extension earliest in *extensions*.

    A device folder routinely holds both a source export and a parquet written from it;
    loading both would duplicate every signal under colliding names.
    """
    suffix_rank = {extension.lower(): index for index, extension in enumerate(extensions)}
    max_rank = len(extensions)

    def rank(file: Path) -> int:
        return suffix_rank.get(file.suffix.lower(), max_rank)

    kept_by_stem: dict[str, Path] = {}
    for file in files:
        stem = file.stem.lower()
        incumbent = kept_by_stem.get(stem)
        if incumbent is None:
            kept_by_stem[stem] = file
            continue
        winner, shadowed = (file, incumbent) if rank(file) < rank(incumbent) else (incumbent, file)
        kept_by_stem[stem] = winner
        logger.info(
            "Ignoring '%s': '%s' already covers stem '%s'.", shadowed.name, winner.name, stem
        )
    return list(kept_by_stem.values())


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

    When *multi* is ``True``, return **all** files matching *extensions*, deduplicated by
    stem and sorted alphabetically, or ``None`` if none found.

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
        ext_set = {extension.lower() for extension in extensions}
        files = [
            file
            for file in folder_path.iterdir()
            if file.is_file() and file.suffix.lower() in ext_set
        ]
        if not files:
            logger.debug("Could not find any %s files in folder '%s'", datasource_name, folder_path)
            return None
        files = sorted(deduplicate_by_stem(files, extensions))
        logger.debug("Found %s: %s in folder %s", datasource_name, files, folder_path)
        return files

    # --- single-file mode ---
    if extensions:
        suffix_set = {extension.lower() for extension in extensions}
        matches = [
            file
            for file in folder_path.iterdir()
            if file.is_file() and file.suffix.lower() in suffix_set
        ]
    else:
        # No extension filter: all non-junk files are candidates.
        matches = [
            file for file in folder_path.iterdir() if file.is_file() and not is_junk_file(file)
        ]

    if not matches:
        logger.warning("No file for '%s' found in folder '%s'.", datasource_name, folder_path)
        return None

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    if extensions:
        matches = deduplicate_by_stem(matches, extensions)

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    # Keyword filtering on stem (ordered by preference)
    if keywords:
        for keyword in keywords:
            keyword_lower = keyword.lower()
            keyword_matches = [file for file in matches if keyword_lower in file.stem.lower()]
            if len(keyword_matches) == 1:
                logger.info(
                    "Selected file by keyword for '%s': %s", datasource_name, keyword_matches[0]
                )
                return keyword_matches[0]
            if keyword_matches:
                matches = keyword_matches

    if extensions:
        suffix_rank = {extension.lower(): index for index, extension in enumerate(extensions)}
        matches.sort(key=lambda file: suffix_rank.get(file.suffix.lower(), len(extensions)))
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
        [file.name for file in matches],
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
    top = [
        (column_name, parsed)
        for column_name, parsed in passing
        if parsed.nunique() == best_uniqueness
    ]
    utc_named = [
        (column_name, parsed) for column_name, parsed in top if "utc" in str(column_name).lower()
    ]
    column_name, parsed = (utc_named or top)[0]
    if "utc" in str(column_name).lower() and parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize("UTC")
    return column_name, parsed


def _name_tiers(columns: list[str]) -> list[list[str]]:
    """
    Build the datetime-column name-priority tiers (exact names, then substring buckets).

    Shared by full-frame detection (:func:`_find_datetime_col_parsed`) and
    schema-only detection (:func:`_detect_datetime_column_from_parquet`), so both walk
    the same priority order without duplicating it. Each name/pattern is its own tier
    so list order is a real priority: a lower-priority name never competes via
    uniqueness against a higher-priority one that's also present and valid.
    """
    lower_names = {column_name: str(column_name).lower().strip() for column_name in columns}
    tiers = [
        [column_name for column_name in columns if lower_names[column_name] == name]
        for name in cst.DatetimeColumnDetection.EXACT_NAMES
    ]
    tiers += [
        [column_name for column_name in columns if pattern.search(lower_names[column_name])]
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
            (column_name, parsed)
            for column_name in tier
            if not pd.api.types.is_numeric_dtype(df[column_name])
            and (parsed := _try_parse_datetime_column(df[column_name])) is not None
        ]
        if passing:
            return _pick_best_candidate(passing)

    # Numeric-epoch tier, tried last: nanosecond epochs only (~1.6e18 is unambiguous
    # against real measurement data), gated by the same validation.
    epoch_passing = []
    for column_name in df.columns:
        if not pd.api.types.is_numeric_dtype(df[column_name]):
            continue
        try:
            parsed = pd.to_datetime(df[column_name], unit="ns", errors="coerce")
        except (ValueError, TypeError, OverflowError):
            continue
        if _validate_parsed_datetimes(parsed):
            epoch_passing.append((column_name, parsed))
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
    index_columns = pandas_metadata.get("index_columns") or []
    if len(index_columns) != 1 or not isinstance(index_columns[0], str):
        return None
    column_name = index_columns[0]
    field = schema.field(column_name)
    if not pa.types.is_timestamp(field.type):
        return None
    return column_name, (str(field.type.tz) if field.type.tz else None)


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
    parquet_metadata = parquet_file.metadata
    row_group_count = parquet_metadata.num_row_groups
    detection_constants = cst.DatetimeColumnDetection
    max_row_decoded = detection_constants.SAMPLE_MAX_ROW_DECODED
    if row_group_count <= 1 or parquet_metadata.num_rows <= max_row_decoded:
        return parquet_file.read(columns=columns).to_pandas()

    rows_per_group = parquet_metadata.row_group(0).num_rows
    budget_groups = max(1, max_row_decoded // rows_per_group)
    sample_group_count = min(detection_constants.SAMPLE_MAX_GROUPS, row_group_count, budget_groups)
    sample_group_count = max(
        sample_group_count, min(detection_constants.SAMPLE_MIN_GROUPS, row_group_count)
    )  # ≥2 places when ≥2 groups exist
    indices = sorted(
        {
            round(sample_index * (row_group_count - 1) / (sample_group_count - 1))
            for sample_index in range(sample_group_count)
        }
    )
    rows_per_block = detection_constants.SAMPLE_ROWS_PER_BLOCK
    tables = [
        parquet_file.read_row_group(group_index, columns=columns).slice(0, rows_per_block)
        for group_index in indices
    ]
    return pa.concat_tables(tables).to_pandas()


def _detect_datetime_column_from_parquet(
    path: Path,
) -> tuple[str, str, str | None, bool] | None:
    """
    Detect the datetime column of a parquet file without a materialized index.

    Mirrors :func:`_find_datetime_col_parsed`'s tiered name search, but reads only
    each tier's candidate columns (progressively widening) to validate content,
    rather than loading the whole file upfront.

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

    def _is_numeric(column_name: str) -> bool:
        return _is_numeric_pa_type(schema.field(column_name).type)

    columns = list(schema.names)
    for tier in _name_tiers(columns):
        candidates = [column_name for column_name in tier if not _is_numeric(column_name)]
        if not candidates:
            continue
        sample = _sample_parquet_columns(parquet_file, candidates)
        passing = [
            (column_name, parsed)
            for column_name in candidates
            if (parsed := _try_parse_datetime_column(sample[column_name])) is not None
        ]
        if len(passing) != 1:
            return None
        column_name, parsed = _pick_best_candidate(passing)
        field_type = schema.field(column_name).type
        if pa.types.is_timestamp(field_type):
            # Use the resolved parsed tz, not the raw physical field's — _pick_best_candidate
            # force-localizes utc-named naive columns to UTC, matching what the real pipeline
            # (set_datetime_index) later does, and the row-filter bounds must agree with that.
            # The physical on-disk type stays naive though, so flag it for the caller.
            tz = parsed.dt.tz
            return column_name, "timestamp", (str(tz) if tz else None), field_type.tz is None
        return column_name, "other", None, False

    numeric_columns = [column_name for column_name in columns if _is_numeric(column_name)]
    if numeric_columns:
        sample = _sample_parquet_columns(parquet_file, numeric_columns)
        epoch_passing = []
        for column_name in numeric_columns:
            try:
                parsed = pd.to_datetime(sample[column_name], unit="ns", errors="coerce")
            except (ValueError, TypeError, OverflowError):
                continue
            if _validate_parsed_datetimes(parsed):
                epoch_passing.append((column_name, parsed))
        if len(epoch_passing) > 1:  # no named tier hid a candidate here — only the tiebreak can
            return None
        if epoch_passing:
            column_name, _parsed = _pick_best_candidate(epoch_passing)
            return column_name, "epoch_ns", None, True

    return None


def _build_datetime_row_filters(
    column_name: str,
    kind: str,
    physically_naive: bool,
    bounds: tuple[pd.Timestamp | None, pd.Timestamp | None],
) -> list[tuple] | None:
    """Turn resolved ``(start, end)`` bounds into pyarrow row filters, or ``None`` if empty."""
    start, end = bounds
    if kind == "epoch_ns":
        start = None if start is None else start.value
        end = None if end is None else end.value
    elif kind == "timestamp" and physically_naive:
        # A naive column may carry a semantic tz from name detection (e.g. "*utc*"); strip the
        # tz label so the wall-clock bounds match the physical, tz-naive on-disk column.
        if start is not None and start.tzinfo is not None:
            start = start.tz_localize(None)
        if end is not None and end.tzinfo is not None:
            end = end.tz_localize(None)

    filters = [
        filter_clause
        for filter_clause in [
            (column_name, ">=", start) if start is not None else None,
            (column_name, "<=", end) if end is not None else None,
        ]
        if filter_clause is not None
    ]
    return filters or None


def read_parquet_pruned(
    path: Path,
    compute_bounds: Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None]
    | None = None,
    select_columns: Callable[[list[str]], list[str] | None] | None = None,
) -> pd.DataFrame:
    """
    Read a parquet file, pruning out-of-window rows *and* unconfigured columns at read time.

    Two orthogonal prunings, each safe on its own:

    - **Rows** — *compute_bounds* receives the datetime column's tz (``None`` if tz-naive/epoch)
      and returns loose ``(start, end)`` bounds in that tz (either side may be ``None``), or
      ``None`` for no window. Applied only for a range-comparable datetime column; otherwise
      the read is unfiltered (under-pruning only costs extra rows).
    - **Columns** — *select_columns* receives the file's column names and returns the subset to
      read (a superset of the finally-selected signals), or ``None`` to read all. Independent
      of any window — the common case is a wide cache with no window set.

    Index-safe: a materialized DatetimeIndex is auto-restored by pandas even when omitted;
    a non-materialized datetime column is unioned back so ``set_datetime_index`` still finds
    it; if that column can't be resolved, column pruning is skipped (never drop the time axis).
    """
    file_columns = pq.ParquetFile(path).schema_arrow.names
    requested_columns = None if select_columns is None else select_columns(list(file_columns))

    stored_index = resolve_stored_datetime_index(path)
    materialized = stored_index is not None
    want_pushdown = compute_bounds is not None

    # Resolve the datetime column only when needed (row filter, or protecting a
    # non-materialized time axis); detection samples data, so skip it otherwise.
    column_name = kind = tz = None
    physically_naive = False
    if want_pushdown or (requested_columns is not None and not materialized):
        if materialized:
            column_name, tz = stored_index
            kind = "timestamp"
            physically_naive = tz is None
        else:
            detected = _detect_datetime_column_from_parquet(path)
            if detected is not None:
                column_name, kind, tz, physically_naive = detected

    columns_to_read = requested_columns
    if columns_to_read is not None and not materialized:
        if column_name is None:
            columns_to_read = None  # unknown datetime axis → don't risk dropping it, read all
        elif column_name not in columns_to_read:
            columns_to_read = [column_name, *columns_to_read]  # keep the time axis in the read

    filters = None
    if want_pushdown and column_name is not None and kind is not None and kind != "other":
        bounds = compute_bounds(tz if kind == "timestamp" else None)
        if bounds is not None:
            filters = _build_datetime_row_filters(column_name, kind, physically_naive, bounds)

    if columns_to_read is not None:
        logger.debug(
            "Parquet column pruning on '%s': reading %d/%d columns.",
            path,
            len(columns_to_read),
            len(file_columns),
        )

    if filters is None:
        return pd.read_parquet(path, columns=columns_to_read)

    total_rows = pq.ParquetFile(path).metadata.num_rows
    df = pd.read_parquet(path, filters=filters, columns=columns_to_read)
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
    column_name, parsed = _find_datetime_col_parsed(df)
    df = df.copy()
    df[column_name] = parsed
    return df.set_index(column_name)


def deduplicate_then_sort_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop duplicate index entries (keep first) *then* sort by index.

    Deduplicating first keeps the first row in file order on a timestamp
    collision, which a non-stable ``sort_index`` would decide arbitrarily.
    Skips either step when already satisfied (device exports are usually
    already sorted and unique).
    """
    if not df.index.is_unique:
        df = df[~df.index.duplicated(keep="first")]
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    return df


# ==================================================================================================
def load_csv_with_datetime_index(
    file_path: str | Path, datetime_column: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Load a CSV file and set a datetime column as the index.

    When *datetime_column* is ``None``, auto-detects the datetime column with
    ``set_datetime_index`` (raises if no column passes validation).
    """
    if datetime_column is not None:
        return pd.read_csv(file_path, index_col=datetime_column, parse_dates=True, **kwargs)

    return set_datetime_index(pd.read_csv(file_path, **kwargs))


# ==================================================================================================
def load_parquet_with_datetime_index(
    file_path: str | Path,
    datetime_column: str | None = None,
    compute_bounds: Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None]
    | None = None,
    select_columns: Callable[[list[str]], list[str] | None] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Load a parquet file and ensure it is indexed by datetime.

    Files already carrying a DatetimeIndex are returned as-is; otherwise the datetime column
    is detected with ``set_datetime_index`` (raises if none passes validation).

    *datetime_column* names the datetime column explicitly, bypassing detection. Column pruning
    (*select_columns*) still applies then — *datetime_column* is always kept in the read — but
    row pushdown (*compute_bounds*) does not, since an explicit column may still need parsing
    before it is range-comparable. Without *datetime_column*, both prunings go through
    :func:`read_parquet_pruned`.
    """
    if datetime_column is not None:
        columns = None
        if select_columns is not None:
            file_columns = pq.ParquetFile(file_path).schema_arrow.names
            columns = select_columns(list(file_columns))
            if columns is not None and datetime_column not in columns:
                columns = [datetime_column, *columns]  # keep the time axis in the read
        df = pd.read_parquet(file_path, columns=columns, **kwargs)
        df[datetime_column] = pd.to_datetime(df[datetime_column])
        return df.set_index(datetime_column)

    if compute_bounds is not None or select_columns is not None:
        df = read_parquet_pruned(
            Path(file_path), compute_bounds=compute_bounds, select_columns=select_columns
        )
    else:
        df = pd.read_parquet(file_path, **kwargs)
    return set_datetime_index(df)


# ==================================================================================================
def _wildcard_matches(pattern: str, columns: pd.Index | list[str]) -> list[str] | None:
    """
    Prefix-match *columns* for a trailing-``*`` wildcard; ``None`` if *pattern* is a literal.

    Single definition of what a ``*`` matches, shared by :func:`get_column_name_from_pattern`
    and :func:`_pruned_columns` so their wildcard handling can't drift. ``None`` (literal) is
    distinct from ``[]`` (wildcard with zero matches) — each caller handles literals its own way.
    """
    if not (pattern and pattern.endswith(cst.DatabaseOptions.WILDCARD_SUFFIX)):
        return None
    prefix = pattern.rstrip(cst.DatabaseOptions.WILDCARD_SUFFIX)
    return [column_name for column_name in columns if column_name.startswith(prefix)]


def get_column_name_from_pattern(columns: pd.Index | list[str], pattern: str) -> str | None:
    """Find a column name matching a pattern (supports wildcard suffix '*')."""
    matching_columns = _wildcard_matches(pattern, columns)
    if matching_columns is None:
        return pattern  # literal: assume the caller-supplied name is the column

    if len(matching_columns) == 1:
        return matching_columns[0]
    if len(matching_columns) == 0:
        logger.warning("No column found in dataframe from the pattern %s", pattern)
    else:
        logger.warning(
            "More than one column found in dataframe with the pattern %s. -> Ignored", pattern
        )
    return None


# ==================================================================================================
def _pruned_columns(field_display: list[str] | None, file_columns: list[str]) -> list[str] | None:
    """
    Resolve which parquet columns to read for a set of configured signal patterns.

    Pure column-name logic (no data read). Shares :func:`_wildcard_matches` with
    :func:`get_column_name_from_pattern`, so the result is by construction a superset of the
    columns that matcher finally selects — every 0/1/2+ match count, and thus every warning,
    is identical to a full read.

    - wildcard ``pre*`` → all file columns starting with ``pre`` (1)
    - literal → included iff present (an absent name in ``columns=`` would raise) (2)
    - *field_display* absent (``None``) → ``None`` ⇒ read all columns (3)
    """
    if field_display is None:  # (3)
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for pattern in field_display:
        matches = _wildcard_matches(pattern, file_columns)
        if matches is None:  # (2)
            matches = [pattern] if pattern in file_columns else []
        for name in matches:  # (1)
            if name not in seen:
                seen.add(name)
                selected.append(name)
    return selected


def make_column_selector(
    database_options_specific: dict | None,
) -> Callable[[list[str]], list[str] | None]:
    """
    Build a *select_columns* callable for :func:`read_parquet_pruned` from a datasource's options.

    Centralizes the ``field_display`` lookup shared by every parquet call site. The returned
    closure defers pattern resolution until the file's columns are known.
    """
    field_display = (database_options_specific or {}).get(cst.DatabaseOptions.FIELD_DISPLAY)
    return lambda file_columns: _pruned_columns(field_display, file_columns)
