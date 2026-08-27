"""
Read-time row and column pruning for parquet reads (ADR 0007).

Pruning is an optimization: every decision here may safely decline, and under-pruning only
costs a wider read. Which file is being read decides how much can be pruned, so the two
provenances get their own front door rather than a flag —
:func:`read_parquet_pruned` for a user's file, :func:`read_cache_pruned` for one we wrote.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import clinical_scope.constants as cst
from clinical_scope.io.time_axis import detect_time_axis_in_parquet

logger = logging.getLogger(__name__)

ComputeBounds = Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None]
SelectColumns = Callable[[list[str]], list[str] | None]


@dataclass(frozen=True)
class _PruningPlan:
    """What a pruned read will ask parquet for, decided without reading any bulk data."""

    columns: list[str] | None  # None → read every column
    row_filters: list[tuple] | None  # None → no row predicate
    file_column_count: int  # for the pruning log line


def _resolve_stored_index_field(path: Path) -> pa.Field | None:
    """
    Return the parquet file's materialized index column as a pyarrow field, if any.

    The field of the single index column *path* stores (e.g. written by our own
    ``to_parquet``), else ``None``: a plain ``RangeIndex`` is recorded as a descriptor dict
    rather than a physical column name, and a MultiIndex resolves to several columns.

    The field's *type* is deliberately not judged here: "which column is the index" and "is
    that index a range-comparable time axis" are separate questions, answered at the call site.
    """
    schema = pq.ParquetFile(path).schema_arrow
    pandas_metadata = schema.pandas_metadata
    if not pandas_metadata:
        return None
    index_columns = pandas_metadata.get("index_columns") or []
    if len(index_columns) != 1 or not isinstance(index_columns[0], str):
        return None
    return schema.field(index_columns[0])


def _to_stored_naive(bound: pd.Timestamp | None, tz: str) -> pd.Timestamp | None:
    """Express an aware *bound* in *tz*, then drop the label to match a tz-naive column."""
    if bound is None or bound.tzinfo is None:
        return bound
    return bound.tz_convert(tz).tz_localize(None)


def _build_datetime_row_filters(
    column_name: str,
    kind: str,
    tz: str | None,
    tz_from_name: bool,
    bounds: tuple[pd.Timestamp | None, pd.Timestamp | None],
) -> list[tuple] | None:
    """Turn resolved ``(start, end)`` bounds into pyarrow row filters, or ``None`` if empty."""
    start, end = bounds
    if kind == cst.ParquetPushdownKind.EPOCH_NS:
        start = None if start is None else start.value
        end = None if end is None else end.value
    elif kind == cst.ParquetPushdownKind.TIMESTAMP and tz_from_name and tz is not None:
        # The tz was asserted from the column name, never stored, so the on-disk values are
        # bare wall clock in it. Converting before dropping the label is what keeps a bound
        # expressed in any other zone landing on the right instant.
        start = _to_stored_naive(start, tz)
        end = _to_stored_naive(end, tz)

    filters = [
        filter_clause
        for filter_clause in [
            (column_name, ">=", start) if start is not None else None,
            (column_name, "<=", end) if end is not None else None,
        ]
        if filter_clause is not None
    ]
    return filters or None


def _pruning_plan(
    path: Path,
    compute_bounds: ComputeBounds | None,
    select_columns: SelectColumns | None,
    *,
    index_is_time_axis: bool,
) -> _PruningPlan:
    """
    Decide both prunings for *path*, reading only its schema and a detection sample.

    Two orthogonal prunings, each safe on its own:

    - **Rows** — *compute_bounds* receives the datetime column's tz (``None`` if tz-naive/epoch)
      and returns loose ``(start, end)`` bounds in that tz (either side may be ``None``), or
      ``None`` for no window. Planned only for a range-comparable datetime column.
    - **Columns** — *select_columns* receives the file's column names and returns the subset to
      read (a superset of the finally-selected signals), or ``None`` to read all. Independent
      of any window — the common case is a wide cache with no window set.

    Index-safe: a materialized index is auto-restored by pandas even when omitted from
    ``columns=``; a non-materialized datetime column is unioned back so ``set_datetime_index``
    still finds it; if that column can't be resolved, column pruning is skipped (never drop the
    time axis).

    *index_is_time_axis* declares that the stored index is the time axis whatever its dtype, so
    a non-temporal one (EIT's float64 fractional days) prunes columns instead of falling back to
    reading all of them. A declared axis is not thereby range-comparable, so it never carries a
    row filter — and, since the axis is already accounted for, detection is skipped entirely,
    giving up any pushdown it might have found on a data column.
    """
    file_columns = pq.ParquetFile(path).schema_arrow.names
    requested_columns = None if select_columns is None else select_columns(list(file_columns))

    index_field = _resolve_stored_index_field(path)
    # A timestamp index is also range-comparable, so it can carry the row filter; a declared
    # one is only known to be the axis — enough to prune columns, never enough to filter rows.
    temporal_index = index_field is not None and pa.types.is_timestamp(index_field.type)
    axis_survives_pruning = temporal_index or (index_is_time_axis and index_field is not None)
    want_pushdown = compute_bounds is not None

    # Resolve the datetime column only when needed (row filter, or protecting an axis that
    # isn't the index); detection samples data, so skip it otherwise.
    column_name = kind = tz = None
    tz_from_name = False  # a stored index never asserts one; only name detection can
    if temporal_index:
        column_name = index_field.name
        tz = str(index_field.type.tz) if index_field.type.tz else None
        kind = cst.ParquetPushdownKind.TIMESTAMP
    elif not axis_survives_pruning and (want_pushdown or requested_columns is not None):
        detected = detect_time_axis_in_parquet(path)
        if detected is not None:
            column_name = detected.column_name
            kind = detected.kind
            tz = detected.tz
            tz_from_name = detected.tz_from_name

    columns_to_read = requested_columns
    if columns_to_read is not None and not axis_survives_pruning:
        if column_name is None:
            columns_to_read = None  # unknown datetime axis → don't risk dropping it, read all
        elif column_name not in columns_to_read:
            columns_to_read = [column_name, *columns_to_read]  # keep the time axis in the read

    row_filters = None
    if (
        want_pushdown
        and column_name is not None
        and kind is not None
        and kind != cst.ParquetPushdownKind.OTHER
    ):
        bounds = compute_bounds(tz if kind == cst.ParquetPushdownKind.TIMESTAMP else None)
        if bounds is not None:
            row_filters = _build_datetime_row_filters(column_name, kind, tz, tz_from_name, bounds)

    return _PruningPlan(
        columns=columns_to_read, row_filters=row_filters, file_column_count=len(file_columns)
    )


def _read_with_plan(path: Path, plan: _PruningPlan) -> pd.DataFrame:
    """Execute *plan*, reporting what each pruning actually saved."""
    if plan.columns is not None:
        logger.debug(
            "Parquet column pruning on '%s': reading %d/%d columns.",
            path,
            len(plan.columns),
            plan.file_column_count,
        )

    if plan.row_filters is None:
        return pd.read_parquet(path, columns=plan.columns)

    total_rows = pq.ParquetFile(path).metadata.num_rows
    df = pd.read_parquet(path, filters=plan.row_filters, columns=plan.columns)
    pruned_pct = 100 * (1 - len(df) / total_rows) if total_rows else 0.0
    logger.info(
        "Parquet pushdown on '%s': read %d/%d rows (%.0f%% pruned).",
        path,
        len(df),
        total_rows,
        pruned_pct,
    )
    return df


def read_parquet_pruned(
    path: Path,
    compute_bounds: ComputeBounds | None = None,
    select_columns: SelectColumns | None = None,
) -> pd.DataFrame:
    """
    Read a parquet file of unknown provenance, pruning only what detection can establish.

    A stored index of a non-timestamp type could be anything, so column pruning is declined
    rather than risk dropping the time axis. See :func:`_pruning_plan` for both prunings.
    """
    plan = _pruning_plan(path, compute_bounds, select_columns, index_is_time_axis=False)
    return _read_with_plan(path, plan)


def read_cache_pruned(
    path: Path,
    compute_bounds: ComputeBounds | None = None,
    select_columns: SelectColumns | None = None,
) -> pd.DataFrame:
    """
    Read a parquet cache *we* wrote, whose index is the time axis by construction (ADR 0010).

    That provenance is the one thing detection cannot infer, and it lets a non-timestamp index
    (EIT's float64 fractional days) still prune columns.
    """
    plan = _pruning_plan(path, compute_bounds, select_columns, index_is_time_axis=True)
    return _read_with_plan(path, plan)
