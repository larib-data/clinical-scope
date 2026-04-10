"""Unit tests for signal_container.py — Signal, PlotGroup, PlotModel."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from clinical_data_visualizer.signal_container import (
    PlotGroup,
    PlotModel,
    PlotOptions,
    Signal,
    compute_average_priority,
    get_unique_or_raise,
    merge_y_ranges,
)

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
        # Create two signals with non-overlapping time ranges
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
        # One should be primary (False), one secondary (True)
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
