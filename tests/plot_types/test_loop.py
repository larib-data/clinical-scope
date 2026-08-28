"""The loop plot type: one signal against another, over their shared time grid."""

import numpy as np
import pandas as pd
import pytest

from clinical_scope.plot_types.loop.plot import loop_from_signals
from clinical_scope.signal_container import Signal


class TestLoopFromSignals:
    def test_basic_loop(self, make_signal):
        sig_x = make_signal(raw_name="sig_a", unit="cmH2O")
        sig_y = make_signal(raw_name="sig_a", name="Vol", unit="mL")
        loop = loop_from_signals(sig_x, sig_y, name="PV loop")
        assert loop.trace_options.plot_options.plot_type == "loop"
        assert loop.trace_options.plot_options.definition.GRID_LAYOUT is True
        assert loop.data.point_time_axis is not None
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
            loop_from_signals(sig_x, sig_y)

    def test_empty_signal_raises(self):
        # All-NaN column → empty after pruning
        df1 = pd.DataFrame(
            {"a": [np.nan, np.nan]},
            index=pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC"),
        )
        df2 = pd.DataFrame(
            {"b": [3.0, 4.0]},
            index=pd.date_range("2024-01-01", periods=2, freq="1s", tz="UTC"),
        )
        sig_x = Signal.time_series_from_dataframe(df1, "a")
        sig_y = Signal.time_series_from_dataframe(df2, "b")
        with pytest.raises(ValueError, match="no data"):
            loop_from_signals(sig_x, sig_y)
