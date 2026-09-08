"""Tests for icca datasource — long-format pivot from rows to columns by attributeId."""

import logging
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

    def test_load_index_is_naive(self, loaded_df):
        """_load writes the parquet cache; localizing here would freeze UTC into it."""
        assert loaded_df.index.tz is None


@pytest.fixture(scope="module")
def formatted_df(loaded_df, patient_options_full, icca_cls):
    return icca_cls._format(loaded_df, patient_options_full, {})


class TestFormat:
    def test_format_preserves_index_type(self, formatted_df):
        assert isinstance(formatted_df.index, pd.DatetimeIndex)

    def test_format_has_timezone(self, formatted_df):
        assert formatted_df.index.tz is not None

    def test_format_localizes_to_utc(self, formatted_df):
        assert str(formatted_df.index.tz) == "UTC"

    def test_format_applies_timezone_override(self, loaded_df, patient_options_full, icca_cls):
        """
        The override still reaches the data because _load left the index naive.

        Reading the naive stamps as Paris wall-clock time instead of UTC moves every
        instant back by that September day's offset (CEST, UTC+2).
        """
        database_options = {"additional_informations": {"timezone": "Europe/Paris"}}
        default = icca_cls._format(loaded_df, patient_options_full, {})
        overridden = icca_cls._format(loaded_df, patient_options_full, database_options)
        assert overridden.index[0] == default.index[0] - pd.Timedelta(hours=2)

    def test_format_warns_on_non_utc_override(
        self, loaded_df, patient_options_full, icca_cls, caplog
    ):
        """utcmeasurementTime is UTC by construction, so an override shifts every stamp."""
        database_options = {"additional_informations": {"timezone": "Europe/Paris"}}
        with caplog.at_level(logging.WARNING):
            icca_cls._format(loaded_df, patient_options_full, database_options)
        assert "Europe/Paris" in caplog.text

    def test_format_silent_on_utc_override(
        self, loaded_df, patient_options_full, icca_cls, caplog
    ):
        database_options = {"additional_informations": {"timezone": "UTC"}}
        with caplog.at_level(logging.WARNING):
            icca_cls._format(loaded_df, patient_options_full, database_options)
        assert "Timezone override" not in caplog.text


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


def _write_export(path, rows, delimiter=","):
    """Write a minimal long-format ICCA export."""
    pd.DataFrame(rows).to_csv(path, index=False, sep=delimiter)
    return path


def _numeric_rows(count, attribute_id=2423):
    return [
        {
            "utcmeasurementTime": f"2004-09-15 08:{minute:02d}:00.000000",
            "attributeId": attribute_id,
            "valueNumber": 80.0 + minute,
            "valueString": "",
        }
        for minute in range(count)
    ]


class TestExtensions:
    """ICCA exports CSV; other extensions must fail by name, not silently."""

    def test_parquet_raises_value_error(self, tmp_path, icca_cls):
        path = tmp_path / "export.parquet"
        path.touch()
        with pytest.raises(ValueError, match="not an ICCA export format"):
            icca_cls._load(path, None)

    @pytest.mark.parametrize("suffix", [".xml", ".json"])
    def test_planned_format_raises_not_implemented(self, tmp_path, icca_cls, suffix):
        path = tmp_path / f"export{suffix}"
        path.touch()
        with pytest.raises(NotImplementedError):
            icca_cls._load(path, None)


class TestEmptyExport:
    @staticmethod
    def _header_only(path):
        columns = ["utcmeasurementTime", "attributeId", "valueNumber"]
        pd.DataFrame(columns=columns).to_csv(path, index=False)
        return path

    def test_empty_export_returns_naive_empty_index(self, tmp_path, icca_cls):
        """A header-only export must not hand back a localized index _format would keep."""
        df = icca_cls._load(self._header_only(tmp_path / "icca.csv"), None)
        assert df.empty
        assert df.index.tz is None

    def test_empty_export_still_formats(self, tmp_path, icca_cls, patient_options_full):
        loaded = icca_cls._load(self._header_only(tmp_path / "icca.csv"), None)
        formatted = icca_cls._format(loaded, patient_options_full, {})
        assert str(formatted.index.tz) == "UTC"


class TestDelimiter:
    def test_semicolon_export_loads(self, tmp_path, icca_cls):
        """Excel re-saves a comma export as semicolon-separated without renaming it."""
        path = _write_export(tmp_path / "icca.csv", _numeric_rows(6), delimiter=";")
        df = icca_cls._load(path, None)
        assert list(df.columns) == ["2423"]
        assert len(df) == 6


class TestDataLossReporting:
    def test_collapsed_duplicates_are_reported(self, ds_folder, icca_cls, caplog):
        """The demo export collides on 125 of its 500 measurements."""
        file_path = icca_cls._find(ds_folder)
        with caplog.at_level(logging.WARNING):
            icca_cls._load(file_path, None)
        assert "only the first of each is kept" in caplog.text

    def test_no_duplicate_warning_when_unique(self, tmp_path, icca_cls, caplog):
        path = _write_export(tmp_path / "icca.csv", _numeric_rows(6))
        with caplog.at_level(logging.WARNING):
            icca_cls._load(path, None)
        assert "only the first of each is kept" not in caplog.text

    def test_non_numeric_attribute_is_reported(self, tmp_path, icca_cls, caplog):
        """A text-valued attributeId pivots to all-NaN and is then dropped entirely."""
        rows = _numeric_rows(4)
        rows += [
            {
                "utcmeasurementTime": f"2004-09-15 08:{minute:02d}:00.000000",
                "attributeId": 9999,
                "valueNumber": "",
                "valueString": "Awake",
            }
            for minute in range(4)
        ]
        path = _write_export(tmp_path / "icca.csv", rows)
        with caplog.at_level(logging.WARNING):
            df = icca_cls._load(path, None)
        assert "9999" in caplog.text
        assert "valueString" in caplog.text
        assert "9999" not in df.columns
