"""Unit tests for inspection.py — ColumnInfo, DataSourceInspection, serialization."""

from clinical_data_visualizer.datasource.inspection import (
    ColumnInfo,
    DataSourceInspection,
    results_from_json,
    results_to_json,
    to_csv_string,
    to_text_summary,
)

# ---------------------------------------------------------------------------
# ColumnInfo
# ---------------------------------------------------------------------------


class TestColumnInfo:
    def test_display_values_length(self):
        col = ColumnInfo(
            raw_name="ART",
            is_configured=True,
            raw_point_count=1000,
            filtered_point_count=800,
            first_filtered_timestamp="24-01-01 08:00:00",
            last_filtered_timestamp="24-01-01 09:00:00",
        )
        vals = col.display_values()
        assert len(vals) == len(ColumnInfo.DISPLAY_HEADERS)

    def test_display_values_content(self):
        col = ColumnInfo(
            raw_name="FC",
            is_configured=False,
            raw_point_count=500,
            filtered_point_count=250,
        )
        vals = col.display_values()
        assert vals[0] == "FC"
        assert vals[1] == "\u2717"  # ✗ for not configured
        assert "500" in vals[2]
        assert "250" in vals[3]
        assert "50.0%" in vals[4]

    def test_display_values_zero_raw(self):
        col = ColumnInfo(
            raw_name="X", is_configured=True, raw_point_count=0, filtered_point_count=0
        )
        vals = col.display_values()
        assert vals[4] == "\u2014"  # — for zero division

    def test_display_values_none_timestamps(self):
        col = ColumnInfo(
            raw_name="X", is_configured=True, raw_point_count=10, filtered_point_count=5
        )
        vals = col.display_values()
        assert vals[5] == "\u2014"  # — for None
        assert vals[6] == "\u2014"


# ---------------------------------------------------------------------------
# DataSourceInspection
# ---------------------------------------------------------------------------


class TestDataSourceInspection:
    def test_ok_status(self):
        insp = DataSourceInspection(
            datasource_name="philips_waves",
            status="ok",
            file_path="/data/waves.parquet",
            raw_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
            filtered_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
            columns=[
                ColumnInfo("ART", True, 1000, 800),
            ],
        )
        assert insp.status == "ok"
        assert len(insp.columns) == 1
        assert insp.error_message is None

    def test_file_not_found(self):
        insp = DataSourceInspection(datasource_name="syringe", status="file_not_found")
        assert insp.columns == []
        assert insp.raw_date_range is None


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


class TestSerialization:
    def _make_results(self):
        return [
            DataSourceInspection(
                datasource_name="philips_waves",
                status="ok",
                file_path="/data/waves.parquet",
                raw_date_range=("24-01-01 08:00:00", "24-01-01 09:00:00"),
                filtered_date_range=("24-01-01 08:10:00", "24-01-01 08:50:00"),
                columns=[
                    ColumnInfo("ART", True, 1000, 800, "24-01-01 08:10:00", "24-01-01 08:50:00"),
                    ColumnInfo("PAP", False, 1000, 600),
                ],
            ),
            DataSourceInspection(
                datasource_name="syringe",
                status="file_not_found",
            ),
        ]

    def test_json_roundtrip(self):
        original = self._make_results()
        json_data = results_to_json(original)
        restored = results_from_json(json_data)

        assert len(restored) == len(original)
        for orig, rest in zip(original, restored):
            assert orig.datasource_name == rest.datasource_name
            assert orig.status == rest.status
            assert orig.error_message == rest.error_message
            assert orig.raw_date_range == rest.raw_date_range
            assert orig.filtered_date_range == rest.filtered_date_range
            assert len(orig.columns) == len(rest.columns)

    def test_json_roundtrip_column_values(self):
        original = self._make_results()
        json_data = results_to_json(original)
        restored = results_from_json(json_data)

        for orig_col, rest_col in zip(original[0].columns, restored[0].columns):
            assert orig_col.raw_name == rest_col.raw_name
            assert orig_col.is_configured == rest_col.is_configured
            assert orig_col.raw_point_count == rest_col.raw_point_count
            assert orig_col.filtered_point_count == rest_col.filtered_point_count


# ---------------------------------------------------------------------------
# to_csv_string
# ---------------------------------------------------------------------------


class TestToCsvString:
    def test_non_empty(self):
        results = [
            DataSourceInspection(
                datasource_name="test_ds",
                status="ok",
                columns=[ColumnInfo("col1", True, 100, 50)],
            )
        ]
        csv_str = to_csv_string(results)
        lines = csv_str.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "datasource" in lines[0]
        assert "test_ds" in lines[1]

    def test_error_datasource_has_row(self):
        results = [
            DataSourceInspection(
                datasource_name="broken", status="load_error", error_message="oops"
            )
        ]
        csv_str = to_csv_string(results)
        assert "broken" in csv_str
        assert "oops" in csv_str

    def test_empty_results(self):
        csv_str = to_csv_string([])
        lines = csv_str.strip().split("\n")
        assert len(lines) == 1  # header only


# ---------------------------------------------------------------------------
# to_text_summary
# ---------------------------------------------------------------------------


class TestToTextSummary:
    def test_contains_datasource_name(self):
        results = [
            DataSourceInspection(
                datasource_name="philips_waves",
                status="ok",
                columns=[ColumnInfo("ART", True, 100, 50)],
            )
        ]
        text = to_text_summary(results)
        assert "philips_waves" in text
        assert "OK" in text

    def test_empty_results(self):
        text = to_text_summary([])
        assert text == ""

    def test_error_shows_message(self):
        results = [
            DataSourceInspection(
                datasource_name="bad",
                status="load_error",
                error_message="file corrupt",
            )
        ]
        text = to_text_summary(results)
        assert "FAIL" in text
        assert "file corrupt" in text
