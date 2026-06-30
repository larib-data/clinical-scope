"""Tests for icca datasource — long-format pivot from rows to columns by attributeId."""

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, icca_cls):
    folder = icca_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("icca folder not found in demo_patient")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, icca_cls):
    file_path = icca_cls._find(ds_folder)
    assert file_path is not None
    return icca_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_file(self, ds_folder, icca_cls):
        result = icca_cls._find(ds_folder)
        assert isinstance(result, Path)
        assert result.is_file()


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_datetime_index(self, loaded_df):
        assert isinstance(loaded_df.index, pd.DatetimeIndex)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0

    def test_load_multiple_columns(self, loaded_df):
        """Pivot should produce one column per attributeId."""
        assert len(loaded_df.columns) > 1

    def test_load_columns_are_string_attribute_ids(self, loaded_df):
        """Raw signal names are the stringified attributeId integers."""
        assert all(isinstance(c, str) for c in loaded_df.columns)
        assert all(c.isdigit() for c in loaded_df.columns)

    def test_load_index_sorted_and_unique(self, loaded_df):
        assert loaded_df.index.is_monotonic_increasing
        assert loaded_df.index.is_unique


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, icca_cls):
    return icca_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "icca"

    def test_loaded_snapshot(self, loaded_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            loaded_df, SNAPSHOT_DIR / self._DS / "loaded.parquet", update=update_snapshots
        )

    def test_formatted_snapshot(self, formatted_df, update_snapshots):
        from tests.conftest import SNAPSHOT_DIR, assert_or_update_snapshot

        assert_or_update_snapshot(
            formatted_df, SNAPSHOT_DIR / self._DS / "formatted.parquet", update=update_snapshots
        )
