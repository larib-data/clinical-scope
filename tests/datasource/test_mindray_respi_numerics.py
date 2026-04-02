"""Tests for mindray_respi_numerics datasource — pivot from rows to columns."""

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, mindray_respi_numerics_cls):
    folder = mindray_respi_numerics_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("mindray_respi_numerics folder not found in Patient_full")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, mindray_respi_numerics_cls):
    file_path = mindray_respi_numerics_cls._find(ds_folder)
    assert file_path is not None
    return mindray_respi_numerics_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_file(self, ds_folder, mindray_respi_numerics_cls):
        result = mindray_respi_numerics_cls._find(ds_folder)
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
        """Pivot should produce one column per measurement_label."""
        assert len(loaded_df.columns) > 1


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, mindray_respi_numerics_cls):
    return mindray_respi_numerics_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None


class TestLoadCsv:
    def test_load_csv(self, patient_difficult_path, mindray_respi_numerics_cls):
        folder = mindray_respi_numerics_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("mindray_respi_numerics not in Patient_difficult")
        file_path = mindray_respi_numerics_cls._find(folder)
        if file_path is None:
            pytest.skip("No file found")
        df = mindray_respi_numerics_cls._load(file_path, None)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(df.index, pd.DatetimeIndex)


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "mindray_respi_numerics"

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
