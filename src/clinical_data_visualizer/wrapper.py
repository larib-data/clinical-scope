import logging
from pathlib import Path

import pandas as pd

from clinical_data_visualizer import constants as cst
from clinical_data_visualizer import datasource_list
from clinical_data_visualizer.database_options_parser import (
    normalize_database_options,
    warn_redundant_entries,
)
from clinical_data_visualizer.inspection import DataSourceInspection
from clinical_data_visualizer.signal_container import (
    PlotGroup,
    PlotModel,
    Signal,
)

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def _resolve_database_options(database_options_global: dict | None) -> dict:
    if database_options_global is None:
        return datasource_list.generate_default_database_options()
    normalize_database_options(database_options_global)
    return database_options_global


# ==================================================================================================
def _resolve_signal_references(field_list: list[str], all_signals: list[Signal]) -> list[Signal]:
    """
    Resolve signal references using a three-mode fallback chain.

    1. Qualified name ``"datasource::raw_name"`` -- explicit, unambiguous.
    2. Display name -- matches ``sig.name``. Warns if ambiguous.
    3. Raw name -- current behaviour, backward compatible.
    """
    matched: list[Signal] = []

    for ref in field_list:
        # Mode 1: qualified "datasource::raw_name"
        if "::" in ref:
            sig = next(
                (s for s in all_signals if f"{s.metadata.datasource_name}::{s.raw_name}" == ref),
                None,
            )
            if sig:
                matched.append(sig)
            else:
                logger.warning("Qualified reference '%s' did not match any signal.", ref)
            continue

        # Mode 2: display name
        by_name = [s for s in all_signals if s.name == ref]
        if len(by_name) == 1:
            matched.append(by_name[0])
        elif len(by_name) > 1:
            logger.warning(
                "Ambiguous display name '%s' matched %d signals -- "
                "use 'datasource::raw_name' to disambiguate.",
                ref,
                len(by_name),
            )
        else:
            # Mode 3: raw name fallback (no display name matched)
            by_raw = [s for s in all_signals if s.raw_name == ref]
            matched.extend(by_raw)

    return matched


def main(
    patient_options: dict,
    database_options_global: dict | None = None,
) -> list[PlotModel]:
    database_options_global = _resolve_database_options(database_options_global)
    all_signal_list = []
    already_used_in_group = []
    plot_group_list = []

    requested_sources = [
        ds.NAME for ds in datasource_list.DataSource.AVAILABLE if ds.NAME in database_options_global
    ]
    logger.info(
        "🚀 Starting visualization for %d datasource(s): %s",
        len(requested_sources),
        requested_sources,
    )

    # Loop through data sources
    for data_source in datasource_list.DataSource.AVAILABLE:
        name = data_source.NAME

        if name not in database_options_global:
            continue

        database_options = database_options_global[name]
        warn_redundant_entries(database_options, name)

        try:
            # (1) Create signals
            try:
                list_signal = data_source.MAIN_MODULE(patient_options, database_options)
                all_signal_list.extend(list_signal)
                logger.info("✅ [%s] %d signal(s) loaded.", name, len(list_signal))
            except Exception:
                logger.exception("❌ Failed to create signals for datasource '%s'. Skipping.", name)
                continue

            # Read grouped/loop fields after MAIN_MODULE (datasource may populate dynamically)
            local_group = database_options.get(cst.DatabaseOptions.GROUPED_FIELDS, {})
            for grouped_field_list in local_group.values():
                already_used_in_group.extend(grouped_field_list)

            local_loop_group = database_options.get(cst.DatabaseOptions.LOOP, {})

            # (2) Add default groups (one signal = one group)
            for signal in list_signal:
                if signal.raw_name not in already_used_in_group:
                    try:
                        pg = PlotGroup.from_single_signal(signal)
                        plot_group_list.append(pg)
                    except Exception:
                        logger.exception(
                            "⚠️ Failed to create PlotGroup from single signal '%s' in datasource "
                            "'%s'.",
                            signal.raw_name,
                            name,
                        )

            # (3) Add explicit user-defined groups
            for group_name, grouped_field_list in local_group.items():
                try:
                    signals = [sig for sig in list_signal if sig.raw_name in grouped_field_list]
                    if signals:
                        pg = PlotGroup(name=group_name, signals=signals)
                        plot_group_list.append(pg)
                except Exception:
                    logger.exception(
                        "⚠️ Failed to create grouped PlotGroup '%s' in datasource '%s'.",
                        group_name,
                        name,
                    )

            # (4) Add loop signals
            for loop_name, loop_field_list in local_loop_group.items():
                try:
                    signal_x = next(
                        (sig for sig in list_signal if sig.raw_name == loop_field_list[0]), None
                    )
                    signal_y = next(
                        (sig for sig in list_signal if sig.raw_name == loop_field_list[1]), None
                    )

                    if signal_x is None or signal_y is None:
                        missing = loop_field_list[0] if signal_x is None else loop_field_list[1]
                        logger.warning(
                            "⚠️ Could not construct loop '%s' in datasource '%s'. Missing signal "
                            "'%s'.",
                            loop_name,
                            name,
                            missing,
                        )
                        continue

                    try:
                        loop_signal = Signal.loop_from_signals(signal_x, signal_y, name=loop_name)
                    except Exception:
                        logger.exception(
                            "⚠️ Error constructing loop '%s' in datasource '%s'.",
                            loop_name,
                            name,
                        )
                        continue

                    try:
                        plot_group_list.append(PlotGroup.from_single_signal(loop_signal))
                    except Exception:
                        logger.exception(
                            "⚠️ Failed to create PlotGroup from loop signal '%s' in datasource "
                            "'%s'.",
                            loop_name,
                            name,
                        )

                except Exception:
                    logger.exception(
                        "❌ Unexpected error while processing loop '%s' in datasource '%s'.",
                        loop_name,
                        name,
                    )

        except Exception:
            logger.exception("❌ Error while treating datasource '%s'.", name)

    # Global grouping (must be done at the end)
    grouped_fields_global = database_options_global.get(cst.DatabaseOptions.GLOBAL, {}).get(
        cst.DatabaseOptions.GROUPED_FIELDS, {}
    )

    global_grouped_raw_names: set[str] = set()
    for group_name, grouped_field_list in grouped_fields_global.items():
        try:
            signals = _resolve_signal_references(grouped_field_list, all_signal_list)
            if signals:
                plot_group_list.append(PlotGroup(name=group_name, signals=signals))
                global_grouped_raw_names.update(s.raw_name for s in signals)
        except Exception:
            logger.exception("⚠️ Failed to create global PlotGroup '%s'.", group_name)

    # Remove individual PlotGroups for signals that are now in a global group
    if global_grouped_raw_names:
        plot_group_list = [
            pg
            for pg in plot_group_list
            if len(pg.signals) > 1 or pg.signals[0].raw_name not in global_grouped_raw_names
        ]

    # Global loops (cross-datasource)
    global_loop_group = database_options_global.get(cst.DatabaseOptions.GLOBAL, {}).get(
        cst.DatabaseOptions.LOOP, {}
    )
    for loop_name, loop_field_list in global_loop_group.items():
        try:
            if len(loop_field_list) != 2:  # noqa: PLR2004
                logger.warning(
                    "⚠️ Global loop '%s' needs exactly 2 signal refs, got %d.",
                    loop_name,
                    len(loop_field_list),
                )
                continue
            signals = _resolve_signal_references(loop_field_list[:2], all_signal_list)
            if len(signals) != 2:  # noqa: PLR2004
                logger.warning(
                    "⚠️ Could not resolve both signals for global loop '%s' (resolved %d/2).",
                    loop_name,
                    len(signals),
                )
                continue
            signal_x, signal_y = signals
            try:
                loop_signal = Signal.loop_from_signals(signal_x, signal_y, name=loop_name)
                plot_group_list.append(PlotGroup.from_single_signal(loop_signal))
            except Exception:
                logger.exception("⚠️ Error constructing global loop '%s'.", loop_name)
                continue
            logger.info(
                "✅ Global loop '%s' created (%s x %s).",
                loop_name,
                signal_x.raw_name,
                signal_y.raw_name,
            )
        except Exception:
            logger.exception("❌ Unexpected error while processing global loop '%s'.", loop_name)

    try:
        plot_model_list = PlotModel.assign_plot_model(plot_group_list)
    except Exception:
        logger.exception("❌ Failed to assign PlotModel list.")
        return []

    logger.info(
        "📊 Visualization complete: %d signal(s), %d plot group(s), %d plot model(s).",
        len(all_signal_list),
        len(plot_group_list),
        len(plot_model_list),
    )
    return plot_model_list


def inspect(
    patient_options: dict,
    database_options_global: dict | None = None,
) -> list[DataSourceInspection]:
    """
    Run find → load → format for each enabled datasource and return inspection results.

    Does NOT call _extract_signals() or build PlotModels.
    Returns one DataSourceInspection per datasource present in database_options_global.
    """
    database_options_global = _resolve_database_options(database_options_global)
    requested_sources = [
        ds.NAME for ds in datasource_list.DataSource.AVAILABLE if ds.NAME in database_options_global
    ]
    logger.info(
        "🔎 Starting inspection for %d datasource(s): %s",
        len(requested_sources),
        requested_sources,
    )

    results = []
    for data_source in datasource_list.DataSource.AVAILABLE:
        name = data_source.NAME
        if name not in database_options_global:
            continue

        db_opts = database_options_global[name]
        warn_redundant_entries(db_opts, name)

        datasource_cls = data_source.DATASOURCE_CLASS
        if datasource_cls is None:
            logger.error("No DataSourceBase subclass found for '%s', skipping inspection.", name)
            results.append(
                DataSourceInspection(
                    datasource_name=name,
                    status="load_error",
                    error_message="DataSource class not found",
                )
            )
            continue

        try:
            inspection = datasource_cls.inspect(patient_options, db_opts)
        except Exception as exc:
            logger.exception("❌ Inspection failed for datasource '%s'.", name)
            inspection = DataSourceInspection(
                datasource_name=name,
                status="load_error",
                error_message=str(exc),
            )

        if isinstance(inspection, list):
            results.extend(inspection)
        else:
            results.append(inspection)

    logger.info("🔎 Inspection complete: %d datasource(s) inspected.", len(results))
    return results


def extract_datasource(
    datasource_folder: str | Path,
    database_options_specific: dict | None = None,
    patient_options: dict | None = None,
    datasource_cls: type | None = None,
    save_path: str | Path | None = None,
) -> pd.DataFrame | None:
    """
    Load and format a single datasource folder, returning the formatted DataFrame.

    The datasource type is auto-detected from the folder name via
    :func:`~clinical_data_visualizer.datasource_list.detect_datasource_from_folder`
    unless *datasource_cls* is supplied explicitly.

    ``data_folder`` in *patient_options* is always set to ``datasource_folder.parent``
    so the pipeline's ``_find_folder`` logic can locate the correct subfolder.

    Args:
        datasource_folder: Path to the datasource subfolder
            (e.g. ``/data/Patient01/philips_waves``).
        database_options_specific: Per-datasource database options (optional).
        patient_options: Patient-level options (``datetime_start``, ``datetime_end``, …).
            ``data_folder`` is always overridden.
        datasource_cls: Explicit ``DataSourceBase`` subclass.  When provided,
            folder-name auto-detection is skipped.
        save_path: If given, the formatted DataFrame is saved to this path.
            Extension must be ``.csv`` or ``.parquet``.

    Returns:
        Formatted ``pd.DataFrame``, or ``None`` if no data was found or an error occurred.

    """
    datasource_folder = Path(datasource_folder)

    if datasource_cls is None:
        ds = datasource_list.detect_datasource_from_folder(datasource_folder)
        if ds is None:
            logger.warning(
                "No datasource matched folder name '%s' — skipping.", datasource_folder.name
            )
            return None
        datasource_cls = ds.DATASOURCE_CLASS
        if datasource_cls is None:
            logger.error("No DataSourceBase subclass for '%s' — skipping.", ds.NAME)
            return None

    opts = dict(patient_options or {})
    opts["data_folder"] = str(datasource_folder.parent)
    db_opts = database_options_specific or {}

    return datasource_cls.extract(opts, db_opts, save_path=save_path)


def extract_patient(
    patient_folder: str | Path,
    database_options_global: dict | None = None,
    patient_options: dict | None = None,
    save_folder: str | Path | None = None,
) -> dict[str, pd.DataFrame | None]:
    """
    Run find → load → format for each datasource present in *database_options_global*.

    Args:
        patient_folder: Path to the patient data folder.
        database_options_global: Full database options dict (all datasource sections + global).
            Defaults to all available datasources with their default options.
        patient_options: Optional overrides for patient-level options (``datetime_start``,
            ``datetime_end``, ``quick_load``, …).  ``data_folder`` is always set from
            *patient_folder* and cannot be overridden here.
        save_folder: If given, each formatted DataFrame is saved as
            ``<save_folder>/<datasource_name>.parquet``.

    Returns:
        Mapping ``{datasource_name: DataFrame | None}``.

    """
    database_options_global = _resolve_database_options(database_options_global)

    patient_options = dict(patient_options or {})
    patient_options["data_folder"] = str(patient_folder)

    requested_sources = [
        ds.NAME for ds in datasource_list.DataSource.AVAILABLE if ds.NAME in database_options_global
    ]
    logger.info(
        "📤 Starting extraction for %d datasource(s): %s",
        len(requested_sources),
        requested_sources,
    )

    results: dict[str, pd.DataFrame | None] = {}

    for data_source in datasource_list.DataSource.AVAILABLE:
        name = data_source.NAME
        if name not in database_options_global:
            continue

        db_opts = database_options_global[name]
        warn_redundant_entries(db_opts, name)

        datasource_cls = data_source.DATASOURCE_CLASS
        if datasource_cls is None:
            logger.error("No DataSourceBase subclass found for '%s', skipping.", name)
            results[name] = None
            continue

        save_path = Path(save_folder) / f"{name}.parquet" if save_folder is not None else None
        results[name] = datasource_cls.extract(patient_options, db_opts, save_path=save_path)

    success = sum(1 for v in results.values() if v is not None)
    logger.info("📤 Extraction complete: %d/%d datasource(s) succeeded.", success, len(results))
    return results


def batch_extract(
    patient_folders_or_root: str | Path | list[str | Path],
    database_options_global: dict | None = None,
    patient_options: dict | None = None,
    save_folder: str | Path | None = None,
) -> dict[str, dict[str, pd.DataFrame | None]]:
    """
    Run :func:`extract_patient` for multiple patient folders.

    Args:
        patient_folders_or_root: Either a single directory whose immediate
            subdirectories are patient folders, or a list of patient folder paths.
        database_options_global: Full database options dict shared across all patients.
            Defaults to all available datasources with their default options.
        patient_options: Base patient-level options applied to every patient.
            ``data_folder`` is always overridden per patient.
        save_folder: If given, each patient's DataFrames are saved under
            ``<save_folder>/<patient_name>/<datasource_name>.parquet``.

    Returns:
        Mapping ``{patient_folder_name: {datasource_name: DataFrame | None}}``.
        A patient that raises an unexpected exception is stored as ``{}``.

    """
    database_options_global = _resolve_database_options(database_options_global)

    if isinstance(patient_folders_or_root, (str, Path)):
        root = Path(patient_folders_or_root)
        folders = sorted(f for f in root.iterdir() if f.is_dir())
    else:
        folders = [Path(f) for f in patient_folders_or_root]

    logger.info("📦 Batch extraction: %d folder(s).", len(folders))
    batch_results: dict[str, dict[str, pd.DataFrame | None]] = {}

    for folder in folders:
        logger.info("── Folder: %s", folder)

        per_patient_save = Path(save_folder) / folder.name if save_folder is not None else None

        try:
            folder_results = extract_patient(
                folder,
                database_options_global,
                patient_options=patient_options,
                save_folder=per_patient_save,
            )
        except Exception:
            logger.exception("❌ Unexpected error processing folder '%s'.", folder)
            folder_results = {}

        batch_results[folder.name] = folder_results

    logger.info("📦 Batch complete: %d folder(s) processed.", len(batch_results))
    return batch_results
