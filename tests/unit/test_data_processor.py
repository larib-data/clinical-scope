"""
Unit tests for the data-extraction layer.

Covers:
- DataSourceBase.extract()         (datasource_base.py)
- wrapper.extract_datasource()     (wrapper.py)
- wrapper.extract_patient()        (wrapper.py)
- wrapper.batch_extract()          (wrapper.py)
- helper.save_df()                 (helper.py)
- datasource_list.detect_datasource_from_folder()  (datasource_list.py)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from clinical_data_visualizer import wrapper
from clinical_data_visualizer.datasource_list import detect_datasource_from_folder
from clinical_data_visualizer.io.file_utils import save_df

# ==================================================================================================
# Helpers
# ==================================================================================================


def _make_df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=3, freq="1s", tz="UTC")
    return pd.DataFrame({"col_a": [1.0, 2.0, 3.0], "col_b": [4.0, 5.0, 6.0]}, index=idx)


def _make_datasource_cls(name: str = "test_source") -> MagicMock:
    cls = MagicMock()
    cls.DATASOURCE_NAME = name
    return cls


def _make_ds_entry(name: str, cls, keywords: list[str]) -> MagicMock:
    entry = MagicMock()
    entry.NAME = name
    entry.DATASOURCE_CLASS = cls
    entry.OPTIONS.FOLDER_KEYWORDS = keywords
    return entry


# ==================================================================================================
# helper.save_df
# ==================================================================================================


class TestSaveDf:
    def test_saves_parquet(self, tmp_path):
        df = _make_df()
        path = tmp_path / "out.parquet"
        save_df(df, path)
        assert path.exists()
        assert len(pd.read_parquet(path)) == 3

    def test_saves_csv(self, tmp_path):
        df = _make_df()
        path = tmp_path / "out.csv"
        save_df(df, path)
        assert path.exists()
        assert "col_a" in pd.read_csv(path, index_col=0).columns

    def test_raises_on_unknown_extension(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported file format"):
            save_df(_make_df(), tmp_path / "out.xlsx")

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "subdir" / "deep" / "out.parquet"
        save_df(_make_df(), path)
        assert path.exists()


# ==================================================================================================
# datasource_list.detect_datasource_from_folder
# ==================================================================================================


class TestDetectDatasourceFromFolder:
    @patch("clinical_data_visualizer.datasource_list.DataSource")
    def test_matches_by_keywords(self, mock_ds):
        ds_entry = _make_ds_entry("philips_waves", MagicMock(), ["philips", "waves"])
        mock_ds.AVAILABLE = [ds_entry]
        result = detect_datasource_from_folder(Path("/data/patient/philips_waves"))
        assert result is ds_entry

    @patch("clinical_data_visualizer.datasource_list.DataSource")
    def test_no_match_returns_none(self, mock_ds):
        ds_entry = _make_ds_entry("philips_waves", MagicMock(), ["philips", "waves"])
        mock_ds.AVAILABLE = [ds_entry]
        result = detect_datasource_from_folder(Path("/data/patient/unknown_folder"))
        assert result is None

    @patch("clinical_data_visualizer.datasource_list.DataSource")
    def test_matching_is_case_insensitive(self, mock_ds):
        ds_entry = _make_ds_entry("eit", MagicMock(), ["eit"])
        mock_ds.AVAILABLE = [ds_entry]
        result = detect_datasource_from_folder(Path("/data/patient/EIT_Data"))
        assert result is ds_entry


# ==================================================================================================
# DataSourceBase.extract
# ==================================================================================================


class TestDataSourceBaseExtract:
    """Tests for DataSourceBase.extract() via a mock subclass."""

    def _make_cls(self, name="ds_a"):
        from clinical_data_visualizer.datasource_base import DataSourceBase

        # Build a minimal concrete subclass on-the-fly
        cls = MagicMock(spec=DataSourceBase)
        cls.DATASOURCE_NAME = name
        return cls

    def test_extract_datasource_success(self):
        from clinical_data_visualizer.datasource_base import DataSourceBase

        cls = _make_datasource_cls()
        df = _make_df()
        cls._load_raw_dataframe.return_value = (df, "/file")
        cls._format.return_value = df

        # Call the real extract() bound to our mock class
        result = DataSourceBase.extract.__func__(cls, {"data_folder": "/p"}, {})

        assert result is not None
        assert list(result.columns) == ["col_a", "col_b"]

    def test_extract_datasource_file_not_found(self):
        from clinical_data_visualizer.datasource_base import DataSourceBase

        cls = _make_datasource_cls()
        cls._load_raw_dataframe.return_value = (None, None)

        result = DataSourceBase.extract.__func__(cls, {"data_folder": "/p"}, {})
        assert result is None
        cls._format.assert_not_called()

    def test_extract_datasource_saves_parquet(self, tmp_path):
        from clinical_data_visualizer.datasource_base import DataSourceBase

        cls = _make_datasource_cls()
        df = _make_df()
        cls._load_raw_dataframe.return_value = (df, "/file")
        cls._format.return_value = df

        save_path = tmp_path / "out.parquet"
        DataSourceBase.extract.__func__(cls, {"data_folder": "/p"}, {}, save_path=save_path)

        assert save_path.exists()


# ==================================================================================================
# wrapper.extract_patient
# ==================================================================================================


class TestExtractPatient:
    @patch("clinical_data_visualizer.wrapper.datasource_list")
    @patch("clinical_data_visualizer.wrapper.warn_redundant_entries")
    def test_extract_patient_processes_both_datasources(self, mock_warn, mock_ds_list):
        df = _make_df()

        cls_a = _make_datasource_cls("ds_a")
        cls_a.extract.return_value = df
        cls_b = _make_datasource_cls("ds_b")
        cls_b.extract.return_value = df

        mock_ds_list.DataSource.AVAILABLE = [
            _make_ds_entry("ds_a", cls_a, ["ds_a"]),
            _make_ds_entry("ds_b", cls_b, ["ds_b"]),
        ]

        results = wrapper.extract_patient(
            Path("/p"),
            {"ds_a": {}, "ds_b": {}},
        )

        assert results["ds_a"] is not None
        assert results["ds_b"] is not None

    @patch("clinical_data_visualizer.wrapper.datasource_list")
    @patch("clinical_data_visualizer.wrapper.warn_redundant_entries")
    def test_extract_patient_saves_to_folder(self, mock_warn, mock_ds_list, tmp_path):
        df = _make_df()

        cls_a = _make_datasource_cls("ds_a")
        cls_a.extract.return_value = df

        mock_ds_list.DataSource.AVAILABLE = [_make_ds_entry("ds_a", cls_a, ["ds_a"])]

        wrapper.extract_patient(Path("/p"), {"ds_a": {}}, save_folder=tmp_path)

        # extract() must have been called with the correct save_path
        cls_a.extract.assert_called_once()
        _, kwargs = cls_a.extract.call_args
        assert kwargs.get("save_path") == tmp_path / "ds_a.parquet"

    @patch("clinical_data_visualizer.wrapper.datasource_list")
    @patch("clinical_data_visualizer.wrapper.warn_redundant_entries")
    def test_extract_patient_sets_data_folder_from_arg(self, mock_warn, mock_ds_list):
        """patient_folder is always injected as data_folder, overriding patient_options."""
        df = _make_df()

        cls_a = _make_datasource_cls("ds_a")
        cls_a.extract.return_value = df

        mock_ds_list.DataSource.AVAILABLE = [_make_ds_entry("ds_a", cls_a, ["ds_a"])]

        wrapper.extract_patient(
            Path("/correct_folder"),
            {"ds_a": {}},
            patient_options={"data_folder": "/should_be_ignored"},
        )

        cls_a.extract.assert_called_once()
        passed_opts = cls_a.extract.call_args[0][0]
        assert passed_opts["data_folder"] == "/correct_folder"

    @patch("clinical_data_visualizer.wrapper.datasource_list")
    @patch("clinical_data_visualizer.wrapper.warn_redundant_entries")
    def test_extract_patient_none_database_options_uses_all_datasources(
        self, mock_warn, mock_ds_list
    ):
        """database_options_global=None → all AVAILABLE datasources are processed."""
        df = _make_df()

        cls_a = _make_datasource_cls("ds_a")
        cls_a.extract.return_value = df
        cls_b = _make_datasource_cls("ds_b")
        cls_b.extract.return_value = df

        entry_a = _make_ds_entry("ds_a", cls_a, ["ds_a"])
        entry_b = _make_ds_entry("ds_b", cls_b, ["ds_b"])
        mock_ds_list.DataSource.AVAILABLE = [entry_a, entry_b]

        # generate_default_database_options returns defaults for all available sources
        mock_ds_list.generate_default_database_options.return_value = {"ds_a": {}, "ds_b": {}}

        results = wrapper.extract_patient(Path("/p"), None)

        assert "ds_a" in results
        assert "ds_b" in results


# ==================================================================================================
# wrapper.batch_extract
# ==================================================================================================


class TestBatchExtract:
    @patch("clinical_data_visualizer.wrapper.extract_patient")
    def test_batch_extract_from_list(self, mock_extract):
        mock_extract.return_value = {"ds_a": _make_df()}

        result = wrapper.batch_extract(
            [Path("/data/PatientA"), Path("/data/PatientB")],
            {"ds_a": {}},
        )

        assert mock_extract.call_count == 2
        assert "PatientA" in result
        assert "PatientB" in result

    @patch("clinical_data_visualizer.wrapper.extract_patient")
    def test_batch_extract_from_root_dir(self, mock_extract, tmp_path):
        (tmp_path / "P01").mkdir()
        (tmp_path / "P02").mkdir()
        mock_extract.return_value = {}

        result = wrapper.batch_extract(tmp_path, {})

        assert mock_extract.call_count == 2
        assert "P01" in result
        assert "P02" in result

    @patch("clinical_data_visualizer.wrapper.extract_patient")
    def test_batch_extract_exception_isolated(self, mock_extract):
        mock_extract.side_effect = [RuntimeError("boom"), {"ds_a": _make_df()}]

        result = wrapper.batch_extract(
            [Path("/data/PatientA"), Path("/data/PatientB")],
            {"ds_a": {}},
        )

        assert result["PatientA"] == {}
        assert result["PatientB"] is not None


# ==================================================================================================
# wrapper.main / wrapper.inspect — None database_options_global
# ==================================================================================================


class TestMainAndInspectDefaults:
    @patch("clinical_data_visualizer.wrapper.datasource_list")
    def test_main_none_database_options_uses_defaults(self, mock_ds_list):
        """main(patient_options, None) resolves to generate_default_database_options()."""
        mock_ds_list.generate_default_database_options.return_value = {}
        mock_ds_list.DataSource.AVAILABLE = []

        result = wrapper.main({"data_folder": "/p"}, None)

        mock_ds_list.generate_default_database_options.assert_called_once()
        assert result == []

    @patch("clinical_data_visualizer.wrapper.datasource_list")
    def test_inspect_none_database_options_uses_defaults(self, mock_ds_list):
        """inspect(patient_options, None) resolves to generate_default_database_options()."""
        mock_ds_list.generate_default_database_options.return_value = {}
        mock_ds_list.DataSource.AVAILABLE = []

        result = wrapper.inspect({"data_folder": "/p"}, None)

        mock_ds_list.generate_default_database_options.assert_called_once()
        assert result == []
