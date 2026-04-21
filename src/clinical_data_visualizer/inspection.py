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
from datetime import datetime
from typing import ClassVar


def _fmt_ts_display(ts: str | None) -> str:
    """Format a stored ISO timestamp to a compact human-readable string for display."""
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(ts).strftime("%y-%m-%d %H:%M:%S %Z").rstrip()
    except (ValueError, TypeError):
        return ts


@dataclass
class ColumnInfo:
    """Statistics for a single DataFrame column."""

    raw_name: str
    is_configured: bool  # True if raw_name appears in database_options field_display
    raw_point_count: int  # Non-null rows in the loaded (unfiltered) DataFrame
    filtered_point_count: int  # Non-null rows after datetime filter
    first_filtered_timestamp: str | None = None  # ISO timestamp of first valid filtered point
    last_filtered_timestamp: str | None = None  # ISO timestamp of last valid filtered point

    # Display headers for the inspection table (header_text, alignment).
    # Shared between Dash modal and CLI script.
    DISPLAY_HEADERS: ClassVar[list[tuple[str, str]]] = [
        ("Column", "left"),
        ("Configured", "center"),
        ("Raw pts", "right"),
        ("Filtered pts", "right"),
        ("% retained", "right"),
        ("First (filtered)", "left"),
        ("Last (filtered)", "left"),
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
            _fmt_ts_display(self.first_filtered_timestamp),
            _fmt_ts_display(self.last_filtered_timestamp),
        ]


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


def to_text_summary(results: list[DataSourceInspection]) -> str:
    """
    Format inspection results as a plain-text summary.

    Column values match the app's inspection modal table
    (driven by ``ColumnInfo.DISPLAY_HEADERS`` / ``ColumnInfo.display_values``).
    """
    lines: list[str] = []
    col_headers = [h for h, _ in ColumnInfo.DISPLAY_HEADERS]

    for r in results:
        status_marker = "OK  " if r.status == "ok" else "FAIL"
        lines.append(f"[{status_marker}]  {r.datasource_name}  ({r.status})")
        if r.error_message:
            lines.append(f"         Error: {r.error_message}")
        if r.file_path:
            lines.append(f"         File:  {r.file_path}")
        if r.raw_date_range:
            lines.append(
                f"         Raw dates:      "
                f"{_fmt_ts_display(r.raw_date_range[0])}  →  {_fmt_ts_display(r.raw_date_range[1])}"
            )
        if r.filtered_date_range:
            lines.append(
                f"         Filtered dates: "
                f"{_fmt_ts_display(r.filtered_date_range[0])}  →  "
                f"{_fmt_ts_display(r.filtered_date_range[1])}"
            )
        if r.columns:
            lines.append(f"         Columns ({len(r.columns)}):")
            for col in r.columns:
                vals = col.display_values()
                parts = [f"{h}: {v}" for h, v in zip(col_headers, vals, strict=True)]
                lines.append(f"           {' | '.join(parts)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
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
