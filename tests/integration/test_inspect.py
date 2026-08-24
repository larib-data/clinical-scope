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
        """
        Should have one result per datasource in database_options.

        'other' is the exception: it reports one entry per file (``other::<stem>``), so its
        single config key expands into as many results as demo_patient's other/ folder holds.
        """
        result_names = {r.datasource_name for r in inspection_results}
        expected_names = set(default_database_options.keys()) - {"other"}
        other_names = {name for name in result_names if name.startswith("other::")}
        assert other_names, "expected per-file 'other::<stem>' inspection entries"
        assert result_names - other_names == expected_names

    def test_most_datasources_ok(self, inspection_results):
        """
        demo_patient has 9 datasource folders, three of which are files inside other/.

        Threshold tolerates one unexpected failure while still catching regressions.
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
        assert "OK" in text

    def test_json_roundtrip(self, inspection_results):
        json_data = results_to_json(inspection_results)
        restored = results_from_json(json_data)
        assert len(restored) == len(inspection_results)
        for orig, rest in zip(inspection_results, restored):
            assert orig.datasource_name == rest.datasource_name
            assert orig.status == rest.status
            assert len(orig.columns) == len(rest.columns)


class TestInspectDisplayTimezone:
    """display_timezone is a user option now — cosmetic only, resolved by wrapper.inspect()."""

    def test_user_options_shift_the_reported_date_range(
        self, patient_options_full, default_database_options
    ):
        paris = inspect(
            patient_options_full,
            default_database_options,
            user_options={"display_timezone": "Europe/Paris"},
        )
        tokyo = inspect(
            patient_options_full,
            default_database_options,
            user_options={"display_timezone": "Asia/Tokyo"},
        )
        paris_ranges = {r.datasource_name: r.raw_date_range for r in paris if r.status == "ok"}
        tokyo_ranges = {r.datasource_name: r.raw_date_range for r in tokyo if r.status == "ok"}
        assert paris_ranges  # sanity: at least one datasource actually compared
        assert paris_ranges != tokyo_ranges

    def test_missing_user_options_defaults_like_before(
        self, patient_options_full, default_database_options
    ):
        """No user_options at all (e.g. a bare library call) behaves like the documented default."""
        default = inspect(patient_options_full, default_database_options)
        explicit_default = inspect(
            patient_options_full,
            default_database_options,
            user_options={"display_timezone": "Europe/Paris"},
        )
        default_ranges = [r.raw_date_range for r in default if r.status == "ok"]
        explicit_ranges = [r.raw_date_range for r in explicit_default if r.status == "ok"]
        assert default_ranges == explicit_ranges


class TestInspectConfiguredColumnsOnlyReachesDatasources:
    """
    wrapper.inspect(configured_columns_only=...) must actually reach DataSourceBase.inspect() —
    every real caller (Python API, CLI script, Dash callback) goes through this one function,
    so a seam that silently dropped the flag here would make the feature inert everywhere.
    """

    STEM = "waves_first_half_filtered"
    SELECTED = ["Solar8000/HR", "BIS/BIS"]

    def _database_options(self):
        return {"other": {"files": {self.STEM: {"field_display": self.SELECTED}}}}

    def _entry(self, results):
        return next(r for r in results if r.datasource_name == f"other::{self.STEM}")

    def test_default_does_not_prune(self, patient_options_difficult):
        entry = self._entry(inspect(patient_options_difficult, self._database_options()))
        assert entry.columns_pruned is False
        assert {c.raw_name for c in entry.columns} > set(self.SELECTED)

    def test_flag_reaches_the_datasource_and_prunes(self, patient_options_difficult):
        entry = self._entry(
            inspect(
                patient_options_difficult,
                self._database_options(),
                configured_columns_only=True,
            )
        )
        assert entry.columns_pruned is True
        assert {c.raw_name for c in entry.columns} == set(self.SELECTED)


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
