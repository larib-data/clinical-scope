"""Integration tests for batch_inspect() and database_statistics() — multi-patient pipeline."""

import pytest

from clinical_data_visualizer.database_statistics import DatabaseStatistics
from clinical_data_visualizer.inspection import DataSourceInspection
from clinical_data_visualizer.wrapper import batch_inspect, database_statistics
from tests.conftest import EXAMPLE_DIR

EXAMPLE_PATIENTS_ROOT = EXAMPLE_DIR / "example_patients"


@pytest.fixture(scope="module")
def batch_results(default_database_options):
    return batch_inspect(
        EXAMPLE_PATIENTS_ROOT,
        database_options_global=default_database_options,
    )


@pytest.fixture(scope="module")
def db_stats(default_database_options):
    return database_statistics(
        EXAMPLE_PATIENTS_ROOT,
        database_options_global=default_database_options,
    )


class TestBatchInspect:
    def test_returns_all_patients(self, batch_results):
        assert len(batch_results) == 3
        assert "Patient_full" in batch_results
        assert "Patient_difficult_format" in batch_results
        assert "Patient_other" in batch_results

    def test_each_patient_has_inspections(self, batch_results):
        for patient, inspections in batch_results.items():
            assert isinstance(inspections, list), f"{patient}: expected list"
            assert len(inspections) > 0, f"{patient}: no inspection results"
            assert all(isinstance(r, DataSourceInspection) for r in inspections)

    def test_patient_full_mostly_ok(self, batch_results):
        results = batch_results["Patient_full"]
        ok_count = sum(1 for r in results if r.status == "ok")
        assert ok_count >= 8, f"Patient_full: only {ok_count} OK (expected >= 8)"

    def test_progress_callback_called(self, default_database_options):
        calls = []

        def on_progress(current, total, name):
            calls.append((current, total, name))

        batch_inspect(
            EXAMPLE_PATIENTS_ROOT,
            database_options_global=default_database_options,
            progress_callback=on_progress,
        )
        assert len(calls) == 3
        assert calls[-1][0] == 3  # last call: current == total
        assert calls[-1][1] == 3


class TestDatabaseStatistics:
    def test_returns_database_statistics(self, db_stats):
        assert isinstance(db_stats, DatabaseStatistics)

    def test_total_patients(self, db_stats):
        assert db_stats.total_patients == 3

    def test_has_datasource_names(self, db_stats):
        assert len(db_stats.datasource_names) > 0

    def test_presence_matrix_has_all_patients(self, db_stats):
        assert len(db_stats.presence_matrix) == 3
        assert "Patient_full" in db_stats.presence_matrix

    def test_patient_full_high_completeness(self, db_stats):
        ps = next(p for p in db_stats.patient_summaries if p.patient_name == "Patient_full")
        assert ps.completeness_score >= 0.7

    def test_datasource_summaries_populated(self, db_stats):
        assert len(db_stats.datasource_summaries) > 0
        for ds_sum in db_stats.datasource_summaries:
            assert ds_sum.total_patients == 3

    def test_temporal_overlap_is_symmetric(self, db_stats):
        for ds_a in db_stats.datasource_names:
            for ds_b in db_stats.datasource_names:
                assert (
                    db_stats.temporal_overlap[ds_a][ds_b] == db_stats.temporal_overlap[ds_b][ds_a]
                ), f"Asymmetric overlap: {ds_a} vs {ds_b}"
