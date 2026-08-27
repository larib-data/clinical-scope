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
from clinical_scope.signal_container import PlotGroup, Signal
from clinical_scope.spectral import SpectralRefusalError

# ==================================================================================================
logger = logging.getLogger(__name__)


# ==================================================================================================
# Reference resolution
# ==================================================================================================
def _warn_if_also_a_raw_name(
    ref: str, chosen: Signal, all_signals: list[Signal], separator: str
) -> None:
    """
    Log when *ref* reads as a qualified name *and* as some signal's bare raw_name.

    Only an 'other' file named after a registered datasource can cause this, so it is rare --
    but silent, since both readings are legitimate. The log names the loser and the spelling
    that reaches it.
    """
    shadowed = [signal for signal in all_signals if signal.raw_name == ref and signal is not chosen]
    if not shadowed:
        return
    logger.warning(
        "⚠️ Ambiguous signal reference '%s': read as datasource '%s', but it is also the raw "
        "name of a signal in datasource '%s'. Using the former -- write '%s' for the latter.",
        ref,
        chosen.metadata.datasource_name,
        shadowed[0].metadata.datasource_name,
        f"{shadowed[0].metadata.datasource_name}{separator}{ref}",
    )


def _resolve_signal_references(field_list: list[str], all_signals: list[Signal]) -> list[Signal]:
    """
    Resolve signal references using a three-mode fallback chain.

    1. Qualified name ``"datasource::raw_name"`` -- explicit, unambiguous.
    2. Display name -- matches ``signal.name``. Warns if ambiguous.
    3. Raw name -- current behaviour, backward compatible.

    A ref containing the separator tries mode 1 first but still falls through when it finds
    nothing: an 'other' file's raw_name is itself ``<stem>::<column>``, so ``waves::art`` is a
    mode-3 hit while ``other::waves::art`` is the mode-1 one, and both must resolve.

    Because of that double meaning a ref can match under both readings at once -- a file
    ``other/servo_u.parquet`` makes ``servo_u::Paw`` name both the servo_u datasource's column
    and that file's. Mode 1 wins (an explicit datasource beats a coincidence of file naming)
    and the collision is logged, since the fully qualified form reaches the other one.
    """
    matched: list[Signal] = []

    separator = cst.QUALIFIED_NAME_SEPARATOR
    for ref in field_list:
        # Mode 1: qualified "datasource::raw_name"
        if separator in ref:
            matched_signal = next(
                (
                    signal
                    for signal in all_signals
                    if f"{signal.metadata.datasource_name}{separator}{signal.raw_name}" == ref
                ),
                None,
            )
            if matched_signal:
                _warn_if_also_a_raw_name(ref, matched_signal, all_signals, separator)
                matched.append(matched_signal)
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
            if by_raw:
                matched.extend(by_raw)
            elif separator in ref:
                logger.warning("Qualified reference '%s' did not match any signal.", ref)

    return matched


# ==================================================================================================
# Derived-plot builders
# ==================================================================================================
class _SourceSignalNotFoundError(Exception):
    """Raised by a plot-group builder when its source signal isn't among the loaded signals."""


class _DerivedPlotArityError(Exception):
    """Raised by a plot-group builder given the wrong number of signal references."""


def _resolve_one(reference: str, all_signals: list[Signal]) -> Signal:
    matched = _resolve_signal_references([reference], all_signals) if reference else []
    if not matched:
        raise _SourceSignalNotFoundError(reference)
    return matched[0]


def _build_loop_signal(
    all_signals: list[Signal], loop_name: str, loop_field_list: list[str]
) -> Signal:
    if len(loop_field_list) != 2:  # noqa: PLR2004
        msg = f"needs exactly 2 signal references, got {len(loop_field_list)}"
        raise _DerivedPlotArityError(msg)
    signal_x, signal_y = (_resolve_one(reference, all_signals) for reference in loop_field_list)
    return Signal.loop_from_signals(signal_x, signal_y, name=loop_name)


def _build_spectrogram_signal(
    all_signals: list[Signal], spectrogram_name: str, spectrogram_config: dict
) -> Signal:
    config_cls = cst.DatabaseOptions.SpectrogramConfig
    source_signal = _resolve_one(spectrogram_config.get(config_cls.SIGNAL), all_signals)
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


def _build_psd_signals(all_signals: list[Signal], psd_name: str, psd_config: dict) -> list[Signal]:
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
        # Resolved one entry at a time (rather than batched) so a per-entry window_s/overlap
        # override stays attached to the right match.
        source_signals = _resolve_signal_references([reference], all_signals)
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
    matched = _resolve_signal_references([reference], datasource_signals)
    target = matched[0].raw_name if matched else reference
    return f"{datasource_name}{cst.QUALIFIED_NAME_SEPARATOR}{target}"


def _qualify_loop(config: Any, datasource_name: str, datasource_signals: list[Signal]) -> Any:
    if not isinstance(config, (list, tuple)):
        return config
    return [_qualify(reference, datasource_name, datasource_signals) for reference in config]


def _qualify_spectrogram(
    config: Any, datasource_name: str, datasource_signals: list[Signal]
) -> Any:
    key = cst.DatabaseOptions.SpectrogramConfig.SIGNAL
    if not isinstance(config, dict) or key not in config:
        return config
    return {**config, key: _qualify(config[key], datasource_name, datasource_signals)}


def _qualify_psd(config: Any, datasource_name: str, datasource_signals: list[Signal]) -> Any:
    key = cst.DatabaseOptions.PsdConfig.SIGNALS
    entry_key = cst.DatabaseOptions.PsdConfig.Entry.SIGNAL
    if not isinstance(config, dict) or not isinstance(config.get(key), (list, tuple)):
        return config
    qualified = [
        {**entry, entry_key: _qualify(entry[entry_key], datasource_name, datasource_signals)}
        if isinstance(entry, dict)
        else _qualify(entry, datasource_name, datasource_signals)
        for entry in config[key]
    ]
    return {**config, key: qualified}


@dataclass(frozen=True)
class _DerivedPlotKind:
    """One kind of plot derived from already-loaded signals, and how to read its config."""

    section_key: str
    build: Callable[[list[Signal], str, Any], Signal | list[Signal]]
    qualify: Callable[[Any, str, list[Signal]], Any]
    refusals: tuple[type[Exception], ...] = ()


# In the order their sections are read. Adding a derived plot type is a row here plus its
# builder and its qualifier -- assemble_plot_groups itself does not change.
_DERIVED_PLOTS = (
    _DerivedPlotKind(
        cst.DatabaseOptions.LOOP, _build_loop_signal, _qualify_loop, (_DerivedPlotArityError,)
    ),
    _DerivedPlotKind(
        cst.DatabaseOptions.SPECTROGRAM,
        _build_spectrogram_signal,
        _qualify_spectrogram,
        (SpectralRefusalError,),
    ),
    _DerivedPlotKind(
        cst.DatabaseOptions.PSD, _build_psd_signals, _qualify_psd, (SpectralRefusalError,)
    ),
)


@dataclass(frozen=True)
class _GroupSpec:
    """One configured group of signals, its references already qualified."""

    name: str
    references: list[str]
    origin: str


@dataclass(frozen=True)
class _DerivedSpec:
    """One configured derived plot, its references already qualified."""

    kind: _DerivedPlotKind
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

            for kind in _DERIVED_PLOTS:
                for item_name, item_config in section.get(kind.section_key, {}).items():
                    config = (
                        item_config
                        if is_global
                        else kind.qualify(item_config, section_name, section_signals)
                    )
                    derived_specs.append(_DerivedSpec(kind, item_name, config, section_name))
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
    members = _resolve_signal_references(spec.references, signals)
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
            _add_derived_plot_group(
                kind=spec.kind.section_key,
                item_name=spec.name,
                datasource_name=spec.origin,
                build_signal=partial(spec.kind.build, signals, spec.name, spec.config),
                plot_group_list=plot_group_list,
                refusal_exceptions=spec.kind.refusals,
            )

    return plot_group_list
