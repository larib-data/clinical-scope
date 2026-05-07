"""Tests for servo_u datasource — multi-file .sta binary format."""

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, servo_u_cls):
    folder = servo_u_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("servo_u folder not found in demo_patient")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, servo_u_cls):
    file_path = servo_u_cls._find(ds_folder)
    assert file_path is not None
    return servo_u_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_list(self, ds_folder, servo_u_cls):
        """servo_u is MULTI_FILE — _find() should return a list."""
        result = servo_u_cls._find(ds_folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extension(self, ds_folder, servo_u_cls):
        result = servo_u_cls._find(ds_folder)
        for p in result:
            assert p.suffix == ".sta"


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_datetime_index(self, loaded_df):
        assert isinstance(loaded_df.index, pd.DatetimeIndex)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0

    def test_load_has_columns(self, loaded_df):
        assert len(loaded_df.columns) >= 1

    def test_load_sorted_index(self, loaded_df):
        assert loaded_df.index.is_monotonic_increasing


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, servo_u_cls):
    return servo_u_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests — compare against golden parquet files."""

    _DS = "servo_u"

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
