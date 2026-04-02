"""Tests for fluxmed_parameters datasource — filename timestamp extraction."""

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, fluxmed_parameters_cls):
    folder = fluxmed_parameters_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("fluxmed_parameters folder not found in Patient_full")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, fluxmed_parameters_cls):
    file_path = fluxmed_parameters_cls._find(ds_folder)
    assert file_path is not None
    return fluxmed_parameters_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_file(self, ds_folder, fluxmed_parameters_cls):
        result = fluxmed_parameters_cls._find(ds_folder)
        assert isinstance(result, Path)
        assert result.is_file()

    def test_find_correct_extension(self, ds_folder, fluxmed_parameters_cls):
        result = fluxmed_parameters_cls._find(ds_folder)
        assert result.suffix in (".parquet", ".txt", ".csv")


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_datetime_index(self, loaded_df):
        assert isinstance(loaded_df.index, pd.DatetimeIndex)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0


class TestFormat:
    @pytest.fixture(scope="class")
    def formatted_df(self, loaded_df, patient_options_full, fluxmed_parameters_cls):
        return fluxmed_parameters_cls._format(loaded_df, patient_options_full, {})

    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "fluxmed_parameters"

    @pytest.fixture(scope="class")
    def formatted_df(self, loaded_df, patient_options_full, fluxmed_parameters_cls):
        return fluxmed_parameters_cls._format(loaded_df, patient_options_full, {})

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
