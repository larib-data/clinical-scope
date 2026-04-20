import csv
import logging
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
import clinical_data_visualizer.other.options as options_naming
from clinical_data_visualizer.datasource_base import DataSourceBase
from clinical_data_visualizer.inspection import DataSourceInspection
from clinical_data_visualizer.signal_container import (
    Signal,
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


def _resolve_columns(df: pd.DataFrame, file_config: dict) -> list[str]:
    """
    Determine which columns to expose as signals for a file.

    If ``field_display`` is present in the per-file config, restrict to those
    columns (bare names).  Otherwise all DataFrame columns are returned.
    """
    per_file_display = file_config.get(cst.DatabaseOptions.FIELD_DISPLAY)
    if per_file_display is not None:
        return [c for c in per_file_display if c in df.columns]
    return list(df.columns)


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

        Per-file configuration is read from ``database_options_specific["files"]``, which
        is populated by ``wrapper._collect_other_per_file()`` from ``other::<stem>`` keys.
        Each ``other::<stem>`` section supports the full set of database_options keys:
        ``signals``, ``field_display``, ``additional_informations`` (timezone), ``numerics``,
        ``grouped_fields``, and ``loop``.
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

        per_file_options: dict = database_options.get(cst.DatabaseOptions.FILES, {})

        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        group_by_file = patient_options_specific.get(
            options_naming.PatientOptionsDataSourceRelative.GroupByFile.NAME,
            options_naming.PatientOptionsDataSourceRelative.GroupByFile.DEFAULT,
        )

        all_signals: list[Signal] = []
        grouped_fields: dict = {}
        per_file_loops: dict = {}

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

                # Convert remaining columns to numeric, drop all-NaN columns
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(axis=1, how="all")

                if df.empty or len(df.columns) == 0:
                    logger.warning("No numeric columns in '%s', skipping file", file_path.name)
                    continue

                # Remove duplicate timestamps
                df = df[~df.index.duplicated(keep="first")]
                df = df.sort_index()

                file_stem = file_path.stem
                file_config = per_file_options.get(file_stem, {})

                # Apply formatting (timezone, time shift, datetime filter) with per-file opts
                df = cls._format(df, patient_options, file_config)

                if df.empty:
                    logger.warning("No data after filtering in '%s', skipping file", file_path.name)
                    continue

                # Determine which columns to expose as signals
                columns = _resolve_columns(df, file_config)
                if not columns:
                    logger.debug("No columns selected for '%s', skipping file", file_path.name)
                    continue

                file_signal_raw_names: list[str] = []
                for col_name in columns:
                    raw_name = f"{file_stem}::{col_name}"
                    try:
                        sig = Signal.time_series_from_dataframe(
                            df=df,
                            raw_signal_name=col_name,
                            source_options=cls.SOURCE_OPTIONS,
                            database_options_specific=file_config,
                        )
                        sig.raw_name = raw_name  # override for global uniqueness
                        sig.metadata.datasource_name = cls.DATASOURCE_NAME
                        all_signals.append(sig)
                        file_signal_raw_names.append(raw_name)
                    except Exception:
                        logger.exception(
                            "Could not process signal '%s' from '%s'", col_name, file_path.name
                        )

                if file_signal_raw_names:
                    # Grouping: prefer user-defined groups, fall back to group-by-file
                    file_grouped = file_config.get(cst.DatabaseOptions.GROUPED_FIELDS, {})
                    if file_grouped:
                        for group_name, bare_cols in file_grouped.items():
                            grouped_fields[group_name] = [
                                f"{file_stem}::{col}"
                                for col in bare_cols
                                if f"{file_stem}::{col}" in file_signal_raw_names
                            ]
                    elif group_by_file:
                        grouped_fields[file_stem] = file_signal_raw_names

                    # Loops: prefix bare column names with file_stem for global uniqueness
                    for loop_name, bare_cols in file_config.get(
                        cst.DatabaseOptions.LOOP, {}
                    ).items():
                        per_file_loops[loop_name] = [f"{file_stem}::{col}" for col in bare_cols]

            except Exception:
                logger.exception("Failed to process '%s', skipping", file_path.name)
                continue

        # Inject grouped_fields and loop into database_options for the wrapper to use
        if grouped_fields:
            database_options[cst.DatabaseOptions.GROUPED_FIELDS] = grouped_fields
        if per_file_loops:
            database_options[cst.DatabaseOptions.LOOP] = per_file_loops

        return all_signals

    @classmethod
    def inspect(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
    ) -> list[DataSourceInspection]:
        """
        Inspect each CSV/parquet file in the other datasource folder independently.

        Returns one DataSourceInspection per file, named ``other::<stem>``, mirroring
        the database_options key convention (``other::waves``, ``other::numerics``, …).
        This avoids cross-file aggregation issues (e.g. mixed tz-naive/tz-aware indices)
        and gives the caller per-file date ranges and column stats.

        Overrides DataSourceBase.inspect() because OtherDataSource._load() raises
        NotImplementedError (files are processed individually in main()).
        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )
        per_file_options: dict = database_options.get(cst.DatabaseOptions.FILES, {})

        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return [
                DataSourceInspection(datasource_name=cls.DATASOURCE_NAME, status="file_not_found")
            ]

        file_paths = cls._find(search_folder)
        if not file_paths:
            return [
                DataSourceInspection(datasource_name=cls.DATASOURCE_NAME, status="file_not_found")
            ]

        results: list[DataSourceInspection] = []

        for fp in file_paths:
            inspection_name = f"{cls.DATASOURCE_NAME}::{fp.stem}"
            file_config = per_file_options.get(fp.stem, {})

            try:
                df = _load_single_file(fp)
                df = _detect_and_set_datetime_index(df)
                if df is None:
                    logger.warning("inspect: no datetime index in '%s', skipping", fp.name)
                    results.append(
                        DataSourceInspection(
                            datasource_name=inspection_name,
                            status="load_error",
                            error_message="No datetime index detected",
                            file_path=str(fp),
                        )
                    )
                    continue

                # Coerce all columns to numeric; keep NaN-only columns so that
                # _make_inspection/_column_infos can report them with raw_point_count=0.
                for col in list(df.columns):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df[~df.index.duplicated(keep="first")].sort_index()

                results.append(
                    cls._make_inspection(df, patient_options, file_config, inspection_name, str(fp))
                )

            except Exception:
                logger.exception("inspect: failed to process '%s'", fp.name)
                results.append(
                    DataSourceInspection(
                        datasource_name=inspection_name,
                        status="load_error",
                        error_message=f"Unexpected error processing {fp.name}",
                        file_path=str(fp),
                    )
                )

        return results or [
            DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status="file_not_found",
                file_path=str(search_folder),
            )
        ]
