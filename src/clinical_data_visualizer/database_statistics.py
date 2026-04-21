"""
Database-level aggregate statistics across multiple patients.

Computes metadata-level statistics (signal presence, duration, completeness,
temporal overlap, sampling rates, configuration coverage) from per-patient
inspection results — without loading full DataFrames into memory.
"""

import csv
import dataclasses
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from clinical_data_visualizer.inspection import DataSourceInspection

logger = logging.getLogger(__name__)


# ==================================================================================================
# Dataclasses
# ==================================================================================================


@dataclass
class ColumnAggregateStats:
    """Aggregate statistics for a single column across patients."""

    raw_name: str
    patient_count: int = 0  # Patients with >0 filtered points for this column
    total_points: int = 0
    mean_points: float = 0.0
    min_points: int = 0
    max_points: int = 0
    mean_sampling_rate_hz: float | None = None
    configured_count: int = 0  # Patients where this column is configured


@dataclass
class DatasourceSummary:
    """Per-datasource summary across all patients."""

    datasource_name: str
    patient_count: int = 0  # Patients with status "ok"
    total_patients: int = 0
    config_coverage: float = 0.0  # Mean fraction of configured columns
    columns: dict[str, ColumnAggregateStats] = field(default_factory=dict)


@dataclass
class PatientSummary:
    """Per-patient summary across all datasources."""

    patient_name: str
    datasource_statuses: dict[str, str] = field(default_factory=dict)
    completeness_score: float = 0.0
    earliest_timestamp: str | None = None
    latest_timestamp: str | None = None
    total_duration_hours: float | None = None


@dataclass
class DatabaseStatistics:
    """Aggregate statistics for a database of patients."""

    root_folder: str
    timestamp: str  # ISO timestamp of computation
    total_patients: int = 0
    datasource_names: list[str] = field(default_factory=list)
    patient_summaries: list[PatientSummary] = field(default_factory=list)
    datasource_summaries: list[DatasourceSummary] = field(default_factory=list)
    presence_matrix: dict[str, dict[str, str]] = field(default_factory=dict)
    temporal_overlap: dict[str, dict[str, int]] = field(default_factory=dict)


# ==================================================================================================
# Helpers
# ==================================================================================================


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp string, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _duration_seconds(start: str | None, end: str | None) -> float | None:
    """Compute duration in seconds between two ISO timestamps."""
    dt_start = _parse_iso(start)
    dt_end = _parse_iso(end)
    if dt_start is None or dt_end is None:
        return None
    delta = (dt_end - dt_start).total_seconds()
    return delta if delta > 0 else None


def _ranges_overlap(range_a: tuple[str, str] | None, range_b: tuple[str, str] | None) -> bool:
    """Check if two (iso_start, iso_end) ranges overlap."""
    if range_a is None or range_b is None:
        return False
    start_a, end_a = _parse_iso(range_a[0]), _parse_iso(range_a[1])
    start_b, end_b = _parse_iso(range_b[0]), _parse_iso(range_b[1])
    if any(t is None for t in (start_a, end_a, start_b, end_b)):
        return False
    try:
        return max(start_a, start_b) < min(end_a, end_b)
    except TypeError:
        # Mixed tz-aware / tz-naive datetimes cannot be compared
        return False


# ==================================================================================================
# Core computation
# ==================================================================================================


def compute_database_statistics(
    per_patient_inspections: dict[str, list[DataSourceInspection]],
    root_folder: str = "",
) -> DatabaseStatistics:
    """
    Compute aggregate statistics from per-patient inspection results.

    Args:
        per_patient_inspections: ``{patient_name: list[DataSourceInspection]}``.
        root_folder: Path string for display purposes.

    Returns:
        A fully populated :class:`DatabaseStatistics`.

    """
    all_ds_names: set[str] = set()
    for inspections in per_patient_inspections.values():
        for insp in inspections:
            all_ds_names.add(insp.datasource_name)
    ds_names_sorted = sorted(all_ds_names)

    # ---- Per-patient summaries + presence matrix ----
    patient_summaries: list[PatientSummary] = []
    presence_matrix: dict[str, dict[str, str]] = {}

    # Accumulators for datasource-level aggregation
    ds_ok_counts: dict[str, int] = dict.fromkeys(ds_names_sorted, 0)
    ds_col_stats: dict[str, dict[str, list[tuple[int, float | None, bool]]]] = {
        ds: {} for ds in ds_names_sorted
    }
    ds_config_coverages: dict[str, list[float]] = {ds: [] for ds in ds_names_sorted}

    # For temporal overlap: store per-patient filtered_date_range by datasource
    patient_ds_ranges: dict[str, dict[str, tuple[str, str] | None]] = {}

    for patient_name, inspections in sorted(per_patient_inspections.items()):
        insp_by_ds = {i.datasource_name: i for i in inspections}
        statuses: dict[str, str] = {}
        patient_timestamps: list[datetime] = []

        for ds_name in ds_names_sorted:
            insp = insp_by_ds.get(ds_name)
            if insp is None:
                statuses[ds_name] = "not_inspected"
                continue
            statuses[ds_name] = insp.status

            if insp.status == "ok":
                ds_ok_counts[ds_name] += 1

                # Collect timestamps for patient-level range
                if insp.filtered_date_range:
                    for ts_str in insp.filtered_date_range:
                        dt = _parse_iso(ts_str)
                        if dt is not None:
                            patient_timestamps.append(dt)

                # Column-level accumulation
                total_cols = len(insp.columns) if insp.columns else 0
                configured_cols = sum(1 for c in insp.columns if c.is_configured)
                if total_cols > 0:
                    ds_config_coverages[ds_name].append(configured_cols / total_cols)

                for col in insp.columns:
                    col_list = ds_col_stats[ds_name].setdefault(col.raw_name, [])
                    duration = _duration_seconds(
                        col.first_filtered_timestamp, col.last_filtered_timestamp
                    )
                    col_list.append((col.filtered_point_count, duration, col.is_configured))

        # Store ranges for temporal overlap
        patient_ds_ranges[patient_name] = {
            ds: insp_by_ds[ds].filtered_date_range
            for ds in ds_names_sorted
            if ds in insp_by_ds and insp_by_ds[ds].filtered_date_range
        }

        # Completeness score
        ok_count = sum(1 for s in statuses.values() if s == "ok")
        total_inspected = sum(1 for s in statuses.values() if s != "not_inspected")
        completeness = ok_count / total_inspected if total_inspected > 0 else 0.0

        # Patient time range
        earliest = min(patient_timestamps) if patient_timestamps else None
        latest = max(patient_timestamps) if patient_timestamps else None
        dur_hours = None
        if earliest and latest:
            dur_hours = (latest - earliest).total_seconds() / 3600.0

        patient_summaries.append(
            PatientSummary(
                patient_name=patient_name,
                datasource_statuses=statuses,
                completeness_score=completeness,
                earliest_timestamp=earliest.isoformat() if earliest else None,
                latest_timestamp=latest.isoformat() if latest else None,
                total_duration_hours=dur_hours,
            )
        )
        presence_matrix[patient_name] = statuses

    # ---- Datasource summaries ----
    datasource_summaries: list[DatasourceSummary] = []
    total_patients = len(per_patient_inspections)

    for ds_name in ds_names_sorted:
        columns_agg: dict[str, ColumnAggregateStats] = {}
        for col_name, entries in ds_col_stats[ds_name].items():
            points = [pt for pt, _, _ in entries]
            rates = []
            for pt, dur, _ in entries:
                if dur and dur > 0 and pt > 0:
                    rates.append(pt / dur)
            configured = sum(1 for _, _, cfg in entries if cfg)
            n = len(points)

            columns_agg[col_name] = ColumnAggregateStats(
                raw_name=col_name,
                patient_count=sum(1 for p in points if p > 0),
                total_points=sum(points),
                mean_points=sum(points) / n if n > 0 else 0.0,
                min_points=min(points) if n > 0 else 0,
                max_points=max(points) if n > 0 else 0,
                mean_sampling_rate_hz=sum(rates) / len(rates) if rates else None,
                configured_count=configured,
            )

        coverages = ds_config_coverages[ds_name]
        datasource_summaries.append(
            DatasourceSummary(
                datasource_name=ds_name,
                patient_count=ds_ok_counts[ds_name],
                total_patients=total_patients,
                config_coverage=sum(coverages) / len(coverages) if coverages else 0.0,
                columns=columns_agg,
            )
        )

    # ---- Temporal overlap matrix ----
    temporal_overlap: dict[str, dict[str, int]] = {}
    for ds_a in ds_names_sorted:
        temporal_overlap[ds_a] = {}
        for ds_b in ds_names_sorted:
            count = 0
            for ranges in patient_ds_ranges.values():
                range_a = ranges.get(ds_a)
                range_b = ranges.get(ds_b)
                if _ranges_overlap(range_a, range_b):
                    count += 1
            temporal_overlap[ds_a][ds_b] = count

    return DatabaseStatistics(
        root_folder=root_folder,
        timestamp=datetime.now(tz=UTC).isoformat(),
        total_patients=total_patients,
        datasource_names=ds_names_sorted,
        patient_summaries=patient_summaries,
        datasource_summaries=datasource_summaries,
        presence_matrix=presence_matrix,
        temporal_overlap=temporal_overlap,
    )


# ==================================================================================================
# Serialization
# ==================================================================================================


def stats_to_json(stats: DatabaseStatistics) -> dict:
    """Serialize a :class:`DatabaseStatistics` to a JSON-compatible dict for ``dcc.Store``."""
    return dataclasses.asdict(stats)


def stats_from_json(data: dict) -> DatabaseStatistics:
    """Deserialize a :class:`DatabaseStatistics` from a ``dcc.Store`` dict."""
    return DatabaseStatistics(
        root_folder=data["root_folder"],
        timestamp=data["timestamp"],
        total_patients=data["total_patients"],
        datasource_names=data["datasource_names"],
        patient_summaries=[PatientSummary(**ps) for ps in data.get("patient_summaries", [])],
        datasource_summaries=[
            DatasourceSummary(
                **{
                    **ds,
                    "columns": {
                        k: ColumnAggregateStats(**v) for k, v in ds.get("columns", {}).items()
                    },
                }
            )
            for ds in data.get("datasource_summaries", [])
        ],
        presence_matrix=data.get("presence_matrix", {}),
        temporal_overlap=data.get("temporal_overlap", {}),
    )


# ==================================================================================================
# CSV export
# ==================================================================================================


def to_csv_string(stats: DatabaseStatistics) -> str:
    """
    Export database statistics as a CSV string.

    One row per patient, columns include status per datasource plus metrics.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    ds_names = stats.datasource_names
    headers = [
        "patient",
        "completeness_score",
        "earliest_timestamp",
        "latest_timestamp",
        "total_duration_hours",
        *[f"{ds}_status" for ds in ds_names],
    ]
    writer.writerow(headers)

    for ps in stats.patient_summaries:
        row = [
            ps.patient_name,
            f"{ps.completeness_score:.2f}",
            ps.earliest_timestamp or "",
            ps.latest_timestamp or "",
            f"{ps.total_duration_hours:.2f}" if ps.total_duration_hours is not None else "",
            *[ps.datasource_statuses.get(ds, "") for ds in ds_names],
        ]
        writer.writerow(row)

    return output.getvalue()


# ==================================================================================================
# Text summary
# ==================================================================================================


def to_text_summary(stats: DatabaseStatistics) -> str:
    """Format database statistics as a plain-text summary for CLI output."""
    lines: list[str] = []

    # ---- Header ----
    lines.append(f"Database Statistics — {stats.root_folder}")
    lines.append(f"Computed: {stats.timestamp}")
    lines.append(f"Patients: {stats.total_patients}")
    lines.append(f"Datasources: {len(stats.datasource_names)}")
    lines.append("")

    # ---- Presence matrix ----
    if stats.patient_summaries:
        status_short = {
            "ok": "OK",
            "file_not_found": "---",
            "load_error": "ERR",
            "format_error": "FMT",
            "not_inspected": ".",
        }
        lines.append("=== Presence Matrix ===")
        lines.append("(OK=loaded  ---=not found  ERR=load error  FMT=format error  .=n/a)")
        # Column widths: at least as wide as the datasource name or the status marker
        name_width = max(len(ps.patient_name) for ps in stats.patient_summaries)
        name_width = max(name_width, 7)  # "Patient"
        ds_widths = [max(len(ds), 3) for ds in stats.datasource_names]

        header = f"{'Patient':<{name_width}}"
        for ds, w in zip(stats.datasource_names, ds_widths, strict=True):
            header += f"  {ds:>{w}}"
        header += "  Completeness"
        lines.append(header)
        lines.append("-" * len(header))

        for ps in stats.patient_summaries:
            row = f"{ps.patient_name:<{name_width}}"
            for ds, w in zip(stats.datasource_names, ds_widths, strict=True):
                status = ps.datasource_statuses.get(ds, ".")
                marker = status_short.get(status, status[:3])
                row += f"  {marker:>{w}}"
            row += f"  {ps.completeness_score:.0%}"
            lines.append(row)
        lines.append("")

    # ---- Datasource summaries ----
    if stats.datasource_summaries:
        lines.append("=== Datasource Summaries ===")
        for ds_sum in stats.datasource_summaries:
            lines.append(
                f"  {ds_sum.datasource_name}: "
                f"{ds_sum.patient_count}/{ds_sum.total_patients} patients OK, "
                f"config coverage {ds_sum.config_coverage:.0%}, "
                f"{len(ds_sum.columns)} column(s)"
            )
            for col_stats in ds_sum.columns.values():
                rate_str = (
                    f"{col_stats.mean_sampling_rate_hz:.2f} Hz"
                    if col_stats.mean_sampling_rate_hz is not None
                    else "—"
                )
                lines.append(
                    f"    {col_stats.raw_name}: "
                    f"{col_stats.patient_count} patient(s), "
                    f"pts {col_stats.min_points:,}–{col_stats.max_points:,} "
                    f"(mean {col_stats.mean_points:,.0f}), "
                    f"rate {rate_str}, "
                    f"configured {col_stats.configured_count}x"
                )
        lines.append("")

    # ---- Temporal overlap ----
    if stats.temporal_overlap and len(stats.datasource_names) > 1:
        lines.append("=== Temporal Overlap (patients with overlapping date ranges) ===")
        ds_names = stats.datasource_names
        col_w = max(max(len(ds) for ds in ds_names), 4)

        header = " " * (col_w + 2)
        for ds in ds_names:
            header += f"{ds:>{col_w}}  "
        lines.append(header)

        for ds_a in ds_names:
            row = f"{ds_a:<{col_w}}  "
            for ds_b in ds_names:
                count = stats.temporal_overlap.get(ds_a, {}).get(ds_b, 0)
                row += f"{count:>{col_w}}  "
            lines.append(row)
        lines.append("")

    return "\n".join(lines)
