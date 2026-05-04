"""Tests for Dash callback helper functions — direct invocation, no browser."""

import json

import pytest

from clinical_data_visualizer.dash_api.callbacks.data_callbacks import (
    _build_inspection_content,
    _build_slider_marks,
    _parse_database_options_file,
    _status_badge,
    format_time_range,
)
from clinical_data_visualizer.datasource.inspection import ColumnInfo, DataSourceInspection

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
