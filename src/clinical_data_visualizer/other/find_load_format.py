import csv
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.other.options as options_naming
from clinical_data_visualizer.datasource_base import DataSourceBase
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
        y_unit_name=cst.DatabaseOptions.Data.DEFAULT_UNIT_INFO,
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

    DATASOURCE_NAME = "other"
    FILE_NAME_DATAFRAME_LOADED = options_naming.FILE_NAME_DATAFRAME_LOADED
    OPTIONS_MODULE = options_naming
    SOURCE_OPTIONS = options_naming.source_options
    ALLOW_QUICK_LOAD = False

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | None:
        """Find all CSV and parquet files in the folder."""
        extensions = options_naming.SUPPORTED_EXTENSIONS
        files = []
        for ext in extensions:
            files.extend(folder_path.glob(f"*{ext}"))

        if not files:
            logger.warning("No CSV or parquet files found in '%s'", folder_path)
            return None

        logger.info("Found %d file(s) in '%s'", len(files), folder_path)
        return sorted(files)

    @classmethod
    def _load(cls, file_path_list: list[Path], path_output: Path, **kwargs) -> pd.DataFrame:
        """Not used — main() processes each file independently."""
        msg = "OtherDataSource._load should not be called directly; use main() instead"
        raise NotImplementedError(msg)

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
        database_options[cst.DatabaseOptions.GROUPED_FIELDS] = grouped_fields

        return all_signals


def main(patient_options: dict, database_options_specific: dict | None) -> list[Signal]:
    """Load and process generic 'other' data."""
    return OtherDataSource.main(patient_options, database_options_specific)
