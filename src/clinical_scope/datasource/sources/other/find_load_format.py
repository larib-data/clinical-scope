import csv
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import clinical_scope.constants as cst
import clinical_scope.datasource.sources.other.options as options_naming
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.inspection import DataSourceInspection
from clinical_scope.io.column_patterns import make_column_selector
from clinical_scope.io.parquet_pruning import read_parquet_pruned
from clinical_scope.io.paths import get_output_folder
from clinical_scope.io.time_axis import deduplicate_then_sort_index, set_datetime_index
from clinical_scope.signal_container import (
    DisplayFallbacks,
    Signal,
)

logger = logging.getLogger(__name__)


def _load_single_file(
    file_path: Path,
    compute_bounds: Callable[[str | None], tuple[pd.Timestamp | None, pd.Timestamp | None] | None]
    | None = None,
    select_columns: Callable[[list[str]], list[str] | None] | None = None,
) -> pd.DataFrame:
    """
    Load a single CSV or parquet file into a DataFrame.

    *compute_bounds* pushes a datetime window down as a parquet row filter;
    *select_columns* prunes unconfigured columns at read time.
    Both are ignored for CSV (no partial scan possible).
    """
    suffix = file_path.suffix.lower()

    if suffix == ".parquet":
        if compute_bounds is not None or select_columns is not None:
            return read_parquet_pruned(
                file_path, compute_bounds=compute_bounds, select_columns=select_columns
            )
        return pd.read_parquet(file_path)

    if suffix == ".csv":
        with Path.open(file_path, "r", newline="") as file:
            sample = file.read(4096)
            try:
                dialect = csv.Sniffer().sniff(sample)
                sep = dialect.delimiter
            except csv.Error:
                sep = ","

        return pd.read_csv(file_path, sep=sep)

    msg = f"Unsupported file extension: {suffix}"
    raise ValueError(msg)


def _patient_options_for_file(patient_options: dict, file_stem: str) -> dict:
    """
    Return a patient_options view whose ``other`` slot holds *file_stem*'s own options.

    Per-file settings live under a standalone ``other::<stem>`` key — a peer of a datasource,
    not a nested option. Rebinding the slot keeps the inherited ``_format`` /
    ``_pushdown_bounds`` machinery resolving by ``DATASOURCE_NAME`` without a new argument.
    Fields absent from the per-file block fall back to the generic ``other`` one.

    Read-only: the result aliases *patient_options* when the file has no block of its own.
    """
    per_file = patient_options.get(cst.OTHER_FILE_PREFIX + file_stem)
    if not per_file:
        return patient_options
    generic = patient_options.get(options_naming.DATASOURCE_NAME, {})
    return {**patient_options, options_naming.DATASOURCE_NAME: {**generic, **per_file}}


def _qualify(file_stem: str, bare_name: str) -> str:
    """Scope a bare per-file name to its file: ``waves`` + ``Pao`` -> ``waves::Pao``."""
    return f"{file_stem}{cst.QUALIFIED_NAME_SEPARATOR}{bare_name}"


def _qualify_loop(file_stem: str, bare_columns: list) -> list:
    return [_qualify(file_stem, bare_column) for bare_column in bare_columns]


def _qualify_spectrogram(file_stem: str, entry: dict) -> dict:
    signal_key = cst.DatabaseOptions.SpectrogramConfig.SIGNAL
    if signal_key not in entry:
        return dict(entry)
    return {**entry, signal_key: _qualify(file_stem, entry[signal_key])}


def _qualify_psd(file_stem: str, entry: dict) -> dict:
    config_cls = cst.DatabaseOptions.PsdConfig
    signal_key = config_cls.Entry.SIGNAL
    qualified = []
    for item in entry.get(config_cls.SIGNALS) or []:
        # A plain string is shorthand for an Entry naming just a signal, as in wrapper.py.
        if isinstance(item, dict):
            if signal_key in item:
                qualified.append({**item, signal_key: _qualify(file_stem, item[signal_key])})
            else:
                qualified.append(dict(item))
        else:
            qualified.append(_qualify(file_stem, item))
    return {**entry, config_cls.SIGNALS: qualified}


# Derived-plot sections a per-file 'other::<stem>' block may declare, and how each one's bare
# signal references get scoped to that file. Adding a fifth derived plot type means adding a
# row here -- forgetting to is what made 'psd' validate cleanly yet never render.
PER_FILE_DERIVED_SECTIONS = {
    cst.DatabaseOptions.LOOP: _qualify_loop,
    cst.DatabaseOptions.SPECTROGRAM: _qualify_spectrogram,
    cst.DatabaseOptions.PSD: _qualify_psd,
}


def _resolve_columns(df: pd.DataFrame, file_config: dict) -> list[str]:
    """
    Determine which columns to expose as signals for a file.

    If ``field_display`` is present in the per-file config, restrict to those
    columns (bare names).  Otherwise all DataFrame columns are returned.
    """
    per_file_display = file_config.get(cst.DatabaseOptions.FIELD_DISPLAY)
    if per_file_display is not None:
        return [column_name for column_name in per_file_display if column_name in df.columns]
    return list(df.columns)


class OtherDataSource(DataSourceBase):
    """Generic datasource processor for CSV and parquet files."""

    OPTIONS_MODULE = options_naming

    @classmethod
    def _load(cls, file_path: Path | list[Path]) -> pd.DataFrame:
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
        Not supported for the 'other' datasource -- by design.

        extract()'s job elsewhere is reformatting a device's raw export (pivoting,
        parsing a proprietary layout, …) into the library DataFrame format. 'other' exists
        for files that are *already* tidy CSV/parquet -- there is nothing to reformat.
        Use main() for visualization or inspect() for per-file metadata instead.
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
        display_fallbacks: DisplayFallbacks | None = None,
    ) -> list[Signal]:
        """
        Process each file independently, creating one subplot group per file.

        Each file becomes a separate PlotGroup (subplot) with all its numeric
        columns as traces. Files that fail to load are skipped without affecting others.
        Populates database_options_specific['grouped_fields'] so the wrapper groups
        signals by source file.

        Per-file configuration is read from ``database_options_specific["files"]``, which
        ``database_options_parser.normalize_database_options`` populates from ``other::<stem>``
        keys. Each ``other::<stem>`` section supports the full set of database_options keys:
        ``signals``, ``field_display``, ``additional_informations`` (timezone), ``numerics``,
        ``grouped_fields``, ``trace_options``, and every derived-plot section listed in
        :data:`PER_FILE_DERIVED_SECTIONS` (``loop``, ``spectrogram``, ``psd``).

        Per-file *patient* options (``time_shift``, ``group_by_file``) are read the same way,
        from a standalone ``patient_options["other::<stem>"]`` block — see
        :func:`_patient_options_for_file`.
        """
        database_options = (
            database_options_specific if database_options_specific is not None else {}
        )

        folder_path = Path(patient_options[cst.PatientOptions.PathDataFolder.NAME])

        search_folder = cls._find_folder(folder_path)
        if search_folder is None:
            return []

        file_paths = cls._find(search_folder)
        if file_paths is None:
            return []

        per_file_options: dict = database_options.get(cst.DatabaseOptions.FILES, {})

        all_signals: list[Signal] = []
        loaded_files: list[Path] = []
        grouped_fields: dict = {}
        derived_sections: dict[str, dict] = {key: {} for key in PER_FILE_DERIVED_SECTIONS}

        for file_path in file_paths:
            try:
                file_stem = file_path.stem
                file_config = per_file_options.get(file_stem, {})
                file_patient_options = _patient_options_for_file(patient_options, file_stem)
                group_by_file = file_patient_options.get(cls.DATASOURCE_NAME, {}).get(
                    options_naming.PatientOptionsDataSourceRelative.GroupByFile.NAME,
                    options_naming.PatientOptionsDataSourceRelative.GroupByFile.DEFAULT,
                )

                df = _load_single_file(
                    file_path,
                    compute_bounds=cls._make_bounds_computer(file_patient_options, file_config),
                    select_columns=make_column_selector(file_config),
                )

                try:
                    df = set_datetime_index(df)
                except ValueError as exc:
                    logger.warning("Skipping file '%s': %s", file_path.name, exc)
                    continue

                loaded_files.append(file_path)

                for column in df.columns:
                    df[column] = pd.to_numeric(df[column], errors="coerce")

                df = deduplicate_then_sort_index(df)

                # Apply formatting (timezone, time shift, datetime filter) with per-file opts
                df = cls._format(df, file_patient_options, file_config)

                if df.empty:
                    logger.warning("No data after filtering in '%s', skipping file", file_path.name)
                    continue

                # Drop all-NaN columns *after* the datetime filter so a column's presence is
                # judged on the final window, not on whether row-pushdown narrowed the read.
                df = df.dropna(axis=1, how="all")
                if df.empty or len(df.columns) == 0:
                    logger.warning("No numeric columns in '%s', skipping file", file_path.name)
                    continue

                columns = _resolve_columns(df, file_config)
                if not columns:
                    logger.debug("No columns selected for '%s', skipping file", file_path.name)
                    continue

                file_signal_raw_names: list[str] = []
                for column_name in columns:
                    raw_name = _qualify(file_stem, column_name)
                    try:
                        signal_obj = Signal.time_series_from_dataframe(
                            df=df,
                            raw_signal_name=column_name,
                            source_options=cls.SOURCE_OPTIONS,
                            database_options_specific=file_config,
                            display_fallbacks=display_fallbacks,
                        )
                        signal_obj.raw_name = raw_name  # override for global uniqueness
                        signal_obj.metadata.datasource_name = cls.DATASOURCE_NAME
                        all_signals.append(signal_obj)
                        file_signal_raw_names.append(raw_name)
                    except Exception:
                        logger.exception(
                            "Could not process signal '%s' from '%s'",
                            column_name,
                            file_path.name,
                        )

                if file_signal_raw_names:
                    # Grouping: prefer user-defined groups, fall back to group-by-file
                    file_grouped = file_config.get(cst.DatabaseOptions.GROUPED_FIELDS, {})
                    if file_grouped:
                        for group_name, bare_columns in file_grouped.items():
                            qualified = [
                                _qualify(file_stem, bare_column) for bare_column in bare_columns
                            ]
                            grouped_fields[_qualify(file_stem, group_name)] = [
                                raw for raw in qualified if raw in file_signal_raw_names
                            ]
                    elif group_by_file:
                        grouped_fields[file_stem] = file_signal_raw_names

                    # Both the entry name and the signal references it holds are scoped to the
                    # file: two files may each declare a loop called "PV" without one erasing
                    # the other, and each keeps pointing at its own columns.
                    for section_key, qualify_entry in PER_FILE_DERIVED_SECTIONS.items():
                        for entry_name, entry in file_config.get(section_key, {}).items():
                            derived_sections[section_key][_qualify(file_stem, entry_name)] = (
                                qualify_entry(file_stem, entry)
                            )

            except Exception:
                logger.exception("Failed to process '%s', skipping", file_path.name)
                continue

        # 'other' never writes a parquet cache, so the symlink is the only trace the output
        # folder keeps of which files a run actually read.
        if loaded_files and cls.CREATE_SOURCE_SYMLINK:
            output_root = patient_options.get(cst.PatientOptions.OutputRoot.NAME) or None
            cls._create_source_symlink(loaded_files, get_output_folder(folder_path, output_root))

        # Inject the collected sections into database_options for the wrapper to use
        if grouped_fields:
            database_options[cst.DatabaseOptions.GROUPED_FIELDS] = grouped_fields
        for section_key, entries in derived_sections.items():
            if entries:
                database_options[section_key] = entries

        return all_signals

    @classmethod
    def inspect(
        cls,
        patient_options: dict,
        database_options_specific: dict | None,
        display_timezone: str | None = None,
        configured_columns_only: bool = False,
    ) -> list[DataSourceInspection]:
        """
        Inspect each CSV/parquet file in the other datasource folder independently.

        Returns one DataSourceInspection per file, named ``other::<stem>``, mirroring
        the database_options key convention (``other::waves``, ``other::numerics``, …).
        This avoids cross-file aggregation issues (e.g. mixed tz-naive/tz-aware indices)
        and gives the caller per-file date ranges and column stats.

        *configured_columns_only* prunes each file to its per-file ``field_display``; 'other'
        reads its source files directly, so pruning lands on the parquet ones without a cache
        having to exist. See :meth:`DataSourceBase.inspect` for the full contract.

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
                DataSourceInspection(
                    datasource_name=cls.DATASOURCE_NAME,
                    status=cst.InspectionStatus.FILE_NOT_FOUND,
                )
            ]

        file_paths = cls._find(search_folder)
        if not file_paths:
            return [
                DataSourceInspection(
                    datasource_name=cls.DATASOURCE_NAME,
                    status=cst.InspectionStatus.FILE_NOT_FOUND,
                )
            ]

        results: list[DataSourceInspection] = []

        for file_path in file_paths:
            inspection_name = f"{cls.DATASOURCE_NAME}{cst.QUALIFIED_NAME_SEPARATOR}{file_path.stem}"
            file_config = per_file_options.get(file_path.stem, {})
            file_patient_options = _patient_options_for_file(patient_options, file_path.stem)
            # _load_single_file only honors select_columns on the parquet branch (no partial
            # scan for CSV) — mirror that here so the pruned-view marker below is structural,
            # not inferred from whether the loaded frame happens to match the configured set.
            columns_pruned = (
                configured_columns_only
                and file_path.suffix.lower() == ".parquet"
                and bool(file_config.get(cst.DatabaseOptions.FIELD_DISPLAY))
            )

            try:
                df = _load_single_file(
                    file_path,
                    select_columns=(
                        make_column_selector(file_config) if configured_columns_only else None
                    ),
                )
                try:
                    df = set_datetime_index(df)
                except ValueError as exc:
                    logger.warning("inspect: no datetime index in '%s', skipping", file_path.name)
                    results.append(
                        DataSourceInspection(
                            datasource_name=inspection_name,
                            status=cst.InspectionStatus.LOAD_ERROR,
                            error_message=str(exc),
                            file_path=str(file_path),
                        )
                    )
                    continue

                # Coerce all columns to numeric; keep NaN-only columns so that
                # _make_inspection/_column_infos can report them with raw_point_count=0.
                for column in list(df.columns):
                    df[column] = pd.to_numeric(df[column], errors="coerce")
                df = deduplicate_then_sort_index(df)

                results.append(
                    cls._make_inspection(
                        df,
                        file_patient_options,
                        file_config,
                        inspection_name,
                        str(file_path),
                        display_timezone=display_timezone,
                        columns_pruned=columns_pruned,
                    )
                )

            except Exception:
                logger.exception("inspect: failed to process '%s'", file_path.name)
                results.append(
                    DataSourceInspection(
                        datasource_name=inspection_name,
                        status=cst.InspectionStatus.LOAD_ERROR,
                        error_message=f"Unexpected error processing {file_path.name}",
                        file_path=str(file_path),
                    )
                )

        return results or [
            DataSourceInspection(
                datasource_name=cls.DATASOURCE_NAME,
                status=cst.InspectionStatus.FILE_NOT_FOUND,
                file_path=str(search_folder),
            )
        ]
