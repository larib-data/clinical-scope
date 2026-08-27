"""
Establishing a dataframe's time axis: which column carries it, and normalising it.

Implements ADR 0004's tiered name search gated by content validation. The rule has two
adapters over the same tiers — :func:`detect_time_axis_in_frame` for a loaded frame and
:func:`detect_time_axis_in_parquet` for a file read only by schema and sample. They must
pick the same column, so they live together.

Name lists and validation thresholds live in constants.py (``DatetimeColumnDetection``).
"""

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import clinical_scope.constants as cst


@dataclass(frozen=True)
class DetectedTimeAxis:
    """
    A parquet file's time axis, resolved from its schema and a bounded sample.

    *tz* is semantic: for a utc-named but tz-naive column it is asserted from the name
    rather than read from the type. *tz_from_name* marks that one case, so a caller can
    strip the label back off before comparing against the stored values.
    """

    column_name: str
    kind: str
    tz: str | None
    tz_from_name: bool


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
        parsed = parsed.dt.tz_localize(cst.LIBRARY_TZ)
    return column_name, parsed


def _name_tiers(columns: list[str]) -> list[list[str]]:
    """
    Build the datetime-column name-priority tiers (exact names, then substring buckets).

    Shared by full-frame detection (:func:`detect_time_axis_in_frame`) and
    schema-only detection (:func:`detect_time_axis_in_parquet`), so both walk
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


def detect_time_axis_in_frame(df: pd.DataFrame) -> tuple[str, pd.Series]:
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


def _is_numeric_pa_type(field_type: pa.DataType) -> bool:
    """
    Schema-only "numeric, defer to the epoch tier" predicate for a pyarrow field type.

    Must agree with :func:`detect_time_axis_in_frame`'s ``pd.api.types.is_numeric_dtype``
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
    # ignore_metadata keeps a materialized index column addressable by name: pandas metadata
    # would restore it as the frame's index, and a candidate can be exactly that column.
    parquet_metadata = parquet_file.metadata
    row_group_count = parquet_metadata.num_row_groups
    detection_constants = cst.DatetimeColumnDetection
    max_row_decoded = detection_constants.SAMPLE_MAX_ROW_DECODED
    if row_group_count <= 1 or parquet_metadata.num_rows <= max_row_decoded:
        return parquet_file.read(columns=columns).to_pandas(ignore_metadata=True)

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
    return pa.concat_tables(tables).to_pandas(ignore_metadata=True)


def detect_time_axis_in_parquet(path: Path) -> DetectedTimeAxis | None:
    """
    Detect the datetime column of a parquet file without a materialized index.

    Mirrors :func:`detect_time_axis_in_frame`'s tiered name search, but reads only
    each tier's candidate columns (progressively widening) to validate content,
    rather than loading the whole file upfront.

    Returns a :class:`DetectedTimeAxis` whose *kind* is
    ``TIMESTAMP`` (direct range filter, *tz* set for tz-aware columns) or
    ``EPOCH_NS`` (nanosecond-epoch numeric column, *tz* is ``None``) — see
    :class:`~clinical_scope.constants.ParquetPushdownKind`. Both are safe for
    an unambiguous parquet row filter. Any other resolved type (e.g. a string datetime
    column, unparsed) is not pushdown-safe and yields ``None``, so the caller falls
    back to a full unfiltered read.

    Its *tz* is the *semantic* timezone (from :func:`_pick_best_candidate`, which
    force-localizes a tz-naive utc-named column to UTC — matching what
    :func:`set_datetime_index` does downstream) and can therefore diverge from the
    column's on-disk type, which stays tz-naive. Its *tz_from_name* flags that one case, so
    the caller can strip the label back off before filtering — pyarrow filter values must
    match the stored type exactly.

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
            # Use the resolved parsed tz, not the stored field's — _pick_best_candidate
            # force-localizes utc-named naive columns to UTC, matching set_datetime_index
            # downstream, so the row-filter bounds must agree with it rather than with disk.
            tz = parsed.dt.tz
            return DetectedTimeAxis(
                column_name,
                cst.ParquetPushdownKind.TIMESTAMP,
                str(tz) if tz else None,
                tz_from_name=tz is not None and field_type.tz is None,
            )
        return DetectedTimeAxis(
            column_name, cst.ParquetPushdownKind.OTHER, None, tz_from_name=False
        )

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
            return DetectedTimeAxis(
                column_name, cst.ParquetPushdownKind.EPOCH_NS, None, tz_from_name=False
            )

    return None


def set_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return *df* indexed by its detected datetime column.

    Short-circuits when the index is already a DatetimeIndex; otherwise detects,
    parses, and sets the best-validated datetime column (raises if none passes).
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    column_name, parsed = detect_time_axis_in_frame(df)
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
