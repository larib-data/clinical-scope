"""Tests for eit datasource — .asc parser, day parameter, percentage columns."""

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, eit_cls):
    folder = eit_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("eit folder not found in Patient_full")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, eit_cls):
    file_path = eit_cls._find(ds_folder)
    assert file_path is not None
    return eit_cls._load(file_path, None)


class TestFind:
    def test_find_folder_returns_path(self, ds_folder):
        assert ds_folder.is_dir()

    def test_find_returns_list(self, ds_folder, eit_cls):
        """Eit is MULTI_FILE — _find() should return a list."""
        result = eit_cls._find(ds_folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extension(self, ds_folder, eit_cls):
        result = eit_cls._find(ds_folder)
        for p in result:
            assert p.suffix == ".asc"


class TestLoad:
    def test_load_returns_dataframe(self, loaded_df):
        assert isinstance(loaded_df, pd.DataFrame)

    def test_load_nonempty(self, loaded_df):
        assert len(loaded_df) > 0

    def test_load_has_columns(self, loaded_df):
        assert len(loaded_df.columns) >= 1


class TestFormat:
    """EIT _format() needs the 'day' parameter to build a proper DatetimeIndex."""

    @pytest.fixture(scope="class")
    def formatted_df(self, loaded_df, patient_options_full, eit_cls, example_database_options):
        eit_db_opts = example_database_options.get("eit", {})
        return eit_cls._format(loaded_df, patient_options_full, eit_db_opts)

    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None

    def test_format_percentage_columns(self, formatted_df):
        """_format() should create %Local columns from Local columns."""
        pct_cols = [c for c in formatted_df.columns if c.startswith("%")]
        assert len(pct_cols) > 0, "Expected percentage columns (e.g. %Local 1*)"


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests for EIT (uses example_database_options for _format)."""

    _DS = "eit"

    @pytest.fixture(scope="class")
    def formatted_df(self, loaded_df, patient_options_full, eit_cls, example_database_options):
        eit_db_opts = example_database_options.get("eit", {})
        return eit_cls._format(loaded_df, patient_options_full, eit_db_opts)

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
