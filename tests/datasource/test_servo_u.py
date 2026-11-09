"""Tests for servo_u datasource — multi-file .sta binary format."""

import logging
import shutil

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
    return servo_u_cls._load(file_path)


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


class TestEmptyAndUnreadableFiles:
    """An empty file is skipped; a damaged one stops the load and is named."""

    @pytest.fixture
    def copied_folder(self, tmp_path, ds_folder):
        for path in sorted(ds_folder.glob("*.sta")):
            shutil.copy(path, tmp_path)
        return tmp_path

    def test_zero_byte_sibling_is_skipped(self, copied_folder, servo_u_cls, caplog):
        alone = servo_u_cls._load(servo_u_cls._find(copied_folder))
        (copied_folder / "Curves_00000003.sta").touch()

        with caplog.at_level(logging.WARNING):
            df = servo_u_cls._load(servo_u_cls._find(copied_folder))

        pd.testing.assert_frame_equal(df, alone)
        assert "Curves_00000003.sta" in caplog.text

    def test_garbage_sibling_raises_naming_it(self, copied_folder, servo_u_cls):
        (copied_folder / "Curves_00000003.sta").write_text("not a servo export\n")

        with pytest.raises(ValueError, match=r"Curves_00000003\.sta"):
            servo_u_cls._load(servo_u_cls._find(copied_folder))

    def test_only_zero_byte_files_is_no_data(self, tmp_path, servo_u_cls, caplog):
        (tmp_path / "Curves_00000000.sta").touch()
        (tmp_path / "Curves_00000001.sta").touch()

        with caplog.at_level(logging.WARNING):
            assert servo_u_cls._find(tmp_path) is None

        assert "all empty" in caplog.text

    def test_zero_byte_header_file_names_the_next_file(self, copied_folder, servo_u_cls):
        (copied_folder / "Curves_00000000.sta").write_bytes(b"")

        with pytest.raises(ValueError, match=r"Curves_00000001\.sta.*header"):
            servo_u_cls._load(servo_u_cls._find(copied_folder))
