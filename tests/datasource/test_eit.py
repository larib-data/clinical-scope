"""Tests for eit datasource — .asc parser, day parameter, percentage columns."""

import logging
import shutil

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ds_folder(patient_full_path, eit_cls):
    folder = eit_cls._find_folder(patient_full_path)
    if folder is None:
        pytest.skip("eit folder not found in demo_patient")
    return folder


@pytest.fixture(scope="module")
def loaded_df(ds_folder, eit_cls):
    file_path = eit_cls._find(ds_folder)
    assert file_path is not None
    return eit_cls._load(file_path)


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

    def test_load_percentage_columns(self, loaded_df):
        """%Local = Local / Global resolves no option, so _load derives it into the cache."""
        assert [column for column in loaded_df.columns if column.startswith("%Local")]


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, eit_cls, example_database_options):
    eit_db_opts = example_database_options.get("eit", {})
    return eit_cls._format(loaded_df, patient_options_full, eit_db_opts)


class TestFormat:
    """EIT _format() needs the 'day' parameter to build a proper DatetimeIndex."""

    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None

    def test_format_keeps_percentage_columns(self, formatted_df):
        """They arrive from _load; _format must carry them through, not drop them."""
        pct_cols = [c for c in formatted_df.columns if c.startswith("%Local")]
        assert len(pct_cols) > 0, "Expected percentage columns (e.g. %Local 1*)"


@pytest.fixture(scope="module")
def cache_path(loaded_df, eit_cls, tmp_path_factory):
    """The parquet cache exactly as _load writes it — the file quick-load reads back."""
    path = tmp_path_factory.mktemp("eit_cache") / "eit.parquet"
    eit_cls._save_dataframe(loaded_df, path)
    return path


class TestQuickLoadColumnPruning:
    """The cache's float64 index must not cost EIT its column pruning."""

    def test_reads_only_configured_columns(self, eit_cls, cache_path, example_database_options):
        eit_db_opts = example_database_options.get("eit", {})
        field_display = eit_db_opts["field_display"]
        full = pd.read_parquet(cache_path)
        expected = {
            column
            for column in full.columns
            for pattern in field_display
            if (column.startswith(pattern[:-1]) if pattern.endswith("*") else column == pattern)
        }

        out = eit_cls._quick_load(
            cache_path, patient_options=None, database_options_specific=eit_db_opts
        )

        assert set(out.columns) == expected
        assert len(out.columns) < len(full.columns)
        assert out.index.name == "Time"  # the axis survives without being selected
        pd.testing.assert_frame_equal(out, full[list(out.columns)])


@pytest.mark.snapshot
class TestSnapshot:
    """Content regression tests for EIT (uses example_database_options for _format)."""

    _DS = "eit"

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


class TestEmptyAndUnreadableFiles:
    """An empty file is skipped; a damaged one stops the load and is named."""

    @pytest.fixture
    def copied_folder(self, tmp_path, ds_folder):
        for path in sorted(ds_folder.glob("*.asc")):
            shutil.copy(path, tmp_path)
        return tmp_path

    def test_zero_byte_sibling_is_skipped(self, copied_folder, eit_cls, caplog):
        alone = eit_cls._load(eit_cls._find(copied_folder))
        (copied_folder / "07_PEEP_Trial_02.asc").touch()

        with caplog.at_level(logging.WARNING):
            df = eit_cls._load(eit_cls._find(copied_folder))

        pd.testing.assert_frame_equal(df, alone)
        assert "07_PEEP_Trial_02.asc" in caplog.text

    def test_garbage_sibling_raises_naming_it(self, copied_folder, eit_cls):
        (copied_folder / "07_PEEP_Trial_02.asc").write_text("not an EIT export\n")

        with pytest.raises(ValueError, match=r"07_PEEP_Trial_02\.asc"):
            eit_cls._load(eit_cls._find(copied_folder))

    def test_only_zero_byte_files_is_no_data(self, tmp_path, eit_cls, caplog):
        (tmp_path / "06_PEEP_Trial_01.asc").touch()

        with caplog.at_level(logging.WARNING):
            assert eit_cls._find(tmp_path) is None

        assert "06_PEEP_Trial_01.asc" in caplog.text
