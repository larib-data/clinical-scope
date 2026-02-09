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
from clinical_data_visualizer.signal_container import Signal

logger = logging.getLogger(__name__)


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

    @classmethod
    @abstractmethod
    def _find(cls, folder_path: Path) -> list[Path] | Path | None:
        """
        Find the data file(s) in the given folder.

        Args:
            folder_path: Path to search for data files

        Returns:
            Path or list[Path] or None: Found file(s), or None if not found

        """

    @classmethod
    @abstractmethod
    def _load(cls, file_path, path_output: Path, **kwargs) -> pd.DataFrame:
        """
        Load and parse raw data file(s) into a DataFrame.

        Args:
            file_path: Path or list of paths to data files
            path_output: Path to save loaded DataFrame for quick loading

        Returns:
            pd.DataFrame: Loaded data with datetime index

        """

    @classmethod
    def _quick_load(cls, path_dataframe: Path) -> pd.DataFrame:
        """Load previously saved DataFrame from parquet file."""
        return pd.read_parquet(path_dataframe)

    @classmethod
    def _save_dataframe(cls, df: pd.DataFrame, path_output: Path) -> None:
        """Save DataFrame to parquet for quick loading."""
        try:
            Path(path_output).parent.mkdir(parents=False, exist_ok=True)
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
                list_signal_container.append(Signal.time_series_from_dataframe(**kwargs))
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

            # Check if folder name contains all required keywords (case-insensitive)
            folder_name_lower = subfolder.name.lower()
            if all(keyword.lower() in folder_name_lower for keyword in folder_keywords):
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

        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        dataframe_path = folder_path / cst.FOLDER_NAME_VISU / cls.FILE_NAME_DATAFRAME_LOADED

        # Try quick load if enabled
        quick_load_enabled = patient_options.get(
            cst.PatientOptions.QuickLoad.NAME, getattr(cst, "DEFAULT_QUICK_LOAD", False)
        )

        if cls.ALLOW_QUICK_LOAD and quick_load_enabled and dataframe_path.is_file():
            df = cls._quick_load(dataframe_path)
        else:
            # Find folder (if datasource uses subfolder)
            search_folder = cls._find_folder(folder_path)
            if search_folder is None:
                return []

            # Find file(s)
            file_path = cls._find(search_folder)
            if file_path is None:
                return []

            # Load data
            df = cls._load(file_path, dataframe_path, database_options_specific=database_options)

        # Format data
        df = cls._format(df, patient_options, database_options)

        # Extract signals
        return cls._extract_signals(
            df, patient_options=patient_options_specific, database_options_specific=database_options
        )

