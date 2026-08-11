import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pandas as pd

from clinical_scope import constants as cst
from clinical_scope.dash_api.annotations.io import _load_annotations_from_path
from clinical_scope.dash_api.annotations.model import Annotation
from clinical_scope.database_options_parser import (
    normalize_database_options,
    validate_database_options,
)
from clinical_scope.datasource import registry as datasource_list
from clinical_scope.datasource.inspection import DataSourceInspection
from clinical_scope.io.paths import get_annotations_path
from clinical_scope.signal_container import (
    DisplayFallbacks,
    PlotGroup,
    PlotModel,
    Signal,
)
from clinical_scope.spectral import SpectralRefusalError

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def _resolve_database_options(database_options_global: dict | None) -> dict:
    if database_options_global is None:
        return datasource_list.generate_default_database_options()
    normalize_database_options(database_options_global)
    for issue in validate_database_options(database_options_global):
        if issue.severity == "error":
            logger.error("database_options [%s]: %s", issue.path, issue.message)
        elif issue.severity == "warning":
            logger.warning("database_options [%s]: %s", issue.path, issue.message)
        else:
            logger.info("database_options [%s]: %s", issue.path, issue.message)
    return database_options_global


# ==================================================================================================
def _resolve_signal_references(field_list: list[str], all_signals: list[Signal]) -> list[Signal]:
    """
    Resolve signal references using a three-mode fallback chain.

    1. Qualified name ``"datasource::raw_name"`` -- explicit, unambiguous.
    2. Display name -- matches ``signal.name``. Warns if ambiguous.
    3. Raw name -- current behaviour, backward compatible.
    """
    matched: list[Signal] = []

    for ref in field_list:
        # Mode 1: qualified "datasource::raw_name"
        if "::" in ref:
            matched_signal = next(
                (
                    signal
                    for signal in all_signals
                    if f"{signal.metadata.datasource_name}::{signal.raw_name}" == ref
                ),
                None,
            )
            if matched_signal:
                matched.append(matched_signal)
            else:
                logger.warning("Qualified reference '%s' did not match any signal.", ref)
            continue

        # Mode 2: display name
        by_name = [signal for signal in all_signals if signal.name == ref]
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
            by_raw = [signal for signal in all_signals if signal.raw_name == ref]
            matched.extend(by_raw)

    return matched


def _format_datasource_summary(found: dict[str, str], requested: list[str]) -> str:
    """
    Render a one-line found/not-found tally for a single-patient run.

    *found* maps datasource name -> an optional annotation (e.g. file stems for the
    generic ``other`` datasource); an empty annotation renders the bare name. Cheap by
    construction: callers derive it from data the pipeline already holds in memory, no
    extra I/O. Meant to be visible without ``--debug`` -- a first debugging step before
    the full per-datasource DEBUG log.
    """
    not_found = [name for name in requested if name not in found]
    parts = []
    if found:
        found_str = ", ".join(
            f"{name} ({annotation})" if annotation else name for name, annotation in found.items()
        )
        parts.append(f"Found: {found_str}")
    if not_found:
        parts.append(f"Not found ({len(not_found)}): {', '.join(not_found)}")
    return " | ".join(parts) if parts else "No datasource requested."


class _SourceSignalNotFoundError(Exception):
    """Raised by a plot-group builder when its source signal isn't in ``list_signal``."""


def _add_derived_plot_group(
    kind: str,
    item_name: str,
    datasource_name: str,
    build_signal: Callable[[], Signal | list[Signal]],
    plot_group_list: list[PlotGroup],
    refusal_exceptions: tuple[type[Exception], ...] = (),
) -> None:
    """
    Build one derived plot (loop, spectrogram, psd, ...) and add it as its own PlotGroup.

    *build_signal* returns one Signal, or a list of Signals to overlay on a single subplot
    (a psd entry naming several signals). A list is titled by *item_name*, since the entry
    names the plot rather than any one trace in it.

    Every failure is logged and skipped rather than raised, so one bad entry in
    ``database_options`` doesn't abort the rest of a datasource's plots. *build_signal*
    should raise ``_SourceSignalNotFoundError`` for a missing source signal and, optionally,
    one of *refusal_exceptions* for a deliberate, named refusal -- both are logged as
    warnings; anything else is logged with a full traceback.
    """
    try:
        signal = build_signal()
    except _SourceSignalNotFoundError as exc:
        logger.warning(
            "⚠️ Could not construct %s '%s' in datasource '%s'. Missing signal '%s'.",
            kind,
            item_name,
            datasource_name,
            exc,
        )
        return
    except refusal_exceptions as exc:
        logger.warning(
            "⚠️ %s '%s' in datasource '%s' refused: %s",
            kind.capitalize(),
            item_name,
            datasource_name,
            exc,
        )
        return
    except Exception:
        logger.exception(
            "⚠️ Error constructing %s '%s' in datasource '%s'.", kind, item_name, datasource_name
        )
        return

    try:
        if isinstance(signal, list):
            plot_group_list.append(
                PlotGroup(name=item_name, signals=signal, allow_secondary_y=False)
            )
        else:
            plot_group_list.append(PlotGroup.from_single_signal(signal))
    except Exception:
        logger.exception(
            "⚠️ Failed to create PlotGroup from %s signal '%s' in datasource '%s'.",
            kind,
            item_name,
            datasource_name,
        )


def _build_loop_signal(
    list_signal: list[Signal], loop_name: str, loop_field_list: list[str]
) -> Signal:
    signal_x = next((s for s in list_signal if s.raw_name == loop_field_list[0]), None)
    signal_y = next((s for s in list_signal if s.raw_name == loop_field_list[1]), None)
    if signal_x is None or signal_y is None:
        missing = loop_field_list[0] if signal_x is None else loop_field_list[1]
        raise _SourceSignalNotFoundError(missing)
    return Signal.loop_from_signals(signal_x, signal_y, name=loop_name)


def _build_spectrogram_signal(
    list_signal: list[Signal], spectrogram_name: str, spectrogram_config: dict
) -> Signal:
    config_cls = cst.DatabaseOptions.SpectrogramConfig
    source_raw_name = spectrogram_config.get(config_cls.SIGNAL)
    source_signal = next((s for s in list_signal if s.raw_name == source_raw_name), None)
    if source_signal is None:
        raise _SourceSignalNotFoundError(source_raw_name)
    try:
        return Signal.spectrogram_from_signal(
            source_signal,
            name=spectrogram_name,
            freq_range=tuple(spectrogram_config[config_cls.FREQ_RANGE]),
            db_range=spectrogram_config.get(config_cls.DB_RANGE),
            window_s=spectrogram_config.get(config_cls.WINDOW_S),
            overlap=spectrogram_config.get(config_cls.OVERLAP),
        )
    except SpectralRefusalError as exc:
        msg = f"signal '{source_signal.name}' -- {exc}"
        raise SpectralRefusalError(msg) from exc


def _build_psd_signals(list_signal: list[Signal], psd_name: str, psd_config: dict) -> list[Signal]:
    """Build one PSD trace per configured entry; they share a subplot, so a list comes back."""
    config_cls = cst.DatabaseOptions.PsdConfig
    entry_cls = config_cls.Entry
    # A plain string is shorthand for an Entry naming just a signal, no per-trace overrides.
    entries = [
        entry if isinstance(entry, dict) else {entry_cls.SIGNAL: entry}
        for entry in psd_config.get(config_cls.SIGNALS) or []
    ]

    freq_range = tuple(psd_config[config_cls.FREQ_RANGE])
    db_range = psd_config.get(config_cls.DB_RANGE)
    psd_signals = []
    not_found = 0
    for entry in entries:
        reference = entry[entry_cls.SIGNAL]
        # Same three-mode chain as grouped_fields: qualified, display name, or raw name.
        # Resolved one entry at a time (rather than batched) so a per-entry window_s/overlap
        # override stays attached to the right match.
        source_signals = _resolve_signal_references([reference], list_signal)
        if not source_signals:
            not_found += 1
            continue
        for source_signal in source_signals:
            try:
                psd_signals.append(
                    Signal.psd_from_signal(
                        source_signal,
                        psd_name=psd_name,
                        freq_range=freq_range,
                        db_range=db_range,
                        window_s=entry.get(entry_cls.WINDOW_S),
                        overlap=entry.get(entry_cls.OVERLAP),
                        label=entry.get(entry_cls.LABEL),
                        color=entry.get(entry_cls.COLOR),
                        line_dash=entry.get(entry_cls.LINE_DASH),
                    )
                )
            except SpectralRefusalError as exc:
                # Refuse the whole entry: a comparison missing one of its channels invites the
                # wrong reading more than an absent plot does.
                msg = f"signal '{source_signal.name}' -- {exc}"
                raise SpectralRefusalError(msg) from exc

    if not psd_signals:
        raise _SourceSignalNotFoundError(
            ", ".join(str(entry[entry_cls.SIGNAL]) for entry in entries)
        )
    if not_found:
        logger.warning(
            "⚠️ PSD '%s': %d of %d signal(s) not found; plotting the rest.",
            psd_name,
            not_found,
            len(entries),
        )
    return psd_signals


def main(
    patient_options: dict,
    database_options_global: dict | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    user_options: dict | None = None,
) -> list[PlotModel]:
    database_options_global = _resolve_database_options(database_options_global)
    # User options are passed in explicitly by the UI layer; the core never reads the on-disk
    # file. Their display tenants travel as one carrier, built once here (ADR-0005).
    display_fallbacks = DisplayFallbacks.from_user_options(user_options)
    all_signal_list = []
    already_used_in_group = []
    plot_group_list = []
    found_datasources: dict[str, str] = {}

    requested_sources = [
        ds.NAME for ds in datasource_list.DataSource.AVAILABLE if ds.NAME in database_options_global
    ]
    logger.info(
        "🚀 Starting visualization for %d datasource(s): %s",
        len(requested_sources),
        requested_sources,
    )
    datasource_list.warn_retired_datasource_folders(
        patient_options[cst.PatientOptions.PathDataFolder.NAME]
    )

    total_count = len(requested_sources)
    processed_count = 0

    for data_source in datasource_list.DataSource.AVAILABLE:
        name = data_source.NAME

        if name not in database_options_global:
            continue

        processed_count += 1
        if progress_callback is not None:
            progress_callback(processed_count, total_count, name)

        database_options = database_options_global[name]

        try:
            # (1) Create signals
            try:
                list_signal = data_source.MAIN_MODULE(
                    patient_options, database_options, display_fallbacks
                )
                all_signal_list.extend(list_signal)
                logger.info("✅ [%s] %d signal(s) loaded.", name, len(list_signal))
                if list_signal:
                    if name == datasource_list.DataSource.Other.NAME:
                        # "other" is a generic multi-file catch-all: which files actually
                        # matched is the useful signal, not a bare "found".
                        file_stems = {sig.raw_name.split("::", 1)[0] for sig in list_signal}
                        found_datasources[name] = ", ".join(sorted(file_stems))
                    else:
                        found_datasources[name] = ""
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
                        plot_group = PlotGroup.from_single_signal(signal)
                        plot_group_list.append(plot_group)
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
                    signals = [
                        signal for signal in list_signal if signal.raw_name in grouped_field_list
                    ]
                    loaded_names = {signal.raw_name for signal in signals}
                    missing = [
                        field_name
                        for field_name in grouped_field_list
                        if field_name not in loaded_names
                    ]
                    if missing:
                        logger.warning(
                            "⚠️ Group '%s' in datasource '%s': signals not found: %s",
                            group_name,
                            name,
                            missing,
                        )
                    if len(signals) >= 2:  # noqa: PLR2004
                        plot_group_list.append(PlotGroup(name=group_name, signals=signals))
                    elif len(signals) == 1:
                        plot_group_list.append(PlotGroup.from_single_signal(signals[0]))
                except Exception:
                    logger.exception(
                        "⚠️ Failed to create grouped PlotGroup '%s' in datasource '%s'.",
                        group_name,
                        name,
                    )

            # (4) Add loop signals
            for loop_name, loop_field_list in local_loop_group.items():
                _add_derived_plot_group(
                    kind="loop",
                    item_name=loop_name,
                    datasource_name=name,
                    build_signal=partial(
                        _build_loop_signal, list_signal, loop_name, loop_field_list
                    ),
                    plot_group_list=plot_group_list,
                )

            # (5) Add spectrogram signals
            local_spectrogram_group = database_options.get(cst.DatabaseOptions.SPECTROGRAM, {})
            for spectrogram_name, spectrogram_config in local_spectrogram_group.items():
                _add_derived_plot_group(
                    kind="spectrogram",
                    item_name=spectrogram_name,
                    datasource_name=name,
                    build_signal=partial(
                        _build_spectrogram_signal, list_signal, spectrogram_name, spectrogram_config
                    ),
                    plot_group_list=plot_group_list,
                    refusal_exceptions=(SpectralRefusalError,),
                )

            # (6) Add PSD signals
            local_psd_group = database_options.get(cst.DatabaseOptions.PSD, {})
            for psd_name, psd_config in local_psd_group.items():
                _add_derived_plot_group(
                    kind="psd",
                    item_name=psd_name,
                    datasource_name=name,
                    build_signal=partial(_build_psd_signals, list_signal, psd_name, psd_config),
                    plot_group_list=plot_group_list,
                    refusal_exceptions=(SpectralRefusalError,),
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
            n_missing = len(grouped_field_list) - len(signals)
            if n_missing > 0:
                logger.warning(
                    "⚠️ Global group '%s': %d of %d signal(s) not found.",
                    group_name,
                    n_missing,
                    len(grouped_field_list),
                )
            if len(signals) >= 2:  # noqa: PLR2004
                plot_group_list.append(PlotGroup(name=group_name, signals=signals))
                global_grouped_raw_names.update(s.raw_name for s in signals)
            elif len(signals) == 1:
                logger.info(
                    "Global group '%s' degraded to 1 signal; shown individually.", group_name
                )
        except Exception:
            logger.exception("⚠️ Failed to create global PlotGroup '%s'.", group_name)

    # Remove individual PlotGroups for signals that are now in a global group
    if global_grouped_raw_names:
        plot_group_list = [
            plot_group
            for plot_group in plot_group_list
            if len(plot_group.signals) > 1
            or plot_group.signals[0].raw_name not in global_grouped_raw_names
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
        plot_model_list = PlotModel.assign_plot_model(
            plot_group_list, display_fallbacks=display_fallbacks
        )
    except Exception:
        logger.exception("❌ Failed to assign PlotModel list.")
        return []

    logger.info(
        "📊 Visualization complete: %d signal(s), %d plot group(s), %d plot model(s).",
        len(all_signal_list),
        len(plot_group_list),
        len(plot_model_list),
    )
    logger.info(_format_datasource_summary(found_datasources, requested_sources))
    return plot_model_list


def inspect(
    patient_options: dict,
    database_options_global: dict | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    user_options: dict | None = None,
    configured_columns_only: bool = False,
) -> list[DataSourceInspection]:
    """
    Run find → load → format for each enabled datasource and return inspection results.

    Does NOT call _extract_signals() or build PlotModels.
    Returns one DataSourceInspection per datasource present in database_options_global.

    ``user_options`` only affects the timezone reported dates are displayed in (cosmetic);
    resolved here and passed down as a plain string so DataSourceBase.inspect() never reads
    ``user_options.json`` itself.

    ``configured_columns_only`` restricts the read to the configured signals — see
    :meth:`DataSourceBase.inspect` for what it costs and where it applies.
    """
    database_options_global = _resolve_database_options(database_options_global)
    display_timezone = DisplayFallbacks.from_user_options(user_options).display_timezone
    requested_sources = [
        ds.NAME for ds in datasource_list.DataSource.AVAILABLE if ds.NAME in database_options_global
    ]
    logger.info(
        "🔎 Starting inspection for %d datasource(s): %s%s",
        len(requested_sources),
        requested_sources,
        " (configured columns only)" if configured_columns_only else "",
    )
    datasource_list.warn_retired_datasource_folders(
        patient_options[cst.PatientOptions.PathDataFolder.NAME]
    )

    total_count = len(requested_sources)
    processed_count = 0

    results = []
    for data_source in datasource_list.DataSource.AVAILABLE:
        name = data_source.NAME
        if name not in database_options_global:
            continue

        processed_count += 1
        if progress_callback is not None:
            progress_callback(processed_count, total_count, name)

        database_options = database_options_global[name]

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
            inspection = datasource_cls.inspect(
                patient_options,
                database_options,
                display_timezone=display_timezone,
                configured_columns_only=configured_columns_only,
            )
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

    # "other" reports one entry per file as "other::<stem>" (see OtherDataSource.inspect) --
    # surface which files actually matched rather than a bare "found".
    found_stems: dict[str, set[str]] = {}
    found_plain: set[str] = set()
    for result in results:
        if result.status != "ok":
            continue
        base_name, sep, stem = result.datasource_name.partition("::")
        if sep:
            found_stems.setdefault(base_name, set()).add(stem)
        else:
            found_plain.add(base_name)
    found_datasources = dict.fromkeys(found_plain, "")
    for name, stems in found_stems.items():
        found_datasources[name] = ", ".join(sorted(stems))
    logger.info(_format_datasource_summary(found_datasources, requested_sources))

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
    :func:`~clinical_scope.datasource_list.detect_datasource_from_folder`
    unless *datasource_cls* is supplied explicitly.

    ``data_folder`` in *patient_options* is always set to ``datasource_folder.parent``
    so the pipeline's ``_find_folder`` logic can locate the correct subfolder.

    Args:
        datasource_folder: Path to the datasource subfolder
            (e.g. ``/data/Patient01/servo_u``).
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

    resolved_patient_options = dict(patient_options or {})
    resolved_patient_options["data_folder"] = str(datasource_folder.parent)
    database_options = database_options_specific or {}

    return datasource_cls.extract(resolved_patient_options, database_options, save_path=save_path)


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

        database_options = database_options_global[name]

        datasource_cls = data_source.DATASOURCE_CLASS
        if datasource_cls is None:
            logger.error("No DataSourceBase subclass found for '%s', skipping.", name)
            results[name] = None
            continue

        save_path = Path(save_folder) / f"{name}.parquet" if save_folder is not None else None
        results[name] = datasource_cls.extract(
            patient_options, database_options, save_path=save_path
        )

    success = sum(1 for value in results.values() if value is not None)
    logger.info("📤 Extraction complete: %d/%d datasource(s) succeeded.", success, len(results))

    # "other" is excluded here: extract() always returns None for it by design (it's
    # already a tidy CSV/parquet format, so there's nothing for extract's reformat+cache
    # job to do -- see OtherDataSource.extract()), so it would always misreport as "not
    # found" rather than "not applicable". Use main() or inspect() to see other's files.
    other_name = datasource_list.DataSource.Other.NAME
    found_datasources = {
        name: "" for name, value in results.items() if value is not None and name != other_name
    }
    extract_requested = [name for name in requested_sources if name != other_name]
    logger.info(_format_datasource_summary(found_datasources, extract_requested))

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
        folders = sorted(entry for entry in root.iterdir() if entry.is_dir())
    else:
        folders = [Path(entry) for entry in patient_folders_or_root]

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


# ==================================================================================================
# Annotation loading — multi-source entry point
# ==================================================================================================


def load_annotations(path: str | Path) -> list[Annotation]:
    """
    Load annotations from a JSON file, auto-detecting the source type.

    The path is interpreted as follows:

    1. **Ends with ``.json``** — treated as a direct JSON file path.
    2. **Any other path** — treated as a patient folder;
       annotations are loaded from ``<path>/clinical_scope_output/annotations.json``.

    Returns an empty list when the file does not exist or cannot be parsed.
    The file must contain a JSON dict with a list from key ``"annotations"`` key
    (e.g. ``{"annotations": [...]}``).

    Args:
        path: Path to a JSON file or a patient folder.


    Examples:
    --------
    >>> from clinical_scope import load_annotations
    >>> # Direct JSON file
    >>> annotations = load_annotations("/path/to/annotations.json")
    >>> # Patient folder (standard layout)
    >>> annotations = load_annotations("/data/Patient01")

    """
    path = Path(path)

    resolved_path = path if path.suffix == ".json" else get_annotations_path(path)
    return _load_annotations_from_path(resolved_path)


# ==================================================================================================
# Load all annotations from a database folder
# ==================================================================================================


def load_database_annotations(database_folder: str | Path) -> list[Annotation]:
    """
    Load all annotations from every patient subfolder within *database_folder*.

    Iterates over immediate subdirectories, calls :func:`load_annotations` for
    each (which auto-detects the source type), and attaches the subdirectory name
    as the ``patient`` attribute on every loaded annotation.

    Returns a flat list of :class:`~clinical_scope.dash_api.annotations.model.Annotation`
    with the ``patient`` field set.  Annotations from folders without
    ``annotations.json`` (or with empty annotations) are simply skipped.

    Args:
        database_folder: Path to a directory whose immediate subdirectories
            are patient data folders (each containing ``annotations.json`` or
            ``clinical_scope_output/annotations.json``).

    Returns:
        Flat list of annotations with ``patient`` set to the subfolder name.
        Returns an empty list when no subdirectories are found.

    Examples:
    --------
    >>> from clinical_scope import load_database_annotations
    >>> # Scan all patients under /data
    >>> all_annotations = load_database_annotations("/data")
    >>> for annotation in all_annotations:
    ...     print(f"{annotation.patient}: {annotation.label} ({annotation.plot_name})")
    >>> # Group by patient
    >>> from collections import defaultdict
    >>> by_patient = defaultdict(list)
    >>> for annotation in all_annotations:
    ...     by_patient[annotation.patient].append(annotation)

    """
    database_folder = Path(database_folder)

    if not database_folder.is_dir():
        logger.warning("Database folder does not exist or is not a directory: %s", database_folder)
        return []

    subdirectories = sorted(entry for entry in database_folder.iterdir() if entry.is_dir())
    if not subdirectories:
        logger.warning("No patient subdirectories found in %s", database_folder)
        return []

    all_annotations: list[Annotation] = []

    for patient_dir in subdirectories:
        patient_name = patient_dir.name
        annotations = load_annotations(patient_dir)

        for annotation in annotations:
            annotation.patient = patient_name

        all_annotations.extend(annotations)

    logger.info(
        "Loaded %d annotation(s) from %d patient folder(s) in %s",
        len(all_annotations),
        len(subdirectories),
        database_folder,
    )
    return all_annotations
