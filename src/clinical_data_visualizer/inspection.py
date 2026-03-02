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


@dataclass
class ColumnInfo:
    """Statistics for a single DataFrame column."""

    raw_name: str
    is_configured: bool  # True if raw_name appears in database_options field_display
    raw_point_count: int  # Non-null rows in the loaded (unfiltered) DataFrame
    filtered_point_count: int  # Non-null rows after datetime filter
    first_filtered_timestamp: str | None = None  # ISO timestamp of first valid filtered point
    last_filtered_timestamp: str | None = None  # ISO timestamp of last valid filtered point


@dataclass
class DataSourceInspection:
    """Inspection result for one data source."""

    datasource_name: str
    status: str  # "ok" | "file_not_found" | "load_error" | "format_error"
    error_message: str | None = None
    file_path: str | None = None
    raw_date_range: tuple[str, str] | None = None  # (iso_start, iso_end) before filter
    filtered_date_range: tuple[str, str] | None = None  # (iso_start, iso_end) after filter
    columns: list[ColumnInfo] = field(default_factory=list)


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
]
_CSV_COLUMN_HEADERS = [f.name for f in dataclasses.fields(ColumnInfo)]
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

    for r in results:
        raw_start = r.raw_date_range[0] if r.raw_date_range else ""
        raw_end = r.raw_date_range[1] if r.raw_date_range else ""
        flt_start = r.filtered_date_range[0] if r.filtered_date_range else ""
        flt_end = r.filtered_date_range[1] if r.filtered_date_range else ""

        datasource_row = [
            r.datasource_name,
            r.status,
            r.error_message or "",
            r.file_path or "",
            raw_start,
            raw_end,
            flt_start,
            flt_end,
        ]
        if not r.columns:
            writer.writerow(datasource_row + [""] * len(_CSV_COLUMN_HEADERS))
        else:
            for col in r.columns:
                col_dict = dataclasses.asdict(col)
                col_values = [col_dict[f.name] for f in dataclasses.fields(ColumnInfo)]
                writer.writerow(datasource_row + col_values)

    return output.getvalue()


def results_to_json(results: list[DataSourceInspection]) -> list[dict]:
    """Serialize inspection results to a JSON-compatible list for dcc.Store."""
    return [dataclasses.asdict(r) for r in results]


def results_from_json(data: list[dict]) -> list[DataSourceInspection]:
    """Deserialize inspection results from a dcc.Store list."""
    return [
        DataSourceInspection(
            **{
                **d,
                "columns": [ColumnInfo(**c) for c in d.get("columns", [])],
                "raw_date_range": tuple(d["raw_date_range"]) if d.get("raw_date_range") else None,
                "filtered_date_range": (
                    tuple(d["filtered_date_range"]) if d.get("filtered_date_range") else None
                ),
            }
        )
        for d in data
    ]
