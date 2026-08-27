"""Top half of the ``spectrogram`` plot type: an STFT of one time-series, drawn as a heatmap."""

import logging
from typing import Any

import plotly.graph_objects as go

import clinical_scope.constants as cst
from clinical_scope import spectral
from clinical_scope.plot_types.base import PlotBuilder, RenderSpec, require_time_series
from clinical_scope.plot_types.spectrogram.schema import SpectrogramSchema
from clinical_scope.signal_container import Data, Metadata, PlotOptions, Signal, TraceOptions
from clinical_scope.signal_reference import resolve_one

logger = logging.getLogger(__name__)


def _heatmap_trace(signal: Signal) -> go.Heatmap:
    """
    Draw the spectrogram: a heatmap, not a Scatter with different options.

    z is (freq, time): the transpose of data.y's (time, freq) shape from spectral.py, since
    go.Heatmap indexes z as [row=y value][col=x value].
    """
    color_range = signal.trace_options.plot_options.color_range
    return go.Heatmap(
        x=signal.data.x,
        y=signal.data.spectrogram_freq_axis,
        z=signal.data.y.T if signal.data.y is not None else None,
        colorscale=cst.Spectral.COLORSCALE,
        zmin=color_range[0] if color_range else None,
        zmax=color_range[1] if color_range else None,
        colorbar={"title": {"text": "dB"}},
        hovertemplate=(
            f"<b>{signal.name}</b><br>%{{x}}"
            f"<br>%{{y:{cst.Spectral.HOVER_HEATMAP_FREQ_FORMAT}}} Hz"
            f"<br>%{{z:{cst.Spectral.HOVER_DB_FORMAT}}} dB<extra></extra>"
        ),
    )


def spectrogram_from_signal(
    signal: Signal,
    name: str,
    freq_range: tuple[float, float],
    db_range: list[float] | None = None,
    window_s: float | None = None,
    overlap: float | None = None,
) -> Signal:
    """
    Build a spectrogram signal from one time-series; display fallbacks come from *signal*.

    Raises ``spectral.SpectralRefusalError`` when the source Signal's grid can't be safely
    turned into a spectrogram (too short, decimated, out-of-range) — callers decide whether
    that is a warning or an error.
    """
    require_time_series(signal)

    times, freqs, power_db = spectral.spectrogram(
        signal.data.x,
        signal.data.y,
        freq_range=freq_range,
        period_resampling=signal.metadata.period_resampling,
        params=spectral.SpectralParams.from_options(window_s, overlap),
    )

    color_range = (
        list(db_range) if db_range else list(signal.display_fallbacks.spectrogram_db_range)
    )

    # signal.data.x/timezone were already converted to display timezone by signal's own
    # to_plotly_trace() (__post_init__ runs it eagerly) -- nothing left to convert here,
    # same reasoning as loop_from_signals leaving timezone unset.
    data = Data(x=times, y=power_db, timezone=None, spectrogram_freq_axis=freqs)
    plot_options = PlotOptions(
        plot_type=SpectrogramSchema.NAME,
        y_axis_title="Frequency (Hz)",
        show_legend=False,
        color_range=color_range,
        display_timezone=signal.trace_options.plot_options.display_timezone,
    )
    trace_options = TraceOptions(plot_options=plot_options)
    return Signal(
        raw_name=name,
        name=name,
        data=data,
        trace_options=trace_options,
        metadata=Metadata(),
        display_fallbacks=signal.display_fallbacks,
        render=RenderSpec(trace_factory=_heatmap_trace),
    )


def build(all_signals: list[Signal], spectrogram_name: str, spectrogram_config: Any) -> Signal:
    """Build the spectrogram one ``spectrogram`` config entry describes."""
    config_cls = SpectrogramSchema.Config
    source_signal = resolve_one(spectrogram_config.get(config_cls.SIGNAL), all_signals)
    try:
        return spectrogram_from_signal(
            source_signal,
            name=spectrogram_name,
            freq_range=tuple(spectrogram_config[config_cls.FREQ_RANGE]),
            db_range=spectrogram_config.get(config_cls.DB_RANGE),
            window_s=spectrogram_config.get(config_cls.WINDOW_S),
            overlap=spectrogram_config.get(config_cls.OVERLAP),
        )
    except spectral.SpectralRefusalError as exc:
        msg = f"signal '{source_signal.name}' -- {exc}"
        raise spectral.SpectralRefusalError(msg) from exc


BUILDER = PlotBuilder(build=build, refusals=(spectral.SpectralRefusalError,))
