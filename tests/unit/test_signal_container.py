"""Unit tests for signal_container.py — Signal, PlotGroup, PlotModel."""

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

import clinical_scope.constants as cst
from clinical_scope.signal_container import (
    DisplayFallbacks,
    PlotGroup,
    PlotModel,
    PlotOptions,
    Signal,
    compute_average_priority,
    get_unique_or_raise,
    merge_y_ranges,
    print_out_figure,
)
from clinical_scope.spectral import SpectralRefusalError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n=50, tz="UTC", columns=None):
    """Create a simple DataFrame with DatetimeIndex and float columns."""
    columns = columns or ["sig_a"]
    idx = pd.date_range("2024-01-01", periods=n, freq="1s", tz=tz)
    data = {col: np.random.default_rng(42).standard_normal(n) for col in columns}
    return pd.DataFrame(data, index=idx)


def _make_signal(raw_name="sig_a", name=None, n=50, unit="mmHg", plot_type="time_series"):
    """Create a minimal Signal using time_series_from_dataframe."""
    df = _make_df(n=n, columns=[raw_name])
    db_opts = {
        "signals": {raw_name: {"label": name or raw_name, "unit": unit}},
        "field_display": [raw_name],
    }
    return Signal.time_series_from_dataframe(df, raw_name, database_options_specific=db_opts)


def _make_spectrogram_source_signal(
    raw_name="eeg", n=1280, sample_rate_hz=128.0, period_resampling=None
):
    """A time-series Signal sampled fast/long enough for a real spectrogram window."""
    idx = pd.date_range("2024-01-01", periods=n, freq=f"{1000 / sample_rate_hz}ms", tz="UTC")
    values = np.sin(2 * np.pi * 10.0 * np.arange(n) / sample_rate_hz)
    df = pd.DataFrame({raw_name: values}, index=idx)
    db_opts = {}
    if period_resampling is not None:
        db_opts = {"numerics": {"period_resampling": period_resampling}}
    return Signal.time_series_from_dataframe(df, raw_name, database_options_specific=db_opts)


# ---------------------------------------------------------------------------
# get_unique_or_raise
# ---------------------------------------------------------------------------


class TestGetUniqueOrRaise:
    def test_unique_single(self):
        assert get_unique_or_raise([42], "x") == 42

    def test_unique_repeated(self):
        assert get_unique_or_raise([7, 7, 7], "x") == 7

    def test_empty_returns_none(self):
        assert get_unique_or_raise([], "x") is None

    def test_non_unique_raises(self):
        with pytest.raises(ValueError, match="different"):
            get_unique_or_raise([1, 2], "x")


# ---------------------------------------------------------------------------
# compute_average_priority
# ---------------------------------------------------------------------------


class TestComputeAveragePriority:
    def test_default_priority(self):
        class Obj:
            pass

        assert compute_average_priority([Obj(), Obj()]) == 10000.0

    def test_custom_priorities(self):
        class Obj:
            def __init__(self, p):
                self.plot_priority = p

        assert compute_average_priority([Obj(2), Obj(4)]) == 3.0


# ---------------------------------------------------------------------------
# merge_y_ranges
# ---------------------------------------------------------------------------


class TestMergeYRanges:
    def test_no_ranges_returns_none(self):
        sig = _make_signal()
        sig.trace_options.plot_options.y_axis_range = None
        assert merge_y_ranges([sig], sig.trace_options.plot_options.y_unit_name) is None

    def test_single_range(self):
        sig = _make_signal()
        sig.trace_options.plot_options.y_axis_range = [0, 100]
        result = merge_y_ranges([sig], sig.trace_options.plot_options.y_unit_name)
        assert result == [0, 100]

    def test_merge_expands(self):
        sig1 = _make_signal(raw_name="sig_a")
        sig1.trace_options.plot_options.y_axis_range = [0, 50]
        sig2 = _make_signal(raw_name="sig_a")
        sig2.trace_options.plot_options.y_axis_range = [-10, 100]
        # Ensure same unit
        sig2.trace_options.plot_options.y_unit_name = sig1.trace_options.plot_options.y_unit_name
        result = merge_y_ranges([sig1, sig2], sig1.trace_options.plot_options.y_unit_name)
        assert result == [-10, 100]


# ---------------------------------------------------------------------------
# Signal.time_series_from_dataframe
# ---------------------------------------------------------------------------


class TestSignalTimeSeries:
    def test_basic_creation(self):
        df = _make_df(columns=["ECG"])
        sig = Signal.time_series_from_dataframe(df, "ECG")
        assert sig.raw_name == "ECG"
        assert sig.name == "ECG"  # default: raw_name when no label given
        assert isinstance(sig.data.x, np.ndarray)
        assert isinstance(sig.data.y, np.ndarray)
        assert len(sig.data.x) == len(sig.data.y)
        assert len(sig.data.x) > 0
        assert sig.data.x.dtype == np.dtype("datetime64[ns]")
        assert sig.trace_options.plot_options.plot_type == "time_series"

    def test_trace_is_go_scatter(self):
        sig = _make_signal()
        assert isinstance(sig.trace, go.Scatter)

    def test_label_override(self):
        df = _make_df(columns=["ART"])
        db_opts = {"signals": {"ART": {"label": "Arterial pressure"}}}
        sig = Signal.time_series_from_dataframe(df, "ART", database_options_specific=db_opts)
        assert sig.name == "Arterial pressure"

    def test_unit_conversion(self):
        df = _make_df(columns=["PAP"])
        raw_values = df["PAP"].to_numpy(dtype=np.float64)
        factor = 2.0
        db_opts = {"signals": {"PAP": {"unit_conversion": factor}}}
        sig = Signal.time_series_from_dataframe(df, "PAP", database_options_specific=db_opts)
        # y values should be multiplied by factor (excluding NaNs that were pruned)
        valid_raw = raw_values[np.isfinite(raw_values)]
        np.testing.assert_allclose(sig.data.y, valid_raw * factor)

    def test_range_propagated(self):
        df = _make_df(columns=["X"])
        db_opts = {"signals": {"X": {"range": [-5, 25]}}}
        sig = Signal.time_series_from_dataframe(df, "X", database_options_specific=db_opts)
        assert sig.trace_options.plot_options.y_axis_range == [-5, 25]

    def test_visible_false(self):
        df = _make_df(columns=["X"])
        db_opts = {"signals": {"X": {"visible": False}}}
        sig = Signal.time_series_from_dataframe(df, "X", database_options_specific=db_opts)
        assert sig.trace_options.visible is False
        assert sig.trace.visible == "legendonly"

    def test_timezone_stored(self):
        df = _make_df(tz="Europe/Paris")
        sig = Signal.time_series_from_dataframe(df, "sig_a")
        # timezone is stored but may be converted during trace creation
        assert sig.data.timezone is not None


class TestTraceOptionsPrecedence:
    """A database_options trace_options block layers over the module's source_options."""

    MODULE_OPTIONS = {"trace_options": {"mode": "lines", "line_width": 1.0}}

    @staticmethod
    def _signal(source_options=None, database_options_specific=None):
        df = _make_df(columns=["X"])
        return Signal.time_series_from_dataframe(
            df,
            "X",
            source_options=source_options,
            database_options_specific=database_options_specific,
        )

    def test_user_block_applies_without_any_module_default(self):
        sig = self._signal(database_options_specific={"trace_options": {"mode": "markers"}})
        assert sig.trace.mode == "markers"

    def test_user_key_wins_over_the_module_key(self):
        sig = self._signal(
            source_options=self.MODULE_OPTIONS,
            database_options_specific={"trace_options": {"line_width": 4.0}},
        )
        assert sig.trace.line.width == 4.0

    def test_module_keys_the_user_omits_survive(self):
        sig = self._signal(
            source_options=self.MODULE_OPTIONS,
            database_options_specific={"trace_options": {"line_width": 4.0}},
        )
        assert sig.trace.mode == "lines"

    def test_unknown_keys_are_dropped_not_raised(self):
        """The parser only warns on a typo, so the reader has to tolerate one."""
        sig = self._signal(database_options_specific={"trace_options": {"mdoe": "markers"}})
        assert sig.trace.mode == "lines"

    def test_a_non_dict_block_is_ignored(self):
        """Validation reports it as an error but does not abort the run."""
        sig = self._signal(
            source_options=self.MODULE_OPTIONS,
            database_options_specific={"trace_options": "lines+markers"},
        )
        assert sig.trace.mode == "lines"

    def test_per_signal_line_dash_still_wins(self):
        """The signals block stays the last word, as the tutorial promises."""
        sig = self._signal(
            database_options_specific={
                "trace_options": {"line_dash": "solid"},
                "signals": {"X": {"line_dash": "dot"}},
            }
        )
        assert sig.trace.line.dash == "dot"


# ---------------------------------------------------------------------------
# Signal.loop_from_signals
# ---------------------------------------------------------------------------


class TestSignalLoop:
    def test_basic_loop(self):
        sig_x = _make_signal(raw_name="sig_a", unit="cmH2O")
        sig_y = _make_signal(raw_name="sig_a", name="Vol", unit="mL")
        loop = Signal.loop_from_signals(sig_x, sig_y, name="PV loop")
        assert loop.trace_options.plot_options.plot_type == "loop"
        assert loop.trace_options.plot_options.square_plot is True
        assert loop.data.loop_time_axis is not None
        assert len(loop.data.x) == len(loop.data.y)
        assert loop.name == "PV loop"

    def test_no_overlap_raises(self):
        df1 = pd.DataFrame(
            {"a": [1.0, 2.0]},
            index=pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC"),
        )
        df2 = pd.DataFrame(
            {"b": [3.0, 4.0]},
            index=pd.date_range("2025-01-01", periods=2, freq="1s", tz="UTC"),
        )
        sig_x = Signal.time_series_from_dataframe(df1, "a")
        sig_y = Signal.time_series_from_dataframe(df2, "b")
        with pytest.raises(ValueError, match="overlapping"):
            Signal.loop_from_signals(sig_x, sig_y)

    def test_empty_signal_raises(self):
        # All-NaN column → empty after pruning
        df1 = pd.DataFrame(
            {"a": [np.nan, np.nan]},
            index=pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC"),
        )
        df2 = _make_df(columns=["b"])
        sig_x = Signal.time_series_from_dataframe(df1, "a")
        sig_y = Signal.time_series_from_dataframe(df2, "b")
        with pytest.raises(ValueError, match="no data"):
            Signal.loop_from_signals(sig_x, sig_y)


class TestSignalSpectrogram:
    def test_basic_spectrogram(self):
        source = _make_spectrogram_source_signal()
        spec = Signal.spectrogram_from_signal(
            source, name="EEG spectrogram", freq_range=(1.0, 30.0)
        )
        assert spec.trace_options.plot_options.plot_type == cst.PlotType.SPECTROGRAM
        assert spec.name == "EEG spectrogram"
        assert isinstance(spec.trace, go.Heatmap)
        assert spec.data.spectrogram_freq_axis is not None
        assert spec.data.y.shape == (len(spec.data.x), len(spec.data.spectrogram_freq_axis))

    def test_decimated_signal_refuses(self):
        source = _make_spectrogram_source_signal(period_resampling=0.5)
        with pytest.raises(SpectralRefusalError, match="decimated"):
            Signal.spectrogram_from_signal(source, name="x", freq_range=(1.0, 30.0))

    def test_non_time_series_input_raises(self):
        loop = Signal.loop_from_signals(_make_signal(raw_name="x"), _make_signal(raw_name="y"))
        with pytest.raises(ValueError, match="time_series"):
            Signal.spectrogram_from_signal(loop, name="x", freq_range=(1.0, 30.0))

    def test_db_range_override(self):
        source = _make_spectrogram_source_signal()
        spec = Signal.spectrogram_from_signal(
            source, name="x", freq_range=(1.0, 30.0), db_range=[-20, 10]
        )
        assert spec.trace_options.plot_options.color_range == [-20, 10]
        assert (spec.trace.zmin, spec.trace.zmax) == (-20, 10)

    def test_db_range_falls_back_to_display_fallbacks(self):
        df = pd.DataFrame(
            {"eeg": np.sin(2 * np.pi * 10.0 * np.arange(1280) / 128.0)},
            index=pd.date_range("2024-01-01", periods=1280, freq="7.8125ms", tz="UTC"),
        )
        fallbacks = DisplayFallbacks(spectrogram_db_range=(-5.0, 15.0))
        source = Signal.time_series_from_dataframe(df, "eeg", display_fallbacks=fallbacks)
        spec = Signal.spectrogram_from_signal(source, name="x", freq_range=(1.0, 30.0))
        assert spec.trace_options.plot_options.color_range == [-5.0, 15.0]


class TestSignalPsd:
    def test_basic_psd(self):
        source = _make_spectrogram_source_signal()
        psd_signal = Signal.psd_from_signal(source, psd_name="EEG PSD", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.plot_options.plot_type == "psd"
        assert isinstance(psd_signal.trace, go.Scatter)
        # One power value per frequency, both 1-D: frequency is the x-axis, not a separate axis.
        assert psd_signal.data.x.ndim == 1
        assert psd_signal.data.y.shape == psd_signal.data.x.shape
        assert psd_signal.data.spectrogram_freq_axis is None

    def test_name_is_the_source_signal_but_raw_name_is_qualified(self):
        source = _make_spectrogram_source_signal(raw_name="eeg")
        psd_signal = Signal.psd_from_signal(source, psd_name="EEG PSD", freq_range=(1.0, 30.0))
        # name is the legend entry; the qualified raw_name keeps wrapper.main's single-signal
        # group prune from swallowing the PSD.
        assert psd_signal.name == source.name
        assert psd_signal.raw_name == "EEG PSD::eeg"

    def test_axes_are_frequency_and_decibels(self):
        source = _make_spectrogram_source_signal()
        psd_signal = Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        plot_options = psd_signal.trace_options.plot_options
        assert plot_options.x_axis_title == "Frequency (Hz)"
        assert plot_options.x_axis_range == [1.0, 30.0]
        assert plot_options.y_unit_name == "dB"
        assert plot_options.y_axis_range is None

    def test_db_range_sets_the_power_axis(self):
        source = _make_spectrogram_source_signal()
        psd_signal = Signal.psd_from_signal(
            source, psd_name="x", freq_range=(1.0, 30.0), db_range=[40, 90]
        )
        assert psd_signal.trace_options.plot_options.y_axis_range == [40, 90]

    def test_inherits_source_signal_color(self):
        source = _make_spectrogram_source_signal()
        source.trace_options.line_color = "seagreen"
        psd_signal = Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.line_color == "seagreen"

    def test_decimated_signal_refuses(self):
        source = _make_spectrogram_source_signal(period_resampling=0.5)
        with pytest.raises(SpectralRefusalError, match="decimated"):
            Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))

    def test_non_time_series_input_raises(self):
        loop = Signal.loop_from_signals(_make_signal(raw_name="x"), _make_signal(raw_name="y"))
        with pytest.raises(ValueError, match="time_series"):
            Signal.psd_from_signal(loop, psd_name="x", freq_range=(1.0, 30.0))

    def test_label_overrides_name_and_raw_name(self):
        """Two traces built from the same source (e.g. comparing window_s) need distinct
        identities; a label is the only way to tell them apart on legend/hover and raw_name."""
        source = _make_spectrogram_source_signal(raw_name="eeg")
        psd_signal = Signal.psd_from_signal(
            source, psd_name="EEG PSD", freq_range=(1.0, 30.0), label="wide window"
        )
        assert psd_signal.name == "wide window"
        assert psd_signal.raw_name == "EEG PSD::wide window"

    def test_window_s_changes_the_output(self):
        source = _make_spectrogram_source_signal()
        narrow = Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0), window_s=2.0)
        wide = Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0), window_s=8.0)
        assert narrow.data.x.shape != wide.data.x.shape

    def test_color_and_line_dash_default_to_the_source_signal(self):
        source = _make_spectrogram_source_signal()
        source.trace_options.line_color = "seagreen"
        source.trace_options.line_dash = "dot"
        psd_signal = Signal.psd_from_signal(source, psd_name="x", freq_range=(1.0, 30.0))
        assert psd_signal.trace_options.line_color == "seagreen"
        assert psd_signal.trace_options.line_dash == "dot"

    def test_color_and_line_dash_are_overridable(self):
        """Two traces from the same source (e.g. comparing window_s) would otherwise be
        drawn identically, since color/line_dash both default to the source signal's own."""
        source = _make_spectrogram_source_signal()
        source.trace_options.line_color = "seagreen"
        psd_signal = Signal.psd_from_signal(
            source, psd_name="x", freq_range=(1.0, 30.0), color="red", line_dash="dash"
        )
        assert psd_signal.trace_options.line_color == "red"
        assert psd_signal.trace_options.marker_color == "red"
        assert psd_signal.trace_options.line_dash == "dash"


# ---------------------------------------------------------------------------
# PlotOptions.combine_from_signals
# ---------------------------------------------------------------------------


class TestPlotOptionsCombine:
    def test_same_unit(self):
        sig1 = _make_signal(raw_name="sig_a", unit="mmHg")
        sig2 = _make_signal(raw_name="sig_a", unit="mmHg")
        combined = PlotOptions.combine_from_signals([sig1, sig2], "Pressure")
        assert combined.y_unit_name == "mmHg"
        assert combined.y2_unit_name is None

    def test_mixed_units(self):
        sig1 = _make_signal(raw_name="sig_a", unit="mmHg")
        sig2 = _make_signal(raw_name="sig_a", unit="mL")
        combined = PlotOptions.combine_from_signals([sig1, sig2], "Mixed")
        assert combined.y_unit_name == "mmHg"
        assert combined.y2_unit_name == "mL"

    def test_show_legend_true(self):
        sig1 = _make_signal()
        sig2 = _make_signal()
        combined = PlotOptions.combine_from_signals([sig1, sig2], "Group")
        assert combined.show_legend is True

    def test_carries_x_axis_identity(self):
        """Overlaid PSDs share one frequency axis, so the group must keep its x labelling."""
        source = _make_spectrogram_source_signal(raw_name="eeg")
        psd_signals = [
            Signal.psd_from_signal(source, psd_name="EEG PSD", freq_range=(1.0, 30.0))
            for _ in range(2)
        ]
        combined = PlotOptions.combine_from_signals(psd_signals, "EEG PSD")
        assert combined.x_axis_title == "Frequency (Hz)"
        assert combined.x_axis_range == [1.0, 30.0]
        assert combined.x_unit_name == "Hz"

    def test_time_series_group_keeps_no_x_axis_identity(self):
        combined = PlotOptions.combine_from_signals([_make_signal(), _make_signal()], "Group")
        assert combined.x_axis_title is None
        assert combined.x_axis_range is None


# ---------------------------------------------------------------------------
# PlotGroup
# ---------------------------------------------------------------------------


class TestPlotGroup:
    def test_from_single_signal(self):
        sig = _make_signal()
        pg = PlotGroup.from_single_signal(sig)
        assert len(pg.signals) == 1
        assert pg.allow_secondary_y is False
        assert pg.plot_options is not None
        assert pg.name == sig.name

    def test_multi_signal(self):
        sig1 = _make_signal(raw_name="sig_a", name="A")
        sig2 = _make_signal(raw_name="sig_a", name="B")
        pg = PlotGroup(name="test_group", signals=[sig1, sig2])
        assert len(pg.signals) == 2
        assert pg.plot_options.show_legend is True

    def test_assign_axes_single(self):
        sig = _make_signal()
        pg = PlotGroup.from_single_signal(sig)
        axes = pg.assign_axes()
        assert len(axes) == 1
        trace, secondary_y = axes[0]
        assert isinstance(trace, go.Scatter)

    def test_assign_axes_mixed_units(self):
        sig1 = _make_signal(raw_name="sig_a", unit="mmHg")
        sig2 = _make_signal(raw_name="sig_a", unit="mL")
        pg = PlotGroup(name="Mixed", signals=[sig1, sig2])
        axes = pg.assign_axes()
        secondary_flags = [sec for _, sec in axes]
        assert False in secondary_flags
        assert True in secondary_flags


# ---------------------------------------------------------------------------
# PlotModel
# ---------------------------------------------------------------------------


class TestPlotModel:
    def test_assign_plot_model_groups_by_type(self):
        sig_ts = _make_signal()
        pg_ts = PlotGroup.from_single_signal(sig_ts)

        models = PlotModel.assign_plot_model([pg_ts])
        assert len(models) == 1
        assert models[0].plot_type == "time_series"

    def test_assign_plot_model_time_series_first_even_if_loop_encountered_first(self):
        # Global grouping in wrapper.main appends global TS groups after loops and
        # removes the absorbed singles, so a loop can end up first in the list.
        # Page order must stay deterministic: time_series model before loop model.
        sig_x = _make_signal(raw_name="sig_x")
        sig_y = _make_signal(raw_name="sig_y")
        pg_loop = PlotGroup.from_single_signal(Signal.loop_from_signals(sig_x, sig_y, name="PV"))
        pg_ts = PlotGroup.from_single_signal(_make_signal())

        models = PlotModel.assign_plot_model([pg_loop, pg_ts])
        assert [m.plot_type for m in models] == ["time_series", "loop"]

    def test_to_figure_returns_go_figure(self):
        sig = _make_signal()
        pg = PlotGroup.from_single_signal(sig)
        model = PlotModel(groups=[pg])
        assert isinstance(model.figure, go.Figure)

    def test_figure_has_traces(self):
        sig = _make_signal()
        pg = PlotGroup.from_single_signal(sig)
        model = PlotModel(groups=[pg])
        assert len(model.figure.data) > 0

    def test_computed_height(self):
        sig = _make_signal()
        pg = PlotGroup.from_single_signal(sig)
        model = PlotModel(groups=[pg])
        assert model.computed_height is not None
        assert model.computed_height > 0

    def test_multiple_groups_multiple_subplots(self):
        sig1 = _make_signal(raw_name="sig_a", name="A")
        sig2 = _make_signal(raw_name="sig_a", name="B")
        pg1 = PlotGroup.from_single_signal(sig1)
        pg2 = PlotGroup.from_single_signal(sig2)
        model = PlotModel(groups=[pg1, pg2])
        # Should have 2 traces (one per group)
        assert len(model.figure.data) == 2


# ---------------------------------------------------------------------------
# Display fallbacks in the render layer — precedence (ADR-0005) and sizing
# ---------------------------------------------------------------------------


class TestSubplotHeightPrecedence:
    def test_user_height_fills_a_silent_config(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        assert pg.plot_options.plot_height is None  # nothing configured it

        PlotModel.assign_plot_model([pg], DisplayFallbacks(subplot_height=512))
        assert pg.plot_options.plot_height == 512

    def test_database_height_wins_over_user_height(self):
        """ADR-0005: where the database configuration speaks, it decides."""
        pg = PlotGroup.from_single_signal(_make_signal())
        pg.plot_options.plot_height = 250  # as set through source/database options

        PlotModel.assign_plot_model([pg], DisplayFallbacks(subplot_height=512))
        assert pg.plot_options.plot_height == 250

    def test_loop_height_is_separate_from_time_series_height(self):
        pg_ts = PlotGroup.from_single_signal(_make_signal())
        pg_loop = PlotGroup.from_single_signal(
            Signal.loop_from_signals(_make_signal(raw_name="x"), _make_signal(raw_name="y"))
        )

        PlotModel.assign_plot_model(
            [pg_ts, pg_loop], DisplayFallbacks(subplot_height=400, loop_subplot_height=800)
        )
        assert pg_ts.plot_options.plot_height == 400
        assert pg_loop.plot_options.plot_height == 800

    def test_figure_height_without_assign_plot_model(self):
        """A PlotModel built directly still sizes its subplots from its own carrier."""
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(groups=[pg], display_fallbacks=DisplayFallbacks(subplot_height=333))
        assert model.computed_height == 333


class TestColorwayPrecedence:
    def test_fallback_colorway_applied_to_layout(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(
            groups=[pg], display_fallbacks=DisplayFallbacks(colorway=cst.Colorway.TOL_MUTED)
        )
        assert list(model.figure.layout.colorway) == list(cst.Colorway.PALETTE_TOL_MUTED)

    def test_plotly_choice_leaves_colorway_unset(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(
            groups=[pg], display_fallbacks=DisplayFallbacks(colorway=cst.Colorway.PLOTLY)
        )
        assert model.figure.layout.colorway is None

    def test_per_signal_color_survives_the_fallback_palette(self):
        """A configured color stays on the trace; the colorway only paints uncolored traces."""
        df = _make_df(columns=["ART"])
        db_opts = {"signals": {"ART": {"color": "#123456"}}}
        sig = Signal.time_series_from_dataframe(df, "ART", database_options_specific=db_opts)
        model = PlotModel(
            groups=[PlotGroup.from_single_signal(sig)],
            display_fallbacks=DisplayFallbacks(colorway=cst.Colorway.OKABE_ITO),
        )
        assert model.figure.data[0].line.color == "#123456"


class TestHoverFallbacks:
    def test_y_significant_digits_applied(self):
        sig = _make_signal()
        assert "%{y:.4g}" in sig.trace.hovertemplate

        sig_six = Signal.time_series_from_dataframe(
            _make_df(columns=["sig_a"]),
            "sig_a",
            display_fallbacks=DisplayFallbacks(y_significant_digits=6),
        )
        assert "%{y:.6g}" in sig_six.trace.hovertemplate

    def test_per_signal_hover_template_wins(self):
        """A configured hover_template short-circuits the fallback branch entirely."""
        df = _make_df(columns=["ART"])
        db_opts = {"signals": {"ART": {"hover_template": "custom<extra></extra>"}}}
        sig = Signal.time_series_from_dataframe(
            df,
            "ART",
            database_options_specific=db_opts,
            display_fallbacks=DisplayFallbacks(y_significant_digits=6),
        )
        assert sig.trace.hovertemplate == "custom<extra></extra>"

    def test_hovermode_and_time_format_applied_to_time_series(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(
            groups=[pg],
            display_fallbacks=DisplayFallbacks(
                hovermode=cst.HoverMode.CLOSEST,
                hover_time_format=cst.HoverTimeFormat.DATE_TIME,
            ),
        )
        assert model.figure.layout.hovermode == "closest"
        assert model.figure.layout.xaxis.hoverformat == "%Y-%m-%d %H:%M:%S.%3f"

    def test_loops_keep_plotly_hovermode(self):
        loop = Signal.loop_from_signals(_make_signal(raw_name="x"), _make_signal(raw_name="y"))
        model = PlotModel(
            groups=[PlotGroup.from_single_signal(loop)],
            display_fallbacks=DisplayFallbacks(hovermode=cst.HoverMode.X_UNIFIED),
        )
        assert model.figure.layout.hovermode is None

    def test_spectrograms_keep_plotly_hovermode(self):
        spec = Signal.spectrogram_from_signal(
            _make_spectrogram_source_signal(), name="x", freq_range=(1.0, 30.0)
        )
        model = PlotModel(
            groups=[PlotGroup.from_single_signal(spec)],
            display_fallbacks=DisplayFallbacks(hovermode=cst.HoverMode.X_UNIFIED),
        )
        assert model.figure.layout.hovermode is None


class TestLayoutFallbacks:
    def test_template_applied(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(
            groups=[pg], display_fallbacks=DisplayFallbacks(template=cst.PlotTemplate.DARK)
        )
        # The dark template is identified by its near-black paper background.
        assert model.figure.layout.template.layout.paper_bgcolor == "rgb(17,17,17)"

    def test_legend_entry_width_capped_in_pixels(self):
        pg = PlotGroup.from_single_signal(_make_signal())
        model = PlotModel(groups=[pg], display_fallbacks=DisplayFallbacks(legend_entry_width=140))
        assert model.figure.layout.legend.entrywidth == 140
        assert model.figure.layout.legend.entrywidthmode == "pixels"


class TestLoopGrid:
    def _loop_groups(self, count):
        return [
            PlotGroup.from_single_signal(
                Signal.loop_from_signals(
                    _make_signal(raw_name="x"), _make_signal(raw_name="y"), name=f"loop_{index}"
                )
            )
            for index in range(count)
        ]

    def test_loops_per_row_drives_the_grid(self):
        groups = self._loop_groups(4)
        model = PlotModel.assign_plot_model(
            groups, DisplayFallbacks(loops_per_row=1, loop_subplot_height=200)
        )[0]
        # 4 loops in one column → 4 rows.
        assert model.computed_height == 4 * 200

    def test_three_per_row_packs_into_two_rows(self):
        groups = self._loop_groups(4)
        model = PlotModel.assign_plot_model(
            groups, DisplayFallbacks(loops_per_row=3, loop_subplot_height=200)
        )[0]
        assert model.computed_height == 2 * 200

    def test_loop_figure_width_follows_columns(self):
        groups = self._loop_groups(4)
        model = PlotModel.assign_plot_model(
            groups, DisplayFallbacks(loops_per_row=3, loop_subplot_height=200)
        )[0]
        assert model.figure.layout.width == 3 * 200

    def test_n_cols_exposes_the_grid_to_the_ui(self):
        """The UI maps traces to subplots with n_cols, so it must follow the setting."""
        model = PlotModel.assign_plot_model(
            self._loop_groups(4), DisplayFallbacks(loops_per_row=3)
        )[0]
        assert model.n_cols == 3

    def test_single_loop_stays_one_column(self):
        model = PlotModel.assign_plot_model(
            self._loop_groups(1), DisplayFallbacks(loops_per_row=3)
        )[0]
        assert model.n_cols == 1

    def test_time_series_is_always_one_column(self):
        model = PlotModel.assign_plot_model(
            [PlotGroup.from_single_signal(_make_signal(raw_name=name)) for name in ("a", "b")],
            DisplayFallbacks(loops_per_row=3),
        )[0]
        assert model.n_cols == 1


class TestSpectrogramFigure:
    def _spectrogram_groups(self, count):
        return [
            PlotGroup.from_single_signal(
                Signal.spectrogram_from_signal(
                    _make_spectrogram_source_signal(raw_name=f"eeg_{index}"),
                    name=f"spectrogram_{index}",
                    freq_range=(1.0, 30.0),
                )
            )
            for index in range(count)
        ]

    def test_stacks_in_one_column_like_time_series(self):
        model = PlotModel.assign_plot_model(self._spectrogram_groups(3))[0]
        assert model.n_cols == 1

    def test_colorbars_are_scoped_to_their_own_row(self):
        """Each heatmap's colorbar must fit its own subplot row, not span the whole figure."""
        model = PlotModel.assign_plot_model(self._spectrogram_groups(2))[0]
        colorbars = [trace.colorbar for trace in model.figure.data]
        assert len(colorbars) == 2
        # Stacked top-to-bottom: the first group's row sits above the second's.
        assert colorbars[0].y > colorbars[1].y
        for colorbar in colorbars:
            assert colorbar.len < 1.0

    def test_shares_x_axis_across_stacked_spectrograms(self):
        """Zooming one spectrogram should keep the others aligned, like time-series subplots."""
        model = PlotModel.assign_plot_model(self._spectrogram_groups(2))[0]
        assert model.figure.layout.xaxis2.matches == "x"


class TestPsdFigure:
    def _psd_group(self, name, signal_count):
        source = _make_spectrogram_source_signal(raw_name="eeg")
        return PlotGroup(
            name=name,
            signals=[
                Signal.psd_from_signal(source, psd_name=name, freq_range=(1.0, 30.0))
                for _ in range(signal_count)
            ],
            allow_secondary_y=False,
        )

    def test_overlaid_signals_share_one_subplot(self):
        model = PlotModel.assign_plot_model([self._psd_group("EEG PSD", 3)])[0]
        assert model.plot_type == "psd"
        assert len(model.figure.data) == 3
        assert all(isinstance(trace, go.Scatter) for trace in model.figure.data)

    def test_stacks_in_one_column(self):
        groups = [self._psd_group(f"psd_{index}", 1) for index in range(3)]
        assert PlotModel.assign_plot_model(groups)[0].n_cols == 1

    def test_does_not_share_x_axis_across_subplots(self):
        """Two psd entries may cover different bands, so linking their frequency axes is wrong."""
        groups = [self._psd_group(f"psd_{index}", 1) for index in range(2)]
        model = PlotModel.assign_plot_model(groups)[0]
        assert model.figure.layout.xaxis2.matches is None

    def test_keeps_plotly_hovermode(self):
        model = PlotModel(
            groups=[self._psd_group("EEG PSD", 1)],
            display_fallbacks=DisplayFallbacks(hovermode=cst.HoverMode.X_UNIFIED),
        )
        assert model.figure.layout.hovermode is None

    def test_page_order_puts_psd_between_spectrogram_and_loop(self):
        groups = [
            PlotGroup.from_single_signal(
                Signal.loop_from_signals(_make_signal(raw_name="x"), _make_signal(raw_name="y"))
            ),
            self._psd_group("EEG PSD", 1),
            PlotGroup.from_single_signal(_make_signal()),
        ]
        models = PlotModel.assign_plot_model(groups)
        assert [model.plot_type for model in models] == ["time_series", "psd", "loop"]


class TestToHtml:
    def test_skips_write_when_no_figures(self, tmp_path, caplog):
        # Regression: previously wrote an empty visualization.html — and needed
        # clinical_scope_output/ to already exist — even when nothing was plotted.
        patient_options = {cst.PatientOptions.PathDataFolder.NAME: str(tmp_path)}

        with caplog.at_level("WARNING"):
            PlotModel.to_html([], patient_options)

        assert not (tmp_path / "clinical_scope_output").exists()
        assert "no figures to write" in caplog.text


class TestPrintOutFigure:
    def test_cdn_export_references_the_cdn(self, tmp_path):
        sig = _make_signal()
        model = PlotModel(groups=[PlotGroup.from_single_signal(sig)])
        output = tmp_path / "viz.html"

        print_out_figure(output, [model.figure])
        content = output.read_text()
        assert 'src="https://cdn.plot.ly' in content

    def test_self_contained_export_embeds_plotly(self, tmp_path):
        sig = _make_signal()
        model = PlotModel(groups=[PlotGroup.from_single_signal(sig)])
        output = tmp_path / "viz.html"

        print_out_figure(output, [model.figure], self_contained=True)
        content = output.read_text()
        # No <script src=…>: the file must render on a machine with no network. (Remote URLs
        # inside the embedded bundle are fine — they are optional map tiles, not the library.)
        assert re.search(r"<script[^>]*\ssrc=", content) is None
        assert "Plotly.newPlot" in content
        # The whole bundle is inlined, so the file is megabytes rather than kilobytes.
        assert output.stat().st_size > 1_000_000

    def test_creates_missing_output_directory(self, tmp_path):
        # Regression: clinical_scope_output/ is normally created as a side effect of parquet
        # caching during data load. When 0 datasources produce any data (e.g. pointing the CLI
        # at a device subfolder instead of a patient folder), that side effect never runs, so
        # this must not assume the parent directory already exists.
        sig = _make_signal()
        model = PlotModel(groups=[PlotGroup.from_single_signal(sig)])
        output = tmp_path / "clinical_scope_output" / "viz.html"

        print_out_figure(output, [model.figure])
        assert output.exists()

    def test_bundle_embedded_once_for_several_figures(self, tmp_path):
        sig = _make_signal()
        figures = [
            PlotModel(groups=[PlotGroup.from_single_signal(_make_signal(raw_name="sig_a"))]).figure,
            PlotModel(groups=[PlotGroup.from_single_signal(sig)]).figure,
        ]
        one_figure = tmp_path / "one.html"
        two_figures = tmp_path / "two.html"

        print_out_figure(one_figure, figures[:1], self_contained=True)
        print_out_figure(two_figures, figures, self_contained=True)
        # The second figure adds its own data, not another copy of plotly.js.
        assert two_figures.stat().st_size - one_figure.stat().st_size < 500_000
