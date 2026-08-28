"""Source time-series for the derived plot types to be built from."""

import numpy as np
import pandas as pd
import pytest

from clinical_scope.signal_container import Signal


@pytest.fixture
def make_signal():
    """A minimal time-series Signal, the input every derived plot type takes."""

    def _make(raw_name="sig_a", name=None, n=50, unit="mmHg"):
        idx = pd.date_range("2024-01-01", periods=n, freq="1s", tz="UTC")
        values = np.random.default_rng(42).standard_normal(n)
        df = pd.DataFrame({raw_name: values}, index=idx)
        db_opts = {
            "signals": {raw_name: {"label": name or raw_name, "unit": unit}},
            "field_display": [raw_name],
        }
        return Signal.time_series_from_dataframe(df, raw_name, database_options_specific=db_opts)

    return _make


@pytest.fixture
def make_spectral_source():
    """A time-series Signal sampled fast and long enough for a real spectral window."""

    def _make(raw_name="eeg", n=1280, sample_rate_hz=128.0, period_resampling=None):
        idx = pd.date_range("2024-01-01", periods=n, freq=f"{1000 / sample_rate_hz}ms", tz="UTC")
        values = np.sin(2 * np.pi * 10.0 * np.arange(n) / sample_rate_hz)
        df = pd.DataFrame({raw_name: values}, index=idx)
        db_opts = {}
        if period_resampling is not None:
            db_opts = {"numerics": {"period_resampling": period_resampling}}
        return Signal.time_series_from_dataframe(df, raw_name, database_options_specific=db_opts)

    return _make
