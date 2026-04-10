"""
Tests for other (generic) datasource — auto datetime detection, per-file grouping.

The 'other' datasource only exists in Patient_difficult_format, not Patient_full.
It has a custom main() that processes files individually rather than using _load().
"""

import pytest


class TestFind:
    def test_find_folder_returns_path(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        assert folder is not None
        assert folder.is_dir()

    def test_find_returns_list(self, patient_difficult_path, other_cls):
        """Other is MULTI_FILE — _find() should return a list."""
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extensions(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        for p in result:
            assert p.suffix in (".csv", ".parquet")


class TestMainPipeline:
    """The 'other' datasource has a custom main() — test the full pipeline."""

    def test_main_returns_signals(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_data_visualizer.datasource_list import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        assert isinstance(signals, list)
        assert len(signals) > 0

    def test_main_signals_have_data(self, patient_difficult_path):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_data_visualizer.datasource_list import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        for sig in signals:
            assert sig.data.x is not None
            assert sig.data.y is not None
            assert len(sig.data.x) > 0


class TestExtract:
    """The 'other' datasource does not support extract() — each file is its own signal group."""

    def test_extract_returns_none(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        df = other_cls.extract(patient_options, {})
        assert df is None, (
            "other.extract() must return None (multi-file datasource has no single-DataFrame representation)"
        )
