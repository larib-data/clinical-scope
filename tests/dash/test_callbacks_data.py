"""Tests for Dash callback helper functions — direct invocation, no browser."""

import json

import pytest
from dash import no_update

import clinical_scope.constants as cst
from clinical_scope.dash_api.callbacks.data_callbacks import (
    _build_inspection_content,
    _build_slider_marks,
    _parse_database_options_file,
    _status_badge,
    format_time_range,
    process_visualization,
    reload_patient_options,
    rerender_datetime_on_timezone_change,
    update_datetime_tz_label,
)
from clinical_scope.dash_api.io import load_patient_options
from clinical_scope.datasource.inspection import ColumnInfo, DataSourceInspection
from clinical_scope.io.paths import get_patient_options_path

# ---------------------------------------------------------------------------
# _parse_database_options_file
# ---------------------------------------------------------------------------


class TestParseDbOptionsFile:
    def test_parse_json(self, example_database_options):
        content = json.dumps(example_database_options).encode("utf-8")
        result, issues = _parse_database_options_file(content, "test.json")
        assert isinstance(result, dict)
        assert "philips_waves" in result
        assert isinstance(issues, list)

    def test_parse_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _parse_database_options_file(b"data", "test.txt")

    def test_parse_xlsx(self, project_root):
        xlsx_path = project_root / "example" / "option_files" / "example_database_options.xlsx"
        if not xlsx_path.exists():
            pytest.skip("No example xlsx file")
        content = xlsx_path.read_bytes()
        result, issues = _parse_database_options_file(content, "test.xlsx")
        assert isinstance(result, dict)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# _status_badge
# ---------------------------------------------------------------------------


class TestStatusBadge:
    def test_ok_badge(self):
        badge = _status_badge("ok")
        assert badge.children == "ok"

    def test_error_badge(self):
        badge = _status_badge("load_error")
        assert badge.children == "load_error"

    def test_unknown_status(self):
        badge = _status_badge("unknown")
        assert badge.children == "unknown"


# ---------------------------------------------------------------------------
# _build_inspection_content
# ---------------------------------------------------------------------------


class TestBuildInspectionContent:
    def test_ok_result(self):
        results = [
            DataSourceInspection(
                datasource_name="philips_waves",
                status="ok",
                file_path="/data/waves.parquet",
                raw_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
                filtered_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
                columns=[ColumnInfo("ART", True, 1000, 800)],
            )
        ]
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0

    def test_error_result(self):
        results = [
            DataSourceInspection(
                datasource_name="broken",
                status="load_error",
                error_message="File corrupt",
            )
        ]
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0

    def test_empty_results(self):
        content = _build_inspection_content([])
        assert isinstance(content, list)


# ---------------------------------------------------------------------------
# _build_slider_marks
# ---------------------------------------------------------------------------


class TestBuildSliderMarks:
    def test_default_marks(self):
        marks = _build_slider_marks(1000000.0, 3600.0)
        assert isinstance(marks, dict)
        assert len(marks) == 6  # n_marks=5 → 6 entries (0 to 5)
        assert 0.0 in marks
        assert 3600.0 in marks

    def test_custom_n_marks(self):
        marks = _build_slider_marks(1000000.0, 3600.0, n_marks=3)
        assert len(marks) == 4

    def test_long_duration_format(self):
        """Durations > 1 day should use date+time format."""
        marks = _build_slider_marks(1000000.0, 100000.0)
        # Should contain "/" (month/day format)
        for label in marks.values():
            assert "/" in label


# ---------------------------------------------------------------------------
# format_time_range
# ---------------------------------------------------------------------------


class TestFormatTimeRange:
    def test_returns_string(self):
        result = format_time_range(1000000.0, 1003600.0)
        assert isinstance(result, str)
        assert "\u2014" in result  # — separator

    def test_contains_timestamps(self):
        result = format_time_range(1000000.0, 1003600.0)
        assert ":" in result  # time format HH:MM:SS


# ---------------------------------------------------------------------------
# Issue #68: datetime_start/datetime_end stored as tz-aware instants
# ---------------------------------------------------------------------------


def _global_ids(*names: str) -> list[dict[str, str]]:
    return [{"type": "patient-option", "name": f"global.{name}"} for name in names]


_DATETIME_SCHEMA_DATA = {
    "global.data_folder": "PathDataFolder",
    "global.output_root": "OutputRoot",
    "global.datetime_start": "DatetimeStart",
    "global.datetime_end": "DatetimeEnd",
}


class TestReloadPatientOptionsTimezoneRoundTrip:
    def test_aware_saved_bound_renders_in_current_settings_timezone(self, tmp_path):
        """The preview always uses the live Settings tz, not whatever the file was saved in (#69)."""
        data_folder = tmp_path / "patient"
        data_folder.mkdir()
        patient_options_path = get_patient_options_path(str(data_folder))
        patient_options_path.parent.mkdir(parents=True, exist_ok=True)
        patient_options_path.write_text(
            json.dumps(
                {
                    "data_folder": str(data_folder),
                    "datetime_start": "2004-09-15T08:20:00+02:00",
                    "datetime_end": "2004-09-15T10:20:00+02:00",
                }
            )
        )

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        current_values = [str(data_folder), "", "", ""]

        new_values, _status = reload_patient_options(
            1,
            current_values,
            ids,
            _DATETIME_SCHEMA_DATA,
            {"display_timezone": "America/New_York"},
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 02:20:00"
        assert new_values[names.index("global.datetime_end")] == "2004-09-15 04:20:00"

    def test_legacy_naive_saved_file_is_unaffected(self, tmp_path):
        """Strictly additive: an older, still-naive saved file round-trips unchanged."""
        data_folder = tmp_path / "patient"
        data_folder.mkdir()
        patient_options_path = get_patient_options_path(str(data_folder))
        patient_options_path.parent.mkdir(parents=True, exist_ok=True)
        patient_options_path.write_text(
            json.dumps(
                {
                    "data_folder": str(data_folder),
                    "display_timezone": "UTC",
                    "datetime_start": "2004-09-15 06:20:00",
                }
            )
        )

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        current_values = [str(data_folder), "", "", ""]

        new_values, _status = reload_patient_options(
            1, current_values, ids, _DATETIME_SCHEMA_DATA, {"display_timezone": "Europe/Paris"}
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 06:20:00"


class TestProcessVisualizationSubmitTimezone:
    def test_submit_writes_aware_datetime_bounds(self, tmp_path):
        data_folder = tmp_path / "patient"
        data_folder.mkdir()

        ids = _global_ids("data_folder", "output_root", "datetime_start", "datetime_end")
        values = [
            str(data_folder),
            "",
            "2004-09-15 08:20:00",
            "2004-09-15 10:20:00",
        ]

        # database_options only needs to be truthy; wrapper.main is free to fail afterward
        # (no real datasource data under data_folder) — this test only cares what got saved.
        process_visualization(
            1,
            {"philips_waves": {}},
            _DATETIME_SCHEMA_DATA,
            values,
            ids,
            {"display_timezone": "Europe/Paris"},
        )

        saved = load_patient_options(str(data_folder))
        assert saved["datetime_start"] == "2004-09-15T08:20:00+02:00"
        assert saved["datetime_end"] == "2004-09-15T10:20:00+02:00"


class TestRerenderDatetimeOnTimezoneChange:
    def test_preserves_instant_across_timezones(self):
        ids = _global_ids("datetime_start", "datetime_end")
        current_values = ["2004-09-15 08:20:00", "2004-09-15 10:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "America/New_York", current_values, ids, "Europe/Paris"
        )

        names = [id_["name"] for id_ in ids]
        assert new_values[names.index("global.datetime_start")] == "2004-09-15 02:20:00"
        assert new_values[names.index("global.datetime_end")] == "2004-09-15 04:20:00"
        assert new_timezone == "America/New_York"

    def test_unchanged_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "Europe/Paris", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"

    def test_mid_typing_invalid_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "America/New_Y", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"

    def test_empty_timezone_is_a_no_op(self):
        ids = _global_ids("datetime_start")
        current_values = ["2004-09-15 08:20:00"]

        new_values, new_timezone = rerender_datetime_on_timezone_change(
            "", current_values, ids, "Europe/Paris"
        )

        assert all(value is no_update for value in new_values)
        assert new_timezone == "Europe/Paris"


class TestUpdateDatetimeTzLabel:
    def test_shows_given_timezone(self):
        assert update_datetime_tz_label("Europe/Paris") == (
            "interpreted in Europe/Paris",
            "interpreted in Europe/Paris",
        )

    def test_falls_back_to_default_when_empty(self):
        start_label, end_label = update_datetime_tz_label(None)
        assert "interpreted in" in start_label
        assert start_label == end_label

    def test_falls_back_to_default_when_invalid(self):
        # Never echo an unresolved/invalid name (e.g. mid-typing) as if it were in effect.
        start_label, end_label = update_datetime_tz_label("Not/AZone")
        assert "Not/AZone" not in start_label
        assert f"interpreted in {cst.DISPLAY_TIMEZONE}" == start_label == end_label
