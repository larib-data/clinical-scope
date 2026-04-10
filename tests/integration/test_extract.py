"""Integration tests for wrapper.extract_patient(), extract_datasource(), batch_extract()."""

import pandas as pd
import pytest

from clinical_data_visualizer.wrapper import batch_extract, extract_datasource, extract_patient


class TestExtractDatasource:
    def test_extract_philips_waves(self, patient_full_path):
        folder = patient_full_path / "philips_waves"
        df = extract_datasource(folder)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_extract_nonexistent_folder(self, tmp_path):
        result = extract_datasource(tmp_path / "nonexistent")
        assert result is None


class TestExtractPatient:
    @pytest.fixture(scope="class")
    def extract_results(self, patient_full_path, default_database_options):
        return extract_patient(patient_full_path, default_database_options)

    def test_returns_dict(self, extract_results):
        assert isinstance(extract_results, dict)

    def test_has_datasource_keys(self, extract_results, default_database_options):
        assert set(extract_results.keys()) == set(default_database_options.keys())

    def test_successful_extractions(self, extract_results):
        """
        Most datasources should extract successfully.

        Expected failures (by design, not bugs):
        - 'other': extract() always returns None (multi-file datasource, use main() instead)
        Patient_full has 10 datasource folders, so >= 9 successes is the realistic target
        when all folders load cleanly. Threshold is set to 8 to tolerate one unexpected failure.
        """
        successes = sum(1 for v in extract_results.values() if v is not None)
        assert successes >= 9, f"Only {successes} extractions succeeded (expected >= 9)"

    def test_dataframes_are_valid(self, extract_results):
        for name, df in extract_results.items():
            if df is not None:
                assert isinstance(df, pd.DataFrame), f"{name} is not a DataFrame"
                assert len(df) > 0, f"{name} is empty"

    def test_save_to_tmpdir(self, patient_full_path, default_database_options, tmp_path):
        results = extract_patient(patient_full_path, default_database_options, save_folder=tmp_path)
        saved_files = list(tmp_path.glob("*.parquet"))
        assert len(saved_files) > 0
        # At least the successful ones should have files
        successes = sum(1 for v in results.values() if v is not None)
        assert len(saved_files) == successes


class TestBatchExtract:
    def test_batch_two_patients(self, patient_full_path, patient_difficult_path):
        results = batch_extract([patient_full_path, patient_difficult_path])
        assert isinstance(results, dict)
        assert len(results) == 2
        assert patient_full_path.name in results
        assert patient_difficult_path.name in results

    def test_batch_values_are_dicts(self, patient_full_path, patient_difficult_path):
        results = batch_extract([patient_full_path, patient_difficult_path])
        for patient_name, patient_results in results.items():
            assert isinstance(patient_results, dict), f"{patient_name} results is not a dict"
