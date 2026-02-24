import logging

from clinical_data_visualizer import constants as cst
from clinical_data_visualizer import datasource_list
from clinical_data_visualizer.signal_container import (
    PlotGroup,
    PlotModel,
    Signal,
)

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
def main(
    patient_options: dict,
    database_options_global: dict,
) -> list[PlotModel]:
    all_signal_list = []
    already_used_in_group = []
    plot_group_list = []

    # Collect global grouped fields so we do not plot them twice
    global_groups = database_options_global.get(cst.DatabaseOptions.GLOBAL, {}).get(
        cst.DatabaseOptions.GROUPED_FIELDS, {}
    )
    for global_grouped_field_list in global_groups.values():
        already_used_in_group.extend(global_grouped_field_list)

    requested_sources = [
        ds.NAME
        for ds in datasource_list.DataSource.AVAILABLE
        if ds.NAME in database_options_global
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

        database_options_specific = database_options_global[name]

        try:
            # (1) Create signals
            try:
                list_signal = data_source.MAIN_MODULE(patient_options, database_options_specific)
                all_signal_list.extend(list_signal)
                logger.info("✅ [%s] %d signal(s) loaded.", name, len(list_signal))
            except Exception:
                logger.exception("❌ Failed to create signals for datasource '%s'. Skipping.", name)
                continue

            # Read grouped/loop fields after MAIN_MODULE (datasource may populate dynamically)
            local_group = database_options_specific.get(cst.DatabaseOptions.GROUPED_FIELDS, {})
            for grouped_field_list in local_group.values():
                already_used_in_group.extend(grouped_field_list)

            local_loop_group = database_options_specific.get(cst.DatabaseOptions.LOOP, {})

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

    for group_name, grouped_field_list in grouped_fields_global.items():
        try:
            signals = [sig for sig in all_signal_list if sig.raw_name in grouped_field_list]
            if signals:
                plot_group_list.append(PlotGroup(name=group_name, signals=signals))
        except Exception:
            logger.exception("⚠️ Failed to create global PlotGroup '%s'.", group_name)

    # Handle global loop not implemented
    if cst.DatabaseOptions.LOOP in database_options_global.get(cst.DatabaseOptions.GLOBAL, {}):
        logger.error("loop not implemented for trace from different signals yet")
    # TODO: implement it

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
