import csv
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.other.options as options_naming
from clinical_data_visualizer.datasource_base import DataSourceBase, fmt_ts
from clinical_data_visualizer.inspection import ColumnInfo, DataSourceInspection
from clinical_data_visualizer.signal_container import (
    Data,
    Metadata,
    PlotOptions,
    Signal,
    TraceOptions,
)

logger = logging.getLogger(__name__)


def _detect_and_set_datetime_index(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Detect a datetime column and set it as the DataFrame index.

    Strategy:
    1. If index is already DatetimeIndex, return as-is.
    2. Search columns by name (case-insensitive) against CANDIDATE_LIST.
    3. For each candidate: accept datetime64 directly, skip numeric columns,
       try parsing string/object columns with validation.
    4. Last resort: try every non-numeric column.
    5. Return None if nothing works (file will be skipped).
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return df

    candidates = options_naming.CANDIDATE_LIST_DATETIME_COLUMN
    col_lower_map = {col.lower().strip(): col for col in df.columns}

    # Step 2-3: Search by candidate name
    for candidate_name in candidates:
        actual_col = col_lower_map.get(candidate_name)
        if actual_col is None:
            continue

        series = df[actual_col]

        if pd.api.types.is_datetime64_any_dtype(series):
            return df.set_index(actual_col)

        if pd.api.types.is_numeric_dtype(series):
            logger.debug(
                "Skipping candidate column '%s': numeric dtype (likely relative time)",
                actual_col,
            )
            continue

        parsed = _try_parse_datetime_column(series)
        if parsed is not None:
            df[actual_col] = parsed
            return df.set_index(actual_col)

    # Step 4: Last resort — try every non-numeric column
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        if pd.api.types.is_datetime64_any_dtype(series):
            return df.set_index(col)

        parsed = _try_parse_datetime_column(series)
        if parsed is not None:
            logger.info("Using column '%s' as datetime index (last-resort detection)", col)
            df[col] = parsed
            return df.set_index(col)

    return None


def _try_parse_datetime_column(series: pd.Series) -> pd.Series | None:
    """
    Try to parse a Series as datetime with validation.

    Validates that >50% of values are non-NaT and all parsed years are in [2000, 2100].
    """
    min_valid_year = 2000
    max_valid_year = 2100

    try:
        parsed = pd.to_datetime(series, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return None

    valid_mask = parsed.notna()
    if valid_mask.sum() < 0.5 * len(parsed):
        return None

    years = parsed[valid_mask].dt.year
    if (years < min_valid_year).any() or (years > max_valid_year).any():
        return None

    return parsed


def _load_single_file(file_path: Path) -> pd.DataFrame:
    """Load a single CSV or parquet file into a DataFrame."""
    suffix = file_path.suffix.lower()

    if suffix == ".parquet":
        return pd.read_parquet(file_path)

    if suffix == ".csv":
        with Path.open(file_path, "r", newline="") as f:
            sample = f.read(4096)
            try:
                dialect = csv.Sniffer().sniff(sample)
                sep = dialect.delimiter
            except csv.Error:
                sep = ","

        return pd.read_csv(file_path, sep=sep)

    msg = f"Unsupported file extension: {suffix}"
    raise ValueError(msg)


def _create_signal(
    col_name: str,
    display_name: str,
    df: pd.DataFrame,
    source_options: dict,
) -> Signal:
    """Create a Signal object from a single DataFrame column."""
    y_full = df[col_name].to_numpy(dtype=np.float64)
    valid_mask = np.isfinite(y_full)
    x = df.index[valid_mask].to_numpy(dtype="datetime64[ns]")
    y = y_full[valid_mask]
    timezone = df.index.tz

    data = Data(x=x, y=y, timezone=timezone)

    trace_dict = source_options.get(cst.SourceOptions.TRACE_OPTIONS, {})
    valid_trace_keys = {"mode", "line_width", "line_dash", "opacity", "line_color", "marker_symbol"}

    plot_options = PlotOptions(
        plot_type=cst.PlotType.TIME_SERIES,
        y_unit_name=cst.DatabaseOptions.Signal.DEFAULT_UNIT,
    )

    trace_options = TraceOptions(
        plot_options=plot_options,
        **{k: v for k, v in trace_dict.items() if k in valid_trace_keys},
    )

    return Signal(
        raw_name=col_name,
        name=display_name,
        data=data,
        trace_options=trace_options,
        metadata=Metadata(),
    )


class OtherDataSource(DataSourceBase):
    """Generic datasource processor for CSV and parquet files."""

    OPTIONS_MODULE = options_naming

    @classmethod
    def _load(
        cls, file_path_list: Path | list[Path], path_output: Path | None, **kwargs
    ) -> pd.DataFrame:
        """Not used — main() processes each file independently."""
        msg = "OtherDataSource._load should not be called directly; use main() instead"
        raise NotImplementedError(msg)

    @classmethod
    def extract(
        cls,
        patient_options: dict,  # noqa: ARG003
        database_options_specific: dict | None = None,  # noqa: ARG003
        save_path: str | Path | None = None,  # noqa: ARG003
    ) -> pd.DataFrame | None:
        """
        Not supported for the 'other' datasource.

        The 'other' datasource processes multiple files independently (each file
        becomes its own signal group), so a single-DataFrame extraction is not
        meaningful. Use main() for visualization or inspect() for metadata.
        """
        logger.debug(
            "[%s] extract() is not supported — each file is processed independently. Skipping.",
            cls.DATASOURCE_NAME,
        )
        return None

    @classmethod
    def main(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
    ) -> list[Signal]:
        """
        Process each file independently, creating one subplot group per file.

        Each file becomes a separate PlotGroup (subplot) with all its numeric
        columns as traces. Files that fail to load are skipped without affecting others.
        Populates database_options_specific['grouped_fields'] so the wrapper groups
        signals by source file.
        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])

        # Find folder
        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return []

        # Find files
        file_paths = cls._find(search_folder)
        if file_paths is None:
            return []

        all_signals = []
        grouped_fields = {}

        for file_path in file_paths:
            try:
                df = _load_single_file(file_path)

                result = _detect_and_set_datetime_index(df)
                if result is None:
                    logger.warning(
                        "No datetime index detected in '%s', skipping file", file_path.name
                    )
                    continue
                df = result

                # Convert remaining columns to numeric
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                # Drop columns that are entirely NaN after coercion
                df = df.dropna(axis=1, how="all")

                if df.empty or len(df.columns) == 0:
                    logger.warning("No numeric columns in '%s', skipping file", file_path.name)
                    continue

                # Remove duplicate timestamps
                df = df[~df.index.duplicated(keep="first")]
                df = df.sort_index()

                # Apply formatting (timezone, time shift, datetime filter)
                df = cls._format(df, patient_options, database_options)

                if df.empty:
                    logger.warning("No data after filtering in '%s', skipping file", file_path.name)
                    continue

                # Create signals for each column, with per-file prefix for uniqueness
                file_stem = file_path.stem
                file_signal_raw_names = []

                for col_name in df.columns:
                    raw_name = f"{file_stem}::{col_name}"
                    try:
                        sig = _create_signal(
                            col_name=col_name,
                            display_name=col_name,
                            df=df,
                            source_options=cls.SOURCE_OPTIONS,
                        )
                        # Override raw_name for global uniqueness
                        sig.raw_name = raw_name
                        sig.metadata.datasource_name = cls.DATASOURCE_NAME
                        all_signals.append(sig)
                        file_signal_raw_names.append(raw_name)
                    except Exception:
                        logger.exception(
                            "Could not process signal '%s' from '%s'", col_name, file_path.name
                        )

                if file_signal_raw_names:
                    grouped_fields[file_stem] = file_signal_raw_names

            except Exception:
                logger.exception("Failed to process '%s', skipping", file_path.name)
                continue

        # Inject grouped_fields into database_options for the wrapper to use
        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        group_by_file = patient_options_specific.get(
            options_naming.PatientOptionsDataSourceRelative.GroupByFile.NAME,
            options_naming.PatientOptionsDataSourceRelative.GroupByFile.DEFAULT,
        )
        if group_by_file:
            database_options[cst.DatabaseOptions.GROUPED_FIELDS] = grouped_fields

        return all_signals

    @classmethod
    def inspect(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
    ) -> DataSourceInspection:
        """
        Inspect all CSV/parquet files in the other datasource folder.

        Overrides DataSourceBase.inspect() because OtherDataSource._load() raises
        NotImplementedError (files are processed individually in main()).
        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )
        configured_fields = set(database_options.get(cst.DatabaseOptions.FIELD_DISPLAY, []))

        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME, status="file_not_found"
            )

        file_paths = cls._find(search_folder)
        if not file_paths:
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME, status="file_not_found"
            )

        # Aggregate column stats across all files.
        # Keys use the same "{stem}::{col}" format as main() for consistency.
        all_raw_counts: dict[str, int] = {}
        all_filtered_counts: dict[str, int] = {}
        col_first_ts: dict[str, object] = {}  # per-column earliest filtered Timestamp object
        col_last_ts: dict[str, object] = {}  # per-column latest filtered Timestamp object
        min_raw, max_raw = None, None
        min_flt, max_flt = None, None

        for fp in file_paths:
            try:
                df = _load_single_file(fp)
                df = _detect_and_set_datetime_index(df)
                if df is None:
                    logger.warning("inspect: no datetime index in '%s', skipping", fp.name)
                    continue

                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(axis=1, how="all")
                if df.empty or len(df.columns) == 0:
                    continue

                df = df[~df.index.duplicated(keep="first")].sort_index()

                if not df.empty:
                    lo, hi = df.index.min(), df.index.max()
                    min_raw = lo if min_raw is None else min(min_raw, lo)
                    max_raw = hi if max_raw is None else max(max_raw, hi)

                for col in df.columns:
                    raw_name = f"{fp.stem}::{col}"
                    all_raw_counts[raw_name] = all_raw_counts.get(raw_name, 0) + int(
                        df[col].notna().sum()
                    )

                try:
                    df_flt = cls._format(df, patient_options, database_options)
                    if not df_flt.empty:
                        lo, hi = df_flt.index.min(), df_flt.index.max()
                        min_flt = lo if min_flt is None else min(min_flt, lo)
                        max_flt = hi if max_flt is None else max(max_flt, hi)
                    for col in df_flt.columns:
                        raw_name = f"{fp.stem}::{col}"
                        all_filtered_counts[raw_name] = all_filtered_counts.get(raw_name, 0) + int(
                            df_flt[col].notna().sum()
                        )
                        valid_idx = df_flt.index[df_flt[col].notna()]
                        if not valid_idx.empty:
                            first_ts = valid_idx.min()
                            last_ts = valid_idx.max()
                            if raw_name not in col_first_ts or first_ts < col_first_ts[raw_name]:
                                col_first_ts[raw_name] = first_ts
                            if raw_name not in col_last_ts or last_ts > col_last_ts[raw_name]:
                                col_last_ts[raw_name] = last_ts
                except Exception:
                    logger.exception("inspect: format failed for '%s'", fp.name)

            except Exception:
                logger.exception("inspect: failed to load '%s'", fp.name)

        if not all_raw_counts:
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status="load_error",
                error_message="No readable files found in folder",
                file_path=str(search_folder),
            )

        columns = [
            ColumnInfo(
                raw_name=raw_name,
                is_configured=raw_name in configured_fields,
                raw_point_count=raw_count,
                filtered_point_count=all_filtered_counts.get(raw_name, 0),
                first_filtered_timestamp=(
                    fmt_ts(col_first_ts[raw_name]) if raw_name in col_first_ts else None
                ),
                last_filtered_timestamp=(
                    fmt_ts(col_last_ts[raw_name]) if raw_name in col_last_ts else None
                ),
            )
            for raw_name, raw_count in all_raw_counts.items()
        ]
        raw_date_range = (fmt_ts(min_raw), fmt_ts(max_raw)) if min_raw is not None else None
        filtered_date_range = (fmt_ts(min_flt), fmt_ts(max_flt)) if min_flt is not None else None

        return DataSourceInspection(
            datasource_name=cls.DATASOURCE_NAME,
            status="ok",
            file_path=str(search_folder),
            raw_date_range=raw_date_range,
            filtered_date_range=filtered_date_range,
            columns=columns,
        )


def main(patient_options: dict, database_options_specific: dict | None) -> list[Signal]:
    """Load and process generic 'other' data."""
    return OtherDataSource.main(patient_options, database_options_specific)
