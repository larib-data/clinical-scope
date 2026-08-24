"""
Data inspection module for clinical data sources.

Provides lightweight data structures and serialization helpers for reporting
the available columns, load status, and point counts of each data source
without running the full visualization pipeline.
"""

import csv
import dataclasses
import io
from dataclasses import dataclass, field
from typing import ClassVar

import pandas as pd

import clinical_scope.constants as cst
from clinical_scope.datasource.formatting.timezone import fmt_ts


@dataclass
class ColumnInfo:
    """Statistics for a single DataFrame column."""

    raw_name: str
    is_configured: bool  # True if raw_name appears in database_options field_display
    raw_point_count: int  # Non-null rows in the file as loaded
    # The `filtered_*` names predate time-option handling: these describe the whole _format
    # output — time shift, recording start / day, timezone, then the datetime window.
    filtered_point_count: int  # Non-null rows kept once _format has run
    first_filtered_timestamp: str | None = None  # First kept timestamp, on the formatted axis
    last_filtered_timestamp: str | None = None  # Last kept timestamp, on the formatted axis

    # Display headers for the inspection table (header_text, alignment).
    # Shared between Dash modal and CLI script.
    DISPLAY_HEADERS: ClassVar[list[tuple[str, str]]] = [
        ("Column", "left"),
        ("Configured", "center"),
        ("Raw pts", "right"),
        ("Kept pts", "right"),
        ("% retained", "right"),
        ("First", "left"),
        ("Last", "left"),
    ]

    def display_values(self) -> list[str]:
        """Return display-ready string values, matching ``DISPLAY_HEADERS`` order."""
        percent = (
            f"{self.filtered_point_count / self.raw_point_count * 100:.1f}%"
            if self.raw_point_count > 0
            else "—"
        )
        return [
            self.raw_name,
            "✓" if self.is_configured else "✗",
            f"{self.raw_point_count:,}",
            f"{self.filtered_point_count:,}",
            percent,
            self.first_filtered_timestamp or "—",
            self.last_filtered_timestamp or "—",
        ]


# Shown by both the Dash modal and the CLI summary whenever columns_pruned is set.
PRUNED_VIEW_NOTICE = (
    "Pruned view: only signals configured in database_options were read — "
    "an absent column is unconfigured, not missing from the data."
)


@dataclass
class DataSourceInspection:
    """Inspection result for one data source."""

    datasource_name: str
    status: str  # one of cst.InspectionStatus
    error_message: str | None = None
    file_path: str | None = None
    raw_date_range: tuple[str, str] | None = None  # (iso_start, iso_end) as the file states them
    # (iso_start, iso_end) after _format: time shift, recording start / day, timezone, window.
    filtered_date_range: tuple[str, str] | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    # True when only the configured columns were read: the table is then a partial view of
    # the file, so an absent column means "not configured", not "not in the data".
    columns_pruned: bool = False


# CSV headers: datasource-level fields (hardcoded) + column-level fields (auto-derived)
_CSV_DATASOURCE_HEADERS = [
    "datasource",
    "status",
    "error_message",
    "file_path",
    "raw_date_start",
    "raw_date_end",
    "filtered_date_start",
    "filtered_date_end",
    "columns_pruned",
]
_CSV_COLUMN_HEADERS = [column_field.name for column_field in dataclasses.fields(ColumnInfo)]
_CSV_HEADERS = [*_CSV_DATASOURCE_HEADERS, *_CSV_COLUMN_HEADERS]


def to_csv_string(results: list[DataSourceInspection]) -> str:
    """
    Convert inspection results to a CSV string.

    One row per column per datasource.
    Datasources with errors emit one row with empty column fields.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CSV_HEADERS)

    for result in results:
        raw_start = result.raw_date_range[0] if result.raw_date_range else ""
        raw_end = result.raw_date_range[1] if result.raw_date_range else ""
        flt_start = result.filtered_date_range[0] if result.filtered_date_range else ""
        flt_end = result.filtered_date_range[1] if result.filtered_date_range else ""

        datasource_row = [
            result.datasource_name,
            result.status,
            result.error_message or "",
            result.file_path or "",
            raw_start,
            raw_end,
            flt_start,
            flt_end,
            result.columns_pruned,
        ]
        if not result.columns:
            writer.writerow(datasource_row + [""] * len(_CSV_COLUMN_HEADERS))
        else:
            for column in result.columns:
                column_dict = dataclasses.asdict(column)
                column_values = [
                    column_dict[column_field.name]
                    for column_field in dataclasses.fields(ColumnInfo)
                ]
                writer.writerow(datasource_row + column_values)

    return output.getvalue()


def to_text_summary(results: list[DataSourceInspection]) -> str:
    """
    Format inspection results as a plain-text summary.

    Column values match the app's inspection modal table
    (driven by ``ColumnInfo.DISPLAY_HEADERS`` / ``ColumnInfo.display_values``).
    """
    lines: list[str] = []
    column_headers = [header_text for header_text, _ in ColumnInfo.DISPLAY_HEADERS]

    for result in results:
        status_marker = "OK  " if result.status == cst.InspectionStatus.OK else "FAIL"
        lines.append(f"[{status_marker}]  {result.datasource_name}  ({result.status})")
        if result.error_message:
            lines.append(f"         Error: {result.error_message}")
        if result.file_path:
            lines.append(f"         File:  {result.file_path}")
        if result.raw_date_range:
            lines.append(
                f"         Dates in file:      "
                f"{result.raw_date_range[0]}  →  {result.raw_date_range[1]}"
            )
        if result.filtered_date_range:
            lines.append(
                f"         After time options: "
                f"{result.filtered_date_range[0]}  →  {result.filtered_date_range[1]}"
            )
        if result.columns_pruned:
            lines.append(f"         {PRUNED_VIEW_NOTICE}")
        if result.columns:
            lines.append(f"         Columns ({len(result.columns)}):")
            for column in result.columns:
                values = column.display_values()
                parts = [
                    f"{header_text}: {value}"
                    for header_text, value in zip(column_headers, values, strict=True)
                ]
                lines.append(f"           {' | '.join(parts)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def results_to_json(results: list[DataSourceInspection]) -> list[dict]:
    """Serialize inspection results to a JSON-compatible list for dcc.Store."""
    return [dataclasses.asdict(result) for result in results]


def results_from_json(data: list[dict]) -> list[DataSourceInspection]:
    """Deserialize inspection results from a dcc.Store list."""
    return [
        DataSourceInspection(
            **{
                **entry,
                "columns": [ColumnInfo(**column_dict) for column_dict in entry.get("columns", [])],
                "raw_date_range": (
                    tuple(entry["raw_date_range"]) if entry.get("raw_date_range") else None
                ),
                "filtered_date_range": (
                    tuple(entry["filtered_date_range"])
                    if entry.get("filtered_date_range")
                    else None
                ),
            }
        )
        for entry in data
    ]


# ==================================================================================================
# Column info helpers (used by datasource_base inspection logic)
# ==================================================================================================


def _first_last_timestamp(df: pd.DataFrame, column: str) -> tuple[str | None, str | None]:
    """Return (first, last) compact timestamp strings for valid (non-NaN) values in a column."""

    if column not in df.columns:
        return None, None
    valid_index = df.index[df[column].notna()]
    if valid_index.empty:
        return None, None
    return fmt_ts(valid_index.min()), fmt_ts(valid_index.max())


def _column_infos(
    df_raw: pd.DataFrame,
    df_filtered: pd.DataFrame,
    configured_fields: set[str],
) -> list:
    """Build a list of ColumnInfo objects from raw and filtered DataFrames."""
    column_infos = []
    for column in df_raw.columns:
        first_timestamp, last_timestamp = _first_last_timestamp(df_filtered, column)
        column_infos.append(
            ColumnInfo(
                raw_name=column,
                is_configured=column in configured_fields,
                raw_point_count=int(df_raw[column].notna().sum()),
                filtered_point_count=(
                    int(df_filtered[column].notna().sum()) if column in df_filtered.columns else 0
                ),
                first_filtered_timestamp=first_timestamp,
                last_filtered_timestamp=last_timestamp,
            )
        )
    return column_infos
