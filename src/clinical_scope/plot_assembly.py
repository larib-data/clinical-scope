"""
Turn loaded Signals plus a ``database_options`` dict into the PlotGroups a figure is drawn from.

This is the last purely-domain step of the visualize pipeline: it runs once, after every
datasource has loaded, and needs nothing on disk. Two rules govern it (ADR-0013):

* **Config scope is desugared once.** A per-datasource section is a namespace, not a
  different kind of grouping, so its references are rewritten as qualified global ones
  before anything else happens. Downstream, local scope does not exist -- one resolver,
  one suppression rule, one spelling of a reference.
* **Group membership joins on signal identity, not on ``raw_name``.** A raw name is unique
  only *within* a datasource, so any join on it across datasources silently drops a plot
  the first time two sources share a name (``HR``, ``SpO2``, ``ABP``).

Every failure here is logged and skipped: one bad ``database_options`` entry must not blank
a clinician's screen.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from clinical_scope import constants as cst
from clinical_scope.plot_types import builders
from clinical_scope.plot_types import registry as plot_types
from clinical_scope.plot_types.base import PlotTypeSchema, SourceSignalNotFoundError
from clinical_scope.signal_container import PlotGroup, Signal
from clinical_scope.signal_reference import resolve_signal_references

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
# Desugaring per-datasource sections into qualified global ones
# ==================================================================================================
def _qualify(reference: Any, datasource_name: str, datasource_signals: list[Signal]) -> str:
    """
    Rewrite a per-datasource reference as the qualified ``datasource::raw_name`` (ADR-0013).

    Resolved against that datasource's own signals, so the section keeps acting as the
    namespace it always implicitly was -- and an unresolvable reference is qualified all the
    same, so it cannot fall through and match a namesake belonging to another source.
    """
    matched = resolve_signal_references([reference], datasource_signals)
    target = matched[0].raw_name if matched else reference
    return f"{datasource_name}{cst.QUALIFIED_NAME_SEPARATOR}{target}"


@dataclass(frozen=True)
class _GroupSpec:
    """One configured group of signals, its references already qualified."""

    name: str
    references: list[str]
    origin: str


@dataclass(frozen=True)
class _DerivedSpec:
    """One configured derived plot, its references already qualified."""

    schema: type[PlotTypeSchema]
    name: str
    config: Any
    origin: str


def _flatten_config(
    database_options_global: dict, signals: list[Signal]
) -> tuple[list[_GroupSpec], list[_DerivedSpec]]:
    """
    Desugar every per-datasource section into qualified global references.

    Runs at the head of assembly rather than at parse time because ``other`` injects its
    derived sections into its own section *during load*, after normalization has run.
    Returns internal values; *database_options_global* is never written back to.
    """
    group_specs: list[_GroupSpec] = []
    derived_specs: list[_DerivedSpec] = []

    for section_name, section in database_options_global.items():
        if not isinstance(section, dict):
            continue
        is_global = section_name == cst.DatabaseOptions.GLOBAL
        section_signals = [
            signal for signal in signals if signal.metadata.datasource_name == section_name
        ]
        configured_groups = section.get(cst.DatabaseOptions.GROUPED_FIELDS, {})
        try:
            for group_name, references in configured_groups.items():
                qualified = (
                    list(references)
                    if is_global
                    else [_qualify(ref, section_name, section_signals) for ref in references]
                )
                group_specs.append(_GroupSpec(group_name, qualified, section_name))

            qualify = partial(
                _qualify, datasource_name=section_name, datasource_signals=section_signals
            )
            # Straight off the registry: adding a derived plot type changes nothing here.
            for schema in plot_types.DERIVED:
                for item_name, item_config in section.get(schema.SECTION_KEY, {}).items():
                    config = item_config if is_global else schema.map_refs(item_config, qualify)
                    derived_specs.append(_DerivedSpec(schema, item_name, config, section_name))
        except Exception:
            logger.exception("⚠️ Unreadable database_options section '%s'; skipping.", section_name)

    return group_specs, derived_specs


# ==================================================================================================
# Assembly
# ==================================================================================================
def _origin_order(signals: list[Signal], database_options_global: dict) -> list[str | None]:
    """
    The order plots are emitted in: datasources in load order, then ``global`` last.

    Taken from *signals* rather than from the registry, so assembly stays free of the
    loading machinery; a configured datasource that loaded nothing still gets its turn,
    so its unresolved entries are reported where a reader expects them.
    """
    order: list[str | None] = []
    for signal in signals:
        if signal.metadata.datasource_name not in order:
            order.append(signal.metadata.datasource_name)
    for section_name in database_options_global:
        if section_name != cst.DatabaseOptions.GLOBAL and section_name not in order:
            order.append(section_name)
    order.append(cst.DatabaseOptions.GLOBAL)
    return order


def _resolve_members(spec: _GroupSpec, signals: list[Signal]) -> list[Signal]:
    members = resolve_signal_references(spec.references, signals)
    missing = len(spec.references) - len(members)
    if missing > 0:
        logger.warning(
            "⚠️ Group '%s' (%s): %d of %d signal(s) not found.",
            spec.name,
            spec.origin,
            missing,
            len(spec.references),
        )
    return members


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
    should raise ``SourceSignalNotFoundError`` for a missing source signal and, optionally,
    one of *refusal_exceptions* for a deliberate, named refusal -- both are logged as
    warnings; anything else is logged with a full traceback.
    """
    try:
        signal = build_signal()
    except SourceSignalNotFoundError as exc:
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


def assemble_plot_groups(signals: list[Signal], database_options_global: dict) -> list[PlotGroup]:
    """
    Build the plot groups a visualization is drawn from, out of loaded signals and config.

    Every signal gets a plot of its own unless it belongs to a configured group; groups and
    derived plots (loops, spectrograms, PSDs) follow their datasource's own plots, and the
    ``global`` section's come last. *database_options_global* is only read.

    Args:
        signals: Every signal loaded by the run, in datasource load order.
        database_options_global: The full database options dict, per-datasource sections
            and ``global`` alike.

    Returns:
        The plot groups, in page order.

    """
    group_specs, derived_specs = _flatten_config(database_options_global, signals)

    # Memberships first, so a default one-signal-per-plot group can be skipped for exactly the
    # signal objects a configured group took -- never for anything that merely shares a name.
    members_by_spec = [(spec, _resolve_members(spec, signals)) for spec in group_specs]
    grouped_ids = {id(signal) for _, members in members_by_spec for signal in members}

    plot_group_list: list[PlotGroup] = []
    for origin in _origin_order(signals, database_options_global):
        for signal in signals:
            if signal.metadata.datasource_name != origin or id(signal) in grouped_ids:
                continue
            try:
                plot_group_list.append(PlotGroup.from_single_signal(signal))
            except Exception:
                logger.exception(
                    "⚠️ Failed to create PlotGroup from single signal '%s' in datasource '%s'.",
                    signal.raw_name,
                    origin,
                )

        for spec, members in members_by_spec:
            if spec.origin != origin or not members:
                continue
            try:
                # A group that resolved to one signal keeps the *group's* name: the same
                # config then titles the panel identically however much data happened to load.
                plot_group_list.append(
                    PlotGroup(
                        name=spec.name,
                        signals=members,
                        allow_secondary_y=len(members) > 1,
                    )
                )
            except Exception:
                logger.exception(
                    "⚠️ Failed to create grouped PlotGroup '%s' in datasource '%s'.",
                    spec.name,
                    origin,
                )

        for spec in derived_specs:
            if spec.origin != origin:
                continue
            builder = builders.BUILDERS[spec.schema]
            _add_derived_plot_group(
                kind=spec.schema.SECTION_KEY,
                item_name=spec.name,
                datasource_name=spec.origin,
                build_signal=partial(builder.build, signals, spec.name, spec.config),
                plot_group_list=plot_group_list,
                refusal_exceptions=builder.refusals,
            )

    return plot_group_list
