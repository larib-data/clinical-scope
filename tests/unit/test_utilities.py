import numpy as np
import pandas as pd
import pytest

from clinical_data_visualizer.utilities import is_timestamp


class TestIsTimestamp:
    """Tests for utilities.is_timestamp()."""

    # --- True cases ---

    def test_pandas_timestamp(self):
        assert is_timestamp(pd.Timestamp("2024-01-15 10:30:00")) is True

    def test_pandas_timestamp_now(self):
        assert is_timestamp(pd.Timestamp.now()) is True

    def test_numpy_datetime64(self):
        assert is_timestamp(np.datetime64("2024-01-15")) is True

    def test_numpy_datetime64_with_time(self):
        assert is_timestamp(np.datetime64("2024-01-15T10:30:00")) is True

    def test_string_iso_date(self):
        assert is_timestamp("2024-01-15") is True

    def test_string_iso_datetime(self):
        assert is_timestamp("2024-01-15 10:30:00") is True

    def test_string_iso_datetime_with_tz(self):
        assert is_timestamp("2024-01-15T10:30:00+01:00") is True

    # --- False cases ---

    def test_integer(self):
        assert is_timestamp(42) is False

    def test_float(self):
        assert is_timestamp(3.14) is False

    def test_numeric_string_integer(self):
        """A string containing only digits must not be treated as a timestamp."""
        assert is_timestamp("20240115") is False

    def test_numeric_string_float(self):
        assert is_timestamp("1705312200.0") is False

    def test_none(self):
        assert is_timestamp(None) is False

    @pytest.mark.xfail(
        reason="pd.Timestamp('') returns NaT instead of raising, so '' is incorrectly treated as valid"  # noqa: E501
    )
    def test_empty_string(self):
        assert is_timestamp("") is False

    def test_random_string(self):
        assert is_timestamp("not-a-date") is False

    def test_list(self):
        assert is_timestamp([2024, 1, 15]) is False

    def test_dict(self):
        assert is_timestamp({"year": 2024}) is False
