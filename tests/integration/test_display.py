"""Integration tests for Signal→PlotGroup→PlotModel→to_figure() with real data."""

import numpy as np
import plotly.graph_objects as go
import pytest

from clinical_data_visualizer.signal_container import PlotGroup, PlotModel, Signal


@pytest.fixture(scope="module")
def philips_waves_df(patient_full_path):
    """Load philips_waves data for signal creation tests."""
    from clinical_data_visualizer.datasource.registry import DataSource

    ds_cls = DataSource.PhilipsWaves.DATASOURCE_CLASS
    patient_opts = {
        "data_folder": str(patient_full_path),
        "quick_load": False,
        "datetime_start": None,
        "datetime_end": None,
    }
    return ds_cls.extract(patient_opts, {})


class TestSignalFromRealData:
    def test_signal_creation(self, philips_waves_df):
        # Pick the first available column
        col = philips_waves_df.columns[0]
        sig = Signal.time_series_from_dataframe(philips_waves_df, col)
        assert sig.raw_name == col
        assert isinstance(sig.data.x, np.ndarray)
        assert isinstance(sig.data.y, np.ndarray)
        assert len(sig.data.x) > 0
        assert isinstance(sig.trace, go.Scatter)

    def test_signal_with_db_options(self, philips_waves_df, example_database_options):
        """Test that database_options (label, unit, etc.) are applied to a real signal."""
        db_opts = example_database_options.get("philips_waves", {})
        field_display = db_opts.get("field_display", [])
        # Find a configured signal that actually exists in the data
        actual_cols = set(philips_waves_df.columns)
        col = next((f for f in field_display if f in actual_cols), None)
        if col is None:
            pytest.skip("No configured signal found in actual data columns")
        sig = Signal.time_series_from_dataframe(
            philips_waves_df, col, database_options_specific=db_opts
        )
        sig_config = db_opts.get("signals", {}).get(col, {})
        expected_label = sig_config.get("label", col)
        assert sig.name == expected_label


class TestPlotGroupFromRealData:
    def test_single_signal_group(self, philips_waves_df):
        col = philips_waves_df.columns[0]
        sig = Signal.time_series_from_dataframe(philips_waves_df, col)
        pg = PlotGroup.from_single_signal(sig)
        assert len(pg.signals) == 1
        assert pg.plot_options is not None

    def test_multi_signal_group(self, philips_waves_df):
        cols = [c for c in philips_waves_df.columns if not philips_waves_df[c].isna().all()][:2]
        if len(cols) < 2:
            pytest.skip("Need at least 2 non-NaN columns")
        sigs = [Signal.time_series_from_dataframe(philips_waves_df, c) for c in cols]
        pg = PlotGroup(name="TestGroup", signals=sigs)
        assert len(pg.signals) == 2
        axes = pg.assign_axes()
        assert len(axes) == 2


class TestPlotModelFromRealData:
    def test_to_figure(self, philips_waves_df):
        cols = [c for c in philips_waves_df.columns if not philips_waves_df[c].isna().all()][:2]
        if not cols:
            pytest.skip("No non-NaN columns")
        groups = [
            PlotGroup.from_single_signal(Signal.time_series_from_dataframe(philips_waves_df, c))
            for c in cols
        ]
        model = PlotModel(groups=groups)
        assert isinstance(model.figure, go.Figure)
        assert len(model.figure.data) == len(cols)
        assert model.computed_height > 0


class TestLoopFromRealData:
    def test_loop_creation(self, philips_waves_df, example_database_options):
        """Create a loop from two real columns (using actual data columns, not config)."""
        db_opts = example_database_options.get("philips_waves", {})
        # Use actual non-NaN columns for the loop, not config names (synthetic data may differ)
        non_nan_cols = [c for c in philips_waves_df.columns if not philips_waves_df[c].isna().all()]
        if len(non_nan_cols) < 2:
            pytest.skip("Need at least 2 non-NaN columns for loop")
        x_name, y_name = non_nan_cols[0], non_nan_cols[1]

        sig_x = Signal.time_series_from_dataframe(
            philips_waves_df, x_name, database_options_specific=db_opts
        )
        sig_y = Signal.time_series_from_dataframe(
            philips_waves_df, y_name, database_options_specific=db_opts
        )
        try:
            loop = Signal.loop_from_signals(sig_x, sig_y, name="PV loop")
        except ValueError as exc:
            pytest.skip(f"Columns have no overlapping data for a loop: {exc}")
        assert loop.trace_options.plot_options.plot_type == "loop"
        assert loop.trace_options.plot_options.square_plot is True
        assert loop.data.loop_time_axis is not None
        assert len(loop.data.x) > 0
