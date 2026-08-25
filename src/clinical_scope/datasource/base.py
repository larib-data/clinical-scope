"""
Base class for datasource processing.

This module provides common functionality for all datasource modules,
reducing duplication across find_load_format.py files.
"""

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import clinical_scope.constants as cst
from clinical_scope.datasource.formatting.timezone import (
    _date_range,
    _resolve_effective_tz,
    _to_display_tz,
    apply_timezone_to_dataframe,
    filter_data_by_timestamps,
    resolve_display_timezone,
    shift_data_by_seconds,
)
from clinical_scope.datasource.inspection import (
    DataSourceInspection,
    _column_infos,
)
from clinical_scope.datasource.timing import time_it
from clinical_scope.io.file_utils import (
    find_files,
    folder_name_matches_keywords,
    make_column_selector,
    read_parquet_pruned,
    save_df,
)
from clinical_scope.io.paths import get_datasource_cache_path
from clinical_scope.signal_container import DisplayFallbacks, Signal

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
    DATASOURCE_NAME: str = None  # e.g., "servo_u"
    FILE_NAME_DATAFRAME_LOADED: str = None  # e.g., "servo_u_loaded.parquet"
    OPTIONS_MODULE = None
    ALLOW_QUICK_LOAD: bool = True
    # When True and ALLOW_QUICK_LOAD is False, a symlink to the source file is created in the
    # output folder instead of a parquet cache. Use for large files with trivial loading cost.
    CREATE_SOURCE_SYMLINK: bool = False
    # Whether a set datetime_start/datetime_end window may be pushed down as a parquet row
    # filter at read time. Opt out when the source can't express its own filtering as a
    # min/max range (e.g. EIT's time-of-day filter_date=False).
    ALLOW_DATETIME_PUSHDOWN: bool = True

    # Optional source_options for Signal creation
    SOURCE_OPTIONS: dict = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        options_module = cls.OPTIONS_MODULE
        if options_module is None:
            return
        if cls.DATASOURCE_NAME is None:
            cls.DATASOURCE_NAME = getattr(options_module, "DATASOURCE_NAME", None)
        if cls.FILE_NAME_DATAFRAME_LOADED is None:
            cls.FILE_NAME_DATAFRAME_LOADED = getattr(
                options_module, "FILE_NAME_DATAFRAME_LOADED", None
            )
        if cls.SOURCE_OPTIONS is None:
            cls.SOURCE_OPTIONS = getattr(options_module, "source_options", None)
        allow_quick_load = getattr(options_module, "ALLOW_QUICK_LOAD", None)
        if allow_quick_load is not None:
            cls.ALLOW_QUICK_LOAD = allow_quick_load
        create_source_symlink = getattr(options_module, "CREATE_SOURCE_SYMLINK", None)
        if create_source_symlink is not None:
            cls.CREATE_SOURCE_SYMLINK = create_source_symlink
        allow_pushdown = getattr(options_module, "ALLOW_DATETIME_PUSHDOWN", None)
        if allow_pushdown is not None:
            cls.ALLOW_DATETIME_PUSHDOWN = allow_pushdown

    @classmethod
    def _find(cls, folder_path: Path) -> list[Path] | Path | None:
        """
        Find the data file(s) in the given folder.

        Uses the OPTIONS_MODULE constants (FILE_KEYWORDS, FILE_EXTENSIONS, MULTI_FILE)
        for default file discovery. Override in subclasses that need custom logic.
        """
        options_module = cls.OPTIONS_MODULE
        return find_files(
            folder_path,
            extensions=getattr(options_module, "FILE_EXTENSIONS", []),
            datasource_name=cls.DATASOURCE_NAME,
            multi=getattr(options_module, "MULTI_FILE", False),
            keywords=getattr(options_module, "FILE_KEYWORDS", None),
        )

    @classmethod
    @abstractmethod
    def _load(cls, file_path: Path | list[Path]) -> pd.DataFrame:
        """
        Transcribe the raw data file(s) into a datetime-indexed DataFrame, and nothing more.

        The base class writes the returned frame to the parquet cache, so per ADR-0010 no
        option may be resolved here — a signature taking only the file path enforces it.
        Interpretation (timezone, time shift, windowing) belongs in ``_format``.

        Returns:
            Loaded data, indexed by datetime.

        """

    @staticmethod
    def _has_datetime_window(patient_options: dict) -> bool:
        """Whether a datetime window is set — the precondition for any row-pushdown."""
        return bool(
            patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
            or patient_options.get(cst.PatientOptions.DatetimeEnd.NAME)
        )

    @classmethod
    def _pushdown_bounds(
        cls,
        patient_options: dict,
        database_options_specific: dict,
        index_tz: str | None,
    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None] | None:
        """
        Compute conservative-loose datetime bounds for parquet row-pushdown.

        Returns ``None`` when no window is set (nothing to push down). Otherwise
        returns ``(start, end)`` — either side may be ``None`` for a one-sided window —
        expressed in *index_tz* if given, or tz-naive source-local time (via
        ``OPTIONS_MODULE.DATA_SOURCE_DEFAULT_TIMEZONE``, honoring a database_options
        override) when *index_tz* is ``None``.

        Bounds are intentionally loose (± buffer, time_shift inverted): ``_filter_by_datetime``
        remains the authoritative cut downstream, so under-pruning only costs a few
        extra rows while over-pruning (silent data loss) is impossible by construction.
        """
        datetime_start = patient_options.get(cst.PatientOptions.DatetimeStart.NAME)
        datetime_end = patient_options.get(cst.PatientOptions.DatetimeEnd.NAME)
        if not datetime_start and not datetime_end:
            return None

        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        time_shift = patient_options_specific.get(
            cls.OPTIONS_MODULE.PatientOptionsDataSourceRelative.TimeShift.NAME, 0.0
        )
        shift_td = pd.Timedelta(seconds=time_shift)
        buffer = pd.Timedelta(seconds=cst.DATETIME_PUSHDOWN_BUFFER_SECONDS)

        # An aware bound passes through untouched -- the UI qualifies its bounds at Submit, so
        # this constant is reached only by bounds that never met a user (scripts, hand-edited
        # files). Interpreting those in the user option would make extract_* output depend on
        # ~/.clinical_scope/user_options.json. See ADR-0011.
        def _to_aware(raw_value: str | None) -> pd.Timestamp | None:
            if not raw_value:
                return None
            timestamp = pd.Timestamp(raw_value)
            if timestamp.tzinfo is not None:
                return timestamp
            return timestamp.tz_localize(cst.NAIVE_BOUND_TZ)

        start_aware = _to_aware(datetime_start)
        end_aware = _to_aware(datetime_end)

        if index_tz is None:
            if not hasattr(cls.OPTIONS_MODULE, "DATA_SOURCE_DEFAULT_TIMEZONE"):
                return None
            index_tz = _resolve_effective_tz(
                database_options_specific,
                cls.OPTIONS_MODULE,
                cls.OPTIONS_MODULE.DATA_SOURCE_DEFAULT_TIMEZONE,
            )
            pre_start = (
                None
                if start_aware is None
                else (start_aware - shift_td).tz_convert(index_tz).tz_localize(None) - buffer
            )
            pre_end = (
                None
                if end_aware is None
                else (end_aware - shift_td).tz_convert(index_tz).tz_localize(None) + buffer
            )
        else:
            pre_start = (
                None
                if start_aware is None
                else (start_aware - shift_td).tz_convert(index_tz) - buffer
            )
            pre_end = (
                None if end_aware is None else (end_aware - shift_td).tz_convert(index_tz) + buffer
            )

        return pre_start, pre_end

    @classmethod
    def _make_bounds_computer(
        cls,
        patient_options: dict | None,
        database_options_specific: dict,
    ) -> Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None] | None:
        """
        Build the row-pushdown *compute_bounds* callable, or ``None`` when pushdown doesn't apply.

        Centralizes the pushdown gate shared by every parquet call site: returns ``None`` (no row
        filter) unless this source allows pushdown *and* a datetime window is set. Passing
        ``patient_options=None`` (``inspect()``) yields ``None`` — inspect never prunes rows.
        """
        if (
            patient_options is None
            or not cls.ALLOW_DATETIME_PUSHDOWN
            or not cls._has_datetime_window(patient_options)
        ):
            return None

        def compute_bounds(index_tz):  # noqa: ANN001, ANN202
            return cls._pushdown_bounds(patient_options, database_options_specific, index_tz)

        return compute_bounds

    @classmethod
    def _quick_load(
        cls,
        path_dataframe: Path,
        patient_options: dict | None = None,
        database_options_specific: dict | None = None,
    ) -> pd.DataFrame:
        """
        Load a previously saved DataFrame from parquet, pruning rows and columns.

        Column pruning always applies: each cached frame is one column per signal, so
        ``field_display`` selects exactly the columns read off disk. Row pushdown is
        orthogonal and additionally gated on ``ALLOW_DATETIME_PUSHDOWN`` plus a set window.

        ``patient_options=None`` (``inspect()``) skips row pushdown; inspect also strips
        ``field_display`` upstream, so every column is then read.
        """
        database_options_specific = database_options_specific or {}

        return read_parquet_pruned(
            path_dataframe,
            compute_bounds=cls._make_bounds_computer(patient_options, database_options_specific),
            select_columns=make_column_selector(database_options_specific),
            # A cache is a file we wrote, so its index is the time axis by construction whatever
            # its dtype (EIT's is float64 fractional days). No other caller may claim that.
            index_is_time_axis=True,
        )

    @classmethod
    def _load_raw_dataframe(
        cls,
        patient_options: dict,
        database_options: dict,
        apply_datetime_pushdown: bool = True,
        configured_field_display: list[str] | None = None,
    ) -> tuple[pd.DataFrame | None, str | None, bool]:
        """
        Find, locate, and load the raw DataFrame for this datasource.

        *apply_datetime_pushdown* set to ``False`` bypasses parquet row-pushdown
        (used by ``inspect()``, which needs the full raw file for date-range stats).

        *configured_field_display* applies to the quick-load branch only: it restores a
        narrowed ``field_display`` into *database_options* for the cache read that serves
        ``inspect(configured_columns_only=True)``.

        Returns:
            (df, file_path_str, columns_pruned) on success, (None, None, False) if the file
            was not found. ``columns_pruned`` says whether the read that ran was structurally
            restricted to ``field_display``, which only a cache read can be — a fresh
            ``_load()`` takes no configuration and always parses every column.
            Raises exceptions for actual load errors.

        """
        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])
        output_root = patient_options.get(cst.PatientOptions.OutputRoot.NAME) or None
        dataframe_path = get_datasource_cache_path(
            folder_path, cls.FILE_NAME_DATAFRAME_LOADED, output_root
        )
        quick_load_enabled = patient_options.get(cst.PatientOptions.QuickLoad.NAME, False)
        reuse_cache = cls.ALLOW_QUICK_LOAD and quick_load_enabled
        write_cache = cls.ALLOW_QUICK_LOAD

        if reuse_cache and dataframe_path.is_file():
            logger.info("[%s] Quick loading from cache.", cls.DATASOURCE_NAME)
            column_options = database_options
            if configured_field_display is not None:
                column_options = {
                    **database_options,
                    cst.DatabaseOptions.FIELD_DISPLAY: configured_field_display,
                }
            df = cls._quick_load(
                dataframe_path,
                patient_options=patient_options if apply_datetime_pushdown else None,
                database_options_specific=column_options,
            )
            columns_pruned = bool(column_options.get(cst.DatabaseOptions.FIELD_DISPLAY))
            return df, str(dataframe_path), columns_pruned

        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return None, None, False

        file_path = cls._find(search_folder)
        if file_path is None:
            return None, None, False

        file_path_str = str(file_path[0]) if isinstance(file_path, list) else str(file_path)
        logger.info("🔍 [%s] Loading fresh data from: %s", cls.DATASOURCE_NAME, search_folder)
        df = cls._load(file_path)
        logger.info(
            "📥 [%s] Loaded: %d rows x %d columns.",
            cls.DATASOURCE_NAME,
            df.shape[0],
            df.shape[1],
        )
        # An empty frame would cache a "no data" state every later quick_load run reads back.
        if write_cache and not df.empty:
            cls._save_dataframe(df, dataframe_path)
        if not write_cache and cls.CREATE_SOURCE_SYMLINK:
            cls._create_source_symlink(file_path, dataframe_path.parent)
        columns_pruned = False
        return df, file_path_str, columns_pruned

    @classmethod
    def _save_dataframe(cls, df: pd.DataFrame, path_output: Path) -> None:
        """Save DataFrame to parquet for quick loading."""
        try:
            Path(path_output).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path_output)
        except Exception:
            logger.exception("Could not save the dataframe for future quick-reloading:")

    @classmethod
    def _create_source_symlink(cls, file_path: Path | list[Path], output_folder: Path) -> None:
        """
        Create a symlink under ``<output_folder>/<datasource>/`` pointing to the source file(s).

        Used by datasources that opt out of parquet caching (ALLOW_QUICK_LOAD=False) so the
        output folder still contains a traceable reference to the exact file that was used.

        Symlinks live in a per-datasource subfolder because the output folder is flat and
        shared: an 'other' file named ``servo_u_loaded.parquet`` would otherwise land on
        servo_u's cache path and replace it.
        """
        files = file_path if isinstance(file_path, list) else [file_path]
        symlink_folder = output_folder / cls.DATASOURCE_NAME
        try:
            symlink_folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.exception(
                "[%s] Could not create output folder for symlink.", cls.DATASOURCE_NAME
            )
            return
        for source_file in files:
            symlink_path = symlink_folder / source_file.name
            if symlink_path.is_symlink():
                symlink_path.unlink()
            elif symlink_path.exists():
                # Never unlink a real file: the folder is ours, so this is something a user put
                # here deliberately, and a traceability link isn't worth destroying it.
                logger.warning(
                    "[%s] '%s' exists and is not a symlink; leaving it untouched.",
                    cls.DATASOURCE_NAME,
                    symlink_path,
                )
                continue
            try:
                rel_target = Path(os.path.relpath(source_file, symlink_folder))
                symlink_path.symlink_to(rel_target)
                logger.info(
                    "[%s] Symlinked source file: %s -> %s",
                    cls.DATASOURCE_NAME,
                    symlink_path,
                    source_file,
                )
            except Exception:
                logger.exception(
                    "[%s] Could not create symlink for '%s'.", cls.DATASOURCE_NAME, source_file
                )

    @classmethod
    def _apply_timezone(
        cls, df: pd.DataFrame, database_options_specific: dict, default_timezone: str
    ) -> pd.DataFrame:
        """Apply timezone to DataFrame index if not already set."""
        return apply_timezone_to_dataframe(
            df, database_options_specific, default_timezone, cls.OPTIONS_MODULE
        )

    @classmethod
    def _apply_time_shift(cls, df: pd.DataFrame, patient_options: dict) -> pd.DataFrame:
        """Apply time shift based on patient options."""
        patient_options_specific = patient_options.get(cls.DATASOURCE_NAME, {})
        time_shift_second = patient_options_specific.get(
            cls.OPTIONS_MODULE.PatientOptionsDataSourceRelative.TimeShift.NAME, 0.0
        )
        shift_data_by_seconds(df, time_shift_second)
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
        # See _pushdown_bounds: only a tz-naive bound is interpreted here.
        return filter_data_by_timestamps(
            df,
            time_start=datetime_start,
            time_end=datetime_end,
            filter_date=filter_date,
            naive_bound_tz=cst.NAIVE_BOUND_TZ,
        )

    @classmethod
    @time_it
    def _format(
        cls, df: pd.DataFrame, patient_options: dict, database_options_specific: dict
    ) -> pd.DataFrame:
        """
        Apply standard formatting transformations.

        Override this method for datasource-specific formatting needs.
        """
        # Shallow copy since below only rebinds df.index or row-filters, never mutates columns.
        df = df.copy(deep=False)

        if hasattr(cls.OPTIONS_MODULE, "DATA_SOURCE_DEFAULT_TIMEZONE"):
            df = cls._apply_timezone(
                df, database_options_specific, cls.OPTIONS_MODULE.DATA_SOURCE_DEFAULT_TIMEZONE
            )

        df = cls._apply_time_shift(df, patient_options)

        return cls._filter_by_datetime(df, patient_options)

    @classmethod
    @time_it
    def _extract_signals(
        cls,
        df: pd.DataFrame,
        database_options_specific: dict,
        display_fallbacks: DisplayFallbacks | None = None,
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
                    "database_options_specific": database_options_specific,
                    "display_fallbacks": display_fallbacks,
                }
                if cls.SOURCE_OPTIONS is not None:
                    kwargs["source_options"] = cls.SOURCE_OPTIONS
                signal_obj = Signal.time_series_from_dataframe(**kwargs)
                signal_obj.metadata.datasource_name = cls.DATASOURCE_NAME
                list_signal_container.append(signal_obj)
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

        if not folder_path.is_dir():
            logger.warning("Patient folder '%s' does not exist", folder_path)
            return None

        for subfolder in folder_path.iterdir():
            if not subfolder.is_dir():
                continue

            if folder_name_matches_keywords(subfolder.name, folder_keywords):
                if subfolder.name != expected_folder_name:
                    logger.info(
                        "Found %s folder '%s' matching keywords %s (recommended name: '%s')",
                        cls.DATASOURCE_NAME,
                        subfolder.name,
                        folder_keywords,
                        expected_folder_name,
                    )
                return subfolder

        logger.debug(
            "No folder found in '%s' containing all keywords %s for datasource '%s'",
            folder_path,
            folder_keywords,
            cls.DATASOURCE_NAME,
        )
        return None

    @classmethod
    @time_it
    def main(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
        display_fallbacks: DisplayFallbacks | None = None,
    ) -> list[Signal]:
        """Main entry point for datasource processing."""
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        df, _, _ = cls._load_raw_dataframe(patient_options, database_options)
        if df is None:
            return []

        df = cls._format(df, patient_options, database_options)

        signals = cls._extract_signals(
            df,
            database_options_specific=database_options,
            display_fallbacks=display_fallbacks,
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

        Parquet caching inside ``clinical_scope_output/`` is always created automatically by
        ``_load_raw_dataframe()``.

        Args:
            patient_options: Patient-specific options (same as :meth:`main`).
            save_path: If given, save the formatted DataFrame to this path using
                :func:`io.file_utils.save_df` (supports ``.csv`` and ``.parquet``).

        Returns:
            Formatted ``pd.DataFrame``, or ``None`` if the file was not found or
            an error occurred.

        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        try:
            df, _, _ = cls._load_raw_dataframe(patient_options, database_options)
        except Exception:
            logger.exception("[%s] extract: load failed.", cls.DATASOURCE_NAME)
            return None

        if df is None:
            logger.debug("[%s] No data file found.", cls.DATASOURCE_NAME)
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
            save_df(df, Path(save_path))

        return df

    @classmethod
    def _make_inspection(
        cls,
        df_raw: pd.DataFrame,
        patient_options: dict,
        database_options_specific: dict,
        datasource_name: str,
        file_path: str | None = None,
        display_timezone: str | None = None,
        columns_pruned: bool = False,
    ) -> DataSourceInspection:
        """
        Build a DataSourceInspection from an already-loaded raw DataFrame.

        Shared by :meth:`inspect` (called once after loading) and datasource overrides
        that load files individually (e.g. ``OtherDataSource``).

        Args:
            df_raw: Raw DataFrame with a DatetimeIndex (pre-format).
            patient_options: Patient-specific options forwarded to ``_format``.
            database_options_specific: Options for this datasource or per-file config.
            datasource_name: Name written into the returned DataSourceInspection.
            file_path: Path string to include in the result, or None.
            display_timezone: Timezone the reported date ranges are shown in — cosmetic
                only, never affects filtering. Resolved by the caller (``wrapper.inspect``);
                falls back to ``cst.DISPLAY_TIMEZONE`` when omitted.
            columns_pruned: Whether the caller's read was structurally restricted to configured
                columns — decided by the caller from which branch actually ran, not re-derived
                here from *df_raw*'s columns (a file that happens to hold only configured
                columns was not necessarily pruned to get there).

        Returns:
            DataSourceInspection with status ``OK`` or ``FORMAT_ERROR`` (cst.InspectionStatus).

        """
        signals = database_options_specific.get(cst.DatabaseOptions.SIGNALS, {})
        configured_fields = set(
            database_options_specific.get(cst.DatabaseOptions.FIELD_DISPLAY, list(signals.keys()))
        )
        display_timezone = resolve_display_timezone(display_timezone)

        df_raw_display = _to_display_tz(df_raw, display_timezone=display_timezone)
        raw_date_range = _date_range(df_raw_display)

        try:
            df_filtered = cls._format(df_raw, patient_options, database_options_specific)
        except Exception as exc:
            logger.exception("[%s] inspect: format failed.", datasource_name)
            return DataSourceInspection(
                datasource_name=datasource_name,
                status=cst.InspectionStatus.FORMAT_ERROR,
                error_message=str(exc),
                file_path=file_path,
                raw_date_range=raw_date_range,
                columns=_column_infos(df_raw_display, df_raw_display, configured_fields),
                columns_pruned=columns_pruned,
            )

        df_filtered_display = _to_display_tz(df_filtered, display_timezone=display_timezone)
        return DataSourceInspection(
            datasource_name=datasource_name,
            status=cst.InspectionStatus.OK,
            file_path=file_path,
            raw_date_range=raw_date_range,
            filtered_date_range=_date_range(df_filtered_display),
            columns=_column_infos(df_raw_display, df_filtered_display, configured_fields),
            columns_pruned=columns_pruned,
        )

    @classmethod
    def inspect(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
        display_timezone: str | None = None,
        configured_columns_only: bool = False,
    ) -> DataSourceInspection | list[DataSourceInspection]:
        """
        Run find → load → format for this datasource and return inspection metadata.

        Does NOT call _extract_signals(). Returns statistics on every raw column
        in the loaded DataFrame, including columns not listed in field_display.

        Args:
            patient_options: Patient-specific options (same as main())
            display_timezone: Forwarded to :meth:`_make_inspection` — see its docstring.
            configured_columns_only: Read only the ``field_display`` columns, trading the
                unconfigured-column rows for the memory. Only ever narrows a **parquet** read
                (a CSV or XML first load ignores it); for most sources that means the
                ``clinical_scope_output/`` cache from a previous run, so it speeds up
                re-inspection rather than first contact. Row/time pushdown stays disabled
                either way — inspect's ``% retained`` and ``raw_date_range`` are comparisons
                against the *unwindowed* file.

        Returns:
            DataSourceInspection with status, file info, date ranges, and column stats

        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        # Remove field_display so _load() returns ALL columns.
        database_options_for_load = {
            key: value
            for key, value in database_options.items()
            if key != cst.DatabaseOptions.FIELD_DISPLAY
        }

        file_path_str = None
        try:
            df_raw, file_path_str, columns_pruned = cls._load_raw_dataframe(
                patient_options,
                database_options_for_load,
                apply_datetime_pushdown=False,
                configured_field_display=(
                    database_options.get(cst.DatabaseOptions.FIELD_DISPLAY)
                    if configured_columns_only
                    else None
                ),
            )
        except Exception as exc:
            logger.exception("[%s] inspect: load failed.", cls.DATASOURCE_NAME)
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status=cst.InspectionStatus.LOAD_ERROR,
                error_message=str(exc),
                file_path=file_path_str,
            )

        if df_raw is None:
            return DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME, status=cst.InspectionStatus.FILE_NOT_FOUND
            )

        return cls._make_inspection(
            df_raw,
            patient_options,
            database_options,
            datasource_name=cls.DATASOURCE_NAME,
            file_path=file_path_str,
            display_timezone=display_timezone,
            columns_pruned=columns_pruned,
        )
