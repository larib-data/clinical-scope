"""The spectrogram plot type: an STFT of one time-series, drawn as a heatmap."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from clinical_scope.plot_types.loop.plot import loop_from_signals
from clinical_scope.plot_types.spectrogram.plot import spectrogram_from_signal
from clinical_scope.signal_container import DisplayFallbacks, Signal
from clinical_scope.spectral import SpectralRefusalError


class TestSpectrogramFromSignal:
    def test_basic_spectrogram(self, make_spectral_source):
        source = make_spectral_source()
        spec = spectrogram_from_signal(source, name="EEG spectrogram", freq_range=(1.0, 30.0))
        assert spec.trace_options.plot_options.plot_type == "spectrogram"
        assert spec.name == "EEG spectrogram"
        assert isinstance(spec.trace, go.Heatmap)
        assert spec.data.spectrogram_freq_axis is not None
        assert spec.data.y.shape == (len(spec.data.x), len(spec.data.spectrogram_freq_axis))

    def test_decimated_signal_refuses(self, make_spectral_source):
        source = make_spectral_source(period_resampling=0.5)
        with pytest.raises(SpectralRefusalError, match="decimated"):
            spectrogram_from_signal(source, name="x", freq_range=(1.0, 30.0))

    def test_non_time_series_input_raises(self, make_signal):
        loop = loop_from_signals(make_signal(raw_name="x"), make_signal(raw_name="y"))
        with pytest.raises(ValueError, match="time_series"):
            spectrogram_from_signal(loop, name="x", freq_range=(1.0, 30.0))

    def test_db_range_override(self, make_spectral_source):
        source = make_spectral_source()
        spec = spectrogram_from_signal(source, name="x", freq_range=(1.0, 30.0), db_range=[-20, 10])
        assert spec.trace_options.plot_options.color_range == [-20, 10]
        assert (spec.trace.zmin, spec.trace.zmax) == (-20, 10)

    def test_db_range_falls_back_to_display_fallbacks(self):
        df = pd.DataFrame(
            {"eeg": np.sin(2 * np.pi * 10.0 * np.arange(1280) / 128.0)},
            index=pd.date_range("2024-01-01", periods=1280, freq="7.8125ms", tz="UTC"),
        )
        fallbacks = DisplayFallbacks(spectrogram_db_range=(-5.0, 15.0))
        source = Signal.time_series_from_dataframe(df, "eeg", display_fallbacks=fallbacks)
        spec = spectrogram_from_signal(source, name="x", freq_range=(1.0, 30.0))
        assert spec.trace_options.plot_options.color_range == [-5.0, 15.0]
