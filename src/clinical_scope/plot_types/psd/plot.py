"""Top half of the ``psd`` plot type: power spectral density, several signals to a subplot."""

import logging
from typing import Any

import clinical_scope.constants as cst
from clinical_scope import spectral
from clinical_scope.plot_types.base import (
    PlotBuilder,
    RenderSpec,
    SourceSignalNotFoundError,
    require_time_series,
)
from clinical_scope.plot_types.psd.definition import PsdDefinition
from clinical_scope.signal_container import Data, Metadata, PlotOptions, Signal, TraceOptions
from clinical_scope.signal_reference import resolve_signal_references

logger = logging.getLogger(__name__)


def _hover_spec(signal_name: str) -> RenderSpec:
    """X is frequency and y always dB, so neither unit comes from the signal itself."""
    return RenderSpec(
        hover_template=(
            f"<b>{signal_name}</b>"
            f"<br>%{{x:{cst.Spectral.HOVER_PSD_FREQ_FORMAT}}} Hz"
            f"<br>%{{y:{cst.Spectral.HOVER_DB_FORMAT}}} dB<extra></extra>"
        )
    )


def psd_from_signal(
    signal: Signal,
    psd_name: str,
    freq_range: tuple[float, float],
    db_range: list[float] | None = None,
    window_s: float | None = None,
    overlap: float | None = None,
    label: str | None = None,
    color: str | None = None,
    line_dash: str | None = None,
) -> Signal:
    """
    Build one PSD signal from one time-series; display fallbacks come from *signal*.

    One trace, not one subplot: several PSDs share a subplot when a ``psd`` entry names
    several signals, so the caller groups them. Raises ``spectral.SpectralRefusalError``
    on a grid that can't be safely analysed, like ``spectrogram_from_signal``. *label*
    distinguishes two traces built from the same *signal* (e.g. compared with different
    *window_s*) that would otherwise share both name and raw_name; *color*/*line_dash*
    do the same visually, since both otherwise default to the source signal's own.
    """
    require_time_series(signal)

    freqs, power_db = spectral.psd(
        signal.data.x,
        signal.data.y,
        freq_range=freq_range,
        period_resampling=signal.metadata.period_resampling,
        params=spectral.SpectralParams.from_options(window_s, overlap),
    )

    data = Data(x=freqs, y=power_db, timezone=None)
    plot_options = PlotOptions(
        definition=PsdDefinition,
        x_axis_title="Frequency (Hz)",
        x_unit_name="Hz",
        x_axis_range=list(freq_range),
        y_axis_title="Power spectral density (dB)",
        y_unit_name="dB",
        y_axis_range=list(db_range) if db_range else None,
        show_legend=False,
        display_timezone=signal.trace_options.plot_options.display_timezone,
    )
    trace_options = TraceOptions(
        plot_options=plot_options,
        # Match the source signal's colour/dash by default, so an overlay reads as the
        # same channel; both are overridable to tell apart 2 traces sharing a signal.
        line_color=color or signal.trace_options.line_color,
        marker_color=color or signal.trace_options.marker_color,
        line_dash=line_dash or signal.trace_options.line_dash,
    )
    display_name = label or signal.name
    return Signal(
        # Qualified by the PSD's own name: two entries built from one source signal with
        # different window_s would otherwise share a raw_name as well as a display name.
        raw_name=f"{psd_name}{cst.QUALIFIED_NAME_SEPARATOR}{label or signal.raw_name}",
        name=display_name,
        data=data,
        trace_options=trace_options,
        metadata=Metadata(),
        display_fallbacks=signal.display_fallbacks,
        render=_hover_spec(display_name),
    )


def build(all_signals: list[Signal], psd_name: str, psd_config: Any) -> list[Signal]:
    """Build one PSD trace per configured entry; they share a subplot, so a list comes back."""
    config_cls = PsdDefinition.Config
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
        source_signals = resolve_signal_references([reference], all_signals)
        if not source_signals:
            not_found += 1
            continue
        for source_signal in source_signals:
            try:
                psd_signals.append(
                    psd_from_signal(
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
            except spectral.SpectralRefusalError as exc:
                # Refuse the whole entry: a comparison missing one of its channels invites the
                # wrong reading more than an absent plot does.
                msg = f"signal '{source_signal.name}' -- {exc}"
                raise spectral.SpectralRefusalError(msg) from exc

    if not psd_signals:
        raise SourceSignalNotFoundError(
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


BUILDER = PlotBuilder(build=build, refusals=(spectral.SpectralRefusalError,))
