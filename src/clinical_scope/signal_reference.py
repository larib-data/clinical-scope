"""
How a ``database_options`` string names a signal, and what happens when it names none.

Sits below both callers -- ``plot_assembly`` and each plot type's ``plot.py`` -- because
assembly reaches the builders through the registry, so a builder reaching back into assembly
for this would close a cycle. Every reference reaching here has already been rewritten as a
qualified global one (ADR-0013); local scope does not exist at this point.
"""

import logging

import clinical_scope.constants as cst
from clinical_scope.plot_types.base import SourceSignalNotFoundError
from clinical_scope.signal_container import Signal

logger = logging.getLogger(__name__)


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


def resolve_signal_references(field_list: list[str], all_signals: list[Signal]) -> list[Signal]:
    """
    Resolve signal references using a three-mode fallback chain.

    1. Qualified name ``"datasource::raw_name"`` -- explicit, unambiguous.
    2. Display name -- matches ``signal.name``. Warns if ambiguous.
    3. Raw name -- matches ``signal.raw_name``; the fallback when no display name did.

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


def resolve_one(reference: str, all_signals: list[Signal]) -> Signal:
    """Resolve a reference that must name exactly one signal, or refuse to build the plot."""
    matched = resolve_signal_references([reference], all_signals) if reference else []
    if not matched:
        raise SourceSignalNotFoundError(reference)
    return matched[0]
