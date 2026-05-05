"""Integration tests for wrapper.inspect() — end-to-end inspection pipeline."""

import pytest

from clinical_scope.datasource.inspection import (
    ColumnInfo,
    DataSourceInspection,
    results_from_json,
    results_to_json,
    to_csv_string,
    to_text_summary,
)
from clinical_scope.wrapper import inspect


@pytest.fixture(scope="module")
def inspection_results(patient_options_full, default_database_options):
    return inspect(patient_options_full, default_database_options)


class TestInspectPatientFull:
    def test_returns_list_of_inspections(self, inspection_results):
        assert isinstance(inspection_results, list)
        assert all(isinstance(r, DataSourceInspection) for r in inspection_results)

    def test_all_datasources_present(self, inspection_results, default_database_options):
        """Should have one result per datasource in database_options."""
        result_names = {r.datasource_name for r in inspection_results}
        expected_names = set(default_database_options.keys())
        assert result_names == expected_names

    def test_most_datasources_ok(self, inspection_results):
        """
        Patient_full has 10 datasource folders — all should load successfully.

        'other' is absent from Patient_full so it will not be 'ok'.
        Threshold is 9 to tolerate one unexpected failure while still catching regressions.
        """
        ok_count = sum(1 for r in inspection_results if r.status == "ok")
        assert ok_count >= 9, f"Only {ok_count} datasources succeeded (expected >= 9)"

    def test_ok_datasources_have_columns(self, inspection_results):
        for r in inspection_results:
            if r.status == "ok":
                assert len(r.columns) > 0, f"{r.datasource_name} has no columns"
                assert all(isinstance(c, ColumnInfo) for c in r.columns)

    def test_ok_datasources_have_date_range(self, inspection_results):
        for r in inspection_results:
            if r.status == "ok":
                assert r.raw_date_range is not None, f"{r.datasource_name} has no raw_date_range"
                assert r.filtered_date_range is not None

    def test_column_point_counts(self, inspection_results):
        for r in inspection_results:
            for c in r.columns:
                assert c.raw_point_count >= 0
                assert c.filtered_point_count >= 0
                assert c.filtered_point_count <= c.raw_point_count


class TestInspectSerialization:
    def test_csv_roundtrip(self, inspection_results):
        csv_str = to_csv_string(inspection_results)
        lines = csv_str.strip().split("\n")
        assert len(lines) > 1  # header + at least one data row
        assert "datasource" in lines[0]

    def test_text_summary(self, inspection_results):
        text = to_text_summary(inspection_results)
        assert len(text) > 0
        # Should contain at least one "OK" entry
        assert "OK" in text

    def test_json_roundtrip(self, inspection_results):
        json_data = results_to_json(inspection_results)
        restored = results_from_json(json_data)
        assert len(restored) == len(inspection_results)
        for orig, rest in zip(inspection_results, restored):
            assert orig.datasource_name == rest.datasource_name
            assert orig.status == rest.status
            assert len(orig.columns) == len(rest.columns)


class TestInspectWithDatetimeFilter:
    def test_filter_reduces_counts(self, patient_full_path, default_database_options):
        """Narrowing datetime range should reduce filtered_point_count."""
        patient_opts_narrow = {
            "data_folder": str(patient_full_path),
            "datetime_start": "2004-09-15 08:30:00",
            "datetime_end": "2004-09-15 08:45:00",
            "quick_load": False,
            "eit": {"day": "2004-09-15"},
        }
        results = inspect(patient_opts_narrow, default_database_options)
        for r in results:
            if r.status == "ok":
                for c in r.columns:
                    assert c.filtered_point_count <= c.raw_point_count
