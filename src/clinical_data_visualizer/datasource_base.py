"""
Base class for datasource processing.

This module provides common functionality for all datasource modules,
reducing duplication across find_load_format.py files.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

import clinical_data_visualizer.constants as cst
from clinical_data_visualizer import helper
from clinical_data_visualizer.inspection import ColumnInfo, DataSourceInspection
from clinical_data_visualizer.signal_container import Signal

logger = logging.getLogger(__name__)


_TS_FMT = "%y-%m-%d %H:%M:%S"  # compact, no milliseconds, 2-digit year


def fmt_ts(ts: object) -> str:
    """Format a pandas Timestamp (or datetime-like) to a compact, human-readable string."""
    try:
        return ts.strftime(_TS_FMT)
    except Exception:  # noqa: BLE001
        return str(ts)


def _date_range(df: pd.DataFrame) -> tuple[str, str] | None:
    """Return (compact_min, compact_max) of the DataFrame index, or None if empty."""
    if df.empty:
        return None
    try:
        return (fmt_ts(df.index.min()), fmt_ts(df.index.max()))
    except Exception:  # noqa: BLE001
        return None


def _first_last_timestamp(df: pd.DataFrame, col: str) -> tuple[str | None, str | None]:
    """Return (first, last) compact timestamp strings for valid (non-NaN) values in a column."""
    if col not in df.columns:
        return None, None
    valid_index = df.index[df[col].notna()]
    if valid_index.empty:
        return None, None
    return fmt_ts(valid_index.min()), fmt_ts(valid_index.max())


def _column_infos(
    df_raw: pd.DataFrame,
    df_filtered: pd.DataFrame,
    configured_fields: set[str],
) -> list:
    """Build a list of ColumnInfo objects from raw and filtered DataFrames."""
    infos = []
    for col in df_raw.columns:
        first_ts, last_ts = _first_last_timestamp(df_filtered, col)
        infos.append(
            ColumnInfo(
                raw_name=col,
                is_configured=col in configured_fields,
                raw_point_count=int(df_raw[col].notna().sum()),
                filtered_point_count=(
                    int(df_filtered[col].notna().sum()) if col in df_filtered.columns else 0
                ),
                first_filtered_timestamp=first_ts,
                last_filtered_timestamp=last_ts,
            )
        )
    return infos


class DataSourceBase(ABC):
    """
    Abstract base class for datasource processing.

    Subclasses must implement:
        - _find(): Locate the data file(s)
        - _load(): Parse the raw data into a DataFrame

    Subclasses may override:
        - _format(): Apply formatting transformations
        - _extract_signals(): Convert DataFrame to Signal objects
        - main(): Main entry point (usually not needed)
    """

    # Subclass configuration - must be set by concrete implementations
    DATASOURCE_NAME: str = None  # e.g., "philips_waves"
    FILE_NAME_DATAFRAME_LOADED: str = None  # e.g., "philips_waves_loaded.parquet"
    OPTIONS_MODULE = None  # The options module for this datasource
    ALLOW_QUICK_LOAD: bool = True  # Whether to allow quick loading

    # Optional source_options for Signal creation
    SOURCE_OPTIONS: dict = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        opts = cls.OPTIONS_MODULE
        if opts is None:
            return
        if cls.DATASOURCE_NAME is None:
            cls.DATASOURCE_NAME = getattr(opts, "DATASOURCE_NAME", None)
        if cls.FILE_NAME_DATAFRAME_LOADED is None:
            cls.FILE_NAME_DATAFRAME_LOADED = getattr(opts, "FILE_NAME_DATAFRAME_LOADED", None)
        if cls.SOURCE_OPTIONS is None:
            cls.SOURCE_OPTIONS = getattr(opts, "source_options", None)
        allow = getattr(opts, "ALLOW_QUICK_LOAD", None)
        if allow is not None:
            cls.ALLOW_QUICK_LOAD = allow

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | Path | None:
        """
        Find the data file(s) in the given folder.

        Uses the OPTIONS_MODULE constants (FILE_KEYWORDS, FILE_EXTENSIONS, MULTI_FILE)
        for default file discovery. Override in subclasses that need custom logic.

        Args:
            folder_path: Path to search for data files

        Returns:
            Path or list[Path] or None: Found file(s), or None if not found

        """
        opts = cls.OPTIONS_MODULE
        return helper.find_files(
            folder_path,
            extensions=getattr(opts, "FILE_EXTENSIONS", []),
            datasource_name=cls.DATASOURCE_NAME,
            multi=getattr(opts, "MULTI_FILE", False),
            keywords=getattr(opts, "FILE_KEYWORDS", None),
        )

    @classmethod
    @abstractmethod
    def _load(
        cls, file_path: Path | list[Path], path_output: Path | None, **kwargs
    ) -> pd.DataFrame:
        """
        Load and parse raw data file(s) into a DataFrame.

        Args:
            file_path: Path or list of paths to data files
            path_output: Path to save loaded DataFrame for quick loading, or none if no saving
                         needed

        Returns:
            pd.DataFrame: Loaded data with datetime index

        """

    @classmethod
    def _quick_load(cls, path_dataframe: Path) -> pd.DataFrame:
        """Load previously saved DataFrame from parquet file."""
        return pd.read_parquet(path_dataframe)

    @classmethod
    def _load_raw_dataframe(
        cls,
        patient_options: dict,
        database_options: dict,
    ) -> tuple[pd.DataFrame | None, str | None]:
        """
        Find, locate, and load the raw DataFrame for this datasource.

        Returns:
            (df, file_path_str) on success, (None, None) if file not found.
            Raises exceptions for actual load errors.

        """
        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        dataframe_path = folder_path / cst.FOLDER_NAME_VISU / cls.FILE_NAME_DATAFRAME_LOADED
        quick_load_enabled = patient_options.get(cst.PatientOptions.QuickLoad.NAME, False)
        should_cache = cls.ALLOW_QUICK_LOAD and quick_load_enabled

        if should_cache and dataframe_path.is_file():
            logger.info("[%s] Quick loading from cache.", cls.DATASOURCE_NAME)
            return cls._quick_load(dataframe_path), str(dataframe_path)

        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return None, None

        file_path = cls._find(search_folder)
        if file_path is None:
            return None, None

        file_path_str = str(file_path[0]) if isinstance(file_path, list) else str(file_path)
        logger.info("🔍 [%s] Loading fresh data from: %s", cls.DATASOURCE_NAME, search_folder)
        df = cls._load(
            file_path,
            dataframe_path if should_cache else None,
            database_options_specific=database_options,
        )
        logger.info(
            "📥 [%s] Loaded: %d rows x %d columns.",
            cls.DATASOURCE_NAME,
            df.shape[0],
            df.shape[1],
        )
        return df, file_path_str

    @classmethod
    def _save_dataframe(cls, df: pd.DataFrame, path_output: Path) -> None:
        """Save DataFrame to parquet for quick loading."""
        try:
            Path(path_output).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path_output)
        except Exception:
            logger.exception("Could not save the dataframe for future quick-reloading:")

    @classmethod
    def _apply_timezone(
        cls, df: pd.DataFrame, database_options_specific: dict, default_timezone: str
    ) -> pd.DataFrame:
        """Apply timezone to DataFrame index if not already set."""
        return helper.apply_timezone_to_dataframe(
            df, database_options_specific, default_timezone, cls.OPTIONS_MODULE
        )

    @classmethod
    def _apply_time_shift(cls, df: pd.DataFrame, patient_options: dict) -> pd.DataFrame:
        """Apply time shift based on patient options."""
        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        time_shift_second = patient_options_specific.get(
            cls.OPTIONS_MODULE.PatientOptionsDataSourceRelative.TimeShift.NAME, 0.0
        )
        helper.shift_data_by_seconds(df, time_shift_second)
        return df

    @classmethod
    def _filter_by_datetime(
        cls, df: pd.DataFrame, patient_options: dict, filter_date: bool = True
    ) -> pd.DataFrame:
        """Filter DataFrame by datetime start and end from patient options."""
        datetime_start = patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
        datetime_end = patient_options.get(cst.PatientOptions.DatetimeEnd.NAME)
        datetime_start = pd.Timestamp(datetime_start) if datetime_start else None
        datetime_end = pd.Timestamp(datetime_end) if datetime_end else None
        return helper.filter_data_by_timestamps(
            df, time_start=datetime_start, time_end=datetime_end, filter_date=filter_date
        )

    @classmethod
    @helper.time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        """
        Apply standard formatting transformations.

        Override this method for datasource-specific formatting needs.
        """
        # Apply timezone if needed (most datasources need this)
        if hasattr(cls.OPTIONS_MODULE, "DATA_SOURCE_DEFAULT_TIMEZONE"):
            df = cls._apply_timezone(
                df, database_options_specific, cls.OPTIONS_MODULE.DATA_SOURCE_DEFAULT_TIMEZONE
            )

        # Apply time shift
        df = cls._apply_time_shift(df, patient_options)

        # Filter by datetime
        return cls._filter_by_datetime(df, patient_options)

    @classmethod
    @helper.time_it
    def _extract_signals(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> list[Signal]:
        """
        Extract Signal objects from DataFrame.

        Override this method for datasource-specific signal extraction needs.
        """
        list_signals = database_options_specific.get(
            cst.DatabaseOptions.FIELD_DISPLAY, list(df.columns)
        )

        list_signal_container = []
        for signal in list_signals:
            try:
                kwargs = {
                    "df": df,
                    "raw_signal_name": signal,
                    "patient_options": patient_options,
                    "database_options_specific": database_options_specific,
                }
                if cls.SOURCE_OPTIONS is not None:
                    kwargs["source_options"] = cls.SOURCE_OPTIONS
                sig = Signal.time_series_from_dataframe(**kwargs)
                sig.metadata.datasource_name = cls.DATASOURCE_NAME
                list_signal_container.append(sig)
            except Exception:
                logger.exception("Could not process the signal '%s' as Signal object", signal)

        return list_signal_container

    @classmethod
    def _find_folder(cls, folder_path: Path) -> Path | None:
        """
        Find the datasource folder using flexible keyword matching.

        The method searches for folders containing all required keywords from FOLDER_KEYWORDS.
        Matching is case-insensitive and works with any separator (_, -, space, etc.).

        Priority:
        1. Exact match with EXPECTED_FOLDER_NAME
        2. Folder containing all FOLDER_KEYWORDS (case-insensitive, any order/separator)
        3. Returns None if no match found

        Returns:
            Path to folder, or None if not found

        """
        # Get folder keywords
        folder_keywords = getattr(cls.OPTIONS_MODULE, "FOLDER_KEYWORDS", None)

        if folder_keywords is None or len(folder_keywords) == 0:
            # No subfolder expected, use root patient folder
            return folder_path

        # Try exact match first (for performance)
        expected_folder_name = getattr(cls.OPTIONS_MODULE, "EXPECTED_FOLDER_NAME", None)
        if expected_folder_name:
            expected_path = folder_path / expected_folder_name
            if expected_path.is_dir():
                return expected_path

        # Flexible keyword matching: find folder containing all keywords
        if not folder_path.is_dir():
            logger.warning("Patient folder '%s' does not exist", folder_path)
            return None

        for subfolder in folder_path.iterdir():
            if not subfolder.is_dir():
                continue

            if helper.folder_name_matches_keywords(subfolder.name, folder_keywords):
                if subfolder.name != expected_folder_name:
                    logger.info(
                        "Found %s folder '%s' matching keywords %s (recommended name: '%s')",
                        cls.DATASOURCE_NAME,
                        subfolder.name,
                        folder_keywords,
                        expected_folder_name,
                    )
                return subfolder

        logger.warning(
            "No folder found in '%s' containing all keywords %s for datasource '%s'",
            folder_path,
            folder_keywords,
            cls.DATASOURCE_NAME,
        )
        return None

    @classmethod
    @helper.time_it
    def main(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
    ) -> list[Signal]:
        """
        Main entry point for datasource processing.

        Args:
            patient_options: Patient-specific options
            database_options_specific: Database options for this datasource

        Returns:
            list[Signal]: Extracted signals

        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )
        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})

        df, _ = cls._load_raw_dataframe(patient_options, database_options)
        if df is None:
            return []

        # Format data
        df = cls._format(df, patient_options, database_options)

        # Extract signals
        signals = cls._extract_signals(
            df, patient_options=patient_options_specific, database_options_specific=database_options
        )
        logger.info("🔬 [%s] Extracted %d signal(s).", cls.DATASOURCE_NAME, len(signals))
        return signals

    @classmethod
    def extract(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
        save_path: str | Path | None = None,
    ) -> pd.DataFrame | None:
        """
        Run find → load → format and return the formatted DataFrame.

        Analogous to :meth:`inspect` (same pipeline level — stops after ``_format``,
        never calls ``_extract_signals``), but returns the data itself rather than
        inspection metadata.

        Parquet caching inside ``tdv_visu/`` is always created automatically by
        ``_load()`` inside ``_load_raw_dataframe()``.

        Args:
            patient_options: Patient-specific options (same as :meth:`main`).
            database_options_specific: Database options for this datasource.
            save_path: If given, save the formatted DataFrame to this path using
                :func:`helper.save_df` (supports ``.csv`` and ``.parquet``).

        Returns:
            Formatted ``pd.DataFrame``, or ``None`` if the file was not found or
            an error occurred.

        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        try:
            df, _ = cls._load_raw_dataframe(patient_options, database_options)
        except Exception:
            logger.exception("[%s] extract: load failed.", cls.DATASOURCE_NAME)
            return None

        if df is None:
            logger.info("[%s] No data file found.", cls.DATASOURCE_NAME)
            return None

        df_raw = df
        try:
            df = cls._format(df, patient_options, database_options)
        except Exception:
            logger.exception(
                "[%s] extract: format failed. Falling back to unformatted data.",
                cls.DATASOURCE_NAME,
            )
            df = df_raw

        logger.info(
            "[%s] Extracted: %d rows x %d columns.", cls.DATASOURCE_NAME, df.shape[0], df.shape[1]
        )

        if save_path is not None:
            helper.save_df(df, Path(save_path))

        return df

    @classmethod
    def inspect(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
    ) -> DataSourceInspection:
        """
        Run find → load → format for this datasource and return inspection metadata.

        Does NOT call _extract_signals(). Returns statistics on every raw column
        in the loaded DataFrame, including columns not listed in field_display.

        Args:
            patient_options: Patient-specific options (same as main())
            database_options_specific: Database options for this datasource

        Returns:
            DataSourceInspection with status, file info, date ranges, and column stats

        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        # Remove field_display so _load() returns ALL columns (handles EIT pre-filtering)
        db_opts_for_load = {
            k: v for k, v in database_options.items() if k != cst.DatabaseOptions.FIELD_DISPLAY
        }
        configured_fields = set(database_options.get(cst.DatabaseOptions.FIELD_DISPLAY, []))

        file_path_str = None
        try:
            df_raw, file_path_str = cls._load_raw_dataframe(patient_options, db_opts_for_load)
        except Exception as exc:
            logger.exception("[%s] inspect: load failed.", cls.DATASOURCE_NAME)
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status="load_error",
                error_message=str(exc),
                file_path=file_path_str,
            )

        if df_raw is None:
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME, status="file_not_found"
            )

        raw_date_range = _date_range(df_raw)

        try:
            df_filtered = cls._format(df_raw, patient_options, database_options)
        except Exception as exc:
            logger.exception("[%s] inspect: format failed.", cls.DATASOURCE_NAME)
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status="format_error",
                error_message=str(exc),
                file_path=file_path_str,
                raw_date_range=raw_date_range,
                columns=_column_infos(df_raw, df_raw, configured_fields),
            )

        return DataSourceInspection(
            datasource_name=cls.DATASOURCE_NAME,
            status="ok",
            file_path=file_path_str,
            raw_date_range=raw_date_range,
            filtered_date_range=_date_range(df_filtered),
            columns=_column_infos(df_raw, df_filtered, configured_fields),
        )
