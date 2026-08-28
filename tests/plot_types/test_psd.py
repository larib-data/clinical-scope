"""The psd plot type: power spectral density against frequency."""

import plotly.graph_objects as go
import pytest

from clinical_scope.plot_types.loop.plot import loop_from_signals
from clinical_scope.plot_types.psd.plot import psd_from_signal
from clinical_scope.spectral import SpectralRefusalError


class TestPsdFromSignal:
    def test_basic_psd(self, make_spectral_source):
        source = make_spectral_source()
        psd_signal = psd_from_signal(source, psd_name="EEG PSD", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.plot_options.plot_type == "psd"
        assert isinstance(psd_signal.trace, go.Scatter)
        # One power value per frequency, both 1-D: frequency is the x-axis, not a separate axis.
        assert psd_signal.data.x.ndim == 1
        assert psd_signal.data.y.shape == psd_signal.data.x.shape
        assert psd_signal.data.spectrogram_freq_axis is None

    def test_name_is_the_source_signal_but_raw_name_is_qualified(self, make_spectral_source):
        source = make_spectral_source(raw_name="eeg")
        psd_signal = psd_from_signal(source, psd_name="EEG PSD", freq_range=(1.0, 30.0))
        # name is the legend entry; the qualified raw_name keeps wrapper.main's single-signal
        # group prune from swallowing the PSD.
        assert psd_signal.name == source.name
        assert psd_signal.raw_name == "EEG PSD::eeg"

    def test_axes_are_frequency_and_decibels(self, make_spectral_source):
        source = make_spectral_source()
        psd_signal = psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        plot_options = psd_signal.trace_options.plot_options
        assert plot_options.x_axis_title == "Frequency (Hz)"
        assert plot_options.x_axis_range == [1.0, 30.0]
        assert plot_options.y_unit_name == "dB"
        assert plot_options.y_axis_range is None

    def test_db_range_sets_the_power_axis(self, make_spectral_source):
        source = make_spectral_source()
        psd_signal = psd_from_signal(
            source, psd_name="x", freq_range=(1.0, 30.0), db_range=[40, 90]
        )
        assert psd_signal.trace_options.plot_options.y_axis_range == [40, 90]

    def test_inherits_source_signal_color(self, make_spectral_source):
        source = make_spectral_source()
        source.trace_options.line_color = "seagreen"
        psd_signal = psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.line_color == "seagreen"

    def test_decimated_signal_refuses(self, make_spectral_source):
        source = make_spectral_source(period_resampling=0.5)
        with pytest.raises(SpectralRefusalError, match="decimated"):
            psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))

    def test_non_time_series_input_raises(self, make_signal):
        loop = loop_from_signals(make_signal(raw_name="x"), make_signal(raw_name="y"))
        with pytest.raises(ValueError, match="time_series"):
            psd_from_signal(loop, psd_name="x", freq_range=(1.0, 30.0))

    def test_label_overrides_name_and_raw_name(self, make_spectral_source):
        """Two traces built from the same source (e.g. comparing window_s) need distinct
        identities; a label is the only way to tell them apart on legend/hover and raw_name."""
        source = make_spectral_source(raw_name="eeg")
        psd_signal = psd_from_signal(
            source, psd_name="EEG PSD", freq_range=(1.0, 30.0), label="wide window"
        )
        assert psd_signal.name == "wide window"
        assert psd_signal.raw_name == "EEG PSD::wide window"

    def test_window_s_changes_the_output(self, make_spectral_source):
        source = make_spectral_source()
        narrow = psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0), window_s=2.0)
        wide = psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0), window_s=8.0)
        assert narrow.data.x.shape != wide.data.x.shape

    def test_color_and_line_dash_default_to_the_source_signal(self, make_spectral_source):
        source = make_spectral_source()
        source.trace_options.line_color = "seagreen"
        source.trace_options.line_dash = "dot"
        psd_signal = psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.line_color == "seagreen"
        assert psd_signal.trace_options.line_dash == "dot"

    def test_color_and_line_dash_are_overridable(self, make_spectral_source):
        """Two traces from the same source (e.g. comparing window_s) would otherwise be
        drawn identically, since color/line_dash both default to the source signal's own."""
        source = make_spectral_source()
        source.trace_options.line_color = "seagreen"
        psd_signal = psd_from_signal(
            source, psd_name="x", freq_range=(1.0, 30.0), color="red", line_dash="dash"
        )
        assert psd_signal.trace_options.line_color == "red"
        assert psd_signal.trace_options.marker_color == "red"
        assert psd_signal.trace_options.line_dash == "dash"
