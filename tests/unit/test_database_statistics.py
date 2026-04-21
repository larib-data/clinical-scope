"""Unit tests for database_statistics.py — aggregation logic, serialization, exports."""

from clinical_data_visualizer.database_statistics import (
    compute_database_statistics,
    stats_from_json,
    stats_to_json,
    to_csv_string,
    to_text_summary,
)
from clinical_data_visualizer.inspection import ColumnInfo, DataSourceInspection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inspection(
    ds_name: str,
    status: str = "ok",
    columns: list[ColumnInfo] | None = None,
    filtered_range: tuple[str, str] | None = None,
) -> DataSourceInspection:
    return DataSourceInspection(
        datasource_name=ds_name,
        status=status,
        columns=columns or [],
        filtered_date_range=filtered_range,
    )


def _make_col(
    name: str,
    raw_pts: int = 100,
    filtered_pts: int = 80,
    configured: bool = True,
    first_ts: str | None = None,
    last_ts: str | None = None,
) -> ColumnInfo:
    return ColumnInfo(
        raw_name=name,
        is_configured=configured,
        raw_point_count=raw_pts,
        filtered_point_count=filtered_pts,
        first_filtered_timestamp=first_ts,
        last_filtered_timestamp=last_ts,
    )


# ---------------------------------------------------------------------------
# compute_database_statistics
# ---------------------------------------------------------------------------


class TestComputeEmpty:
    def test_empty_input(self):
        stats = compute_database_statistics({})
        assert stats.total_patients == 0
        assert stats.datasource_names == []
        assert stats.patient_summaries == []
        assert stats.datasource_summaries == []


class TestComputeSinglePatient:
    def test_single_patient_single_ds(self):
        inspections = {
            "Patient_01": [
                _make_inspection(
                    "philips",
                    columns=[_make_col("ART", filtered_pts=500)],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T09:00:00"),
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        assert stats.total_patients == 1
        assert stats.datasource_names == ["philips"]
        assert len(stats.patient_summaries) == 1
        assert stats.patient_summaries[0].completeness_score == 1.0

    def test_single_patient_file_not_found(self):
        inspections = {
            "Patient_01": [
                _make_inspection("philips", status="file_not_found"),
                _make_inspection("eit", status="ok", columns=[_make_col("Z")]),
            ]
        }
        stats = compute_database_statistics(inspections)
        assert stats.patient_summaries[0].completeness_score == 0.5
        ps = stats.presence_matrix["Patient_01"]
        assert ps["philips"] == "file_not_found"
        assert ps["eit"] == "ok"


class TestComputeMultiplePatients:
    def setup_method(self):
        self.inspections = {
            "P1": [
                _make_inspection(
                    "waves",
                    columns=[_make_col("ART", filtered_pts=100), _make_col("FC", filtered_pts=50)],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T09:00:00"),
                ),
                _make_inspection("numerics", status="file_not_found"),
            ],
            "P2": [
                _make_inspection(
                    "waves",
                    columns=[
                        _make_col("ART", filtered_pts=200),
                        _make_col("FC", filtered_pts=0),
                    ],
                    filtered_range=("2024-01-01T08:30:00", "2024-01-01T09:30:00"),
                ),
                _make_inspection(
                    "numerics",
                    columns=[_make_col("HR", filtered_pts=300)],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T10:00:00"),
                ),
            ],
        }
        self.stats = compute_database_statistics(self.inspections)

    def test_total_patients(self):
        assert self.stats.total_patients == 2

    def test_datasource_names_sorted(self):
        assert self.stats.datasource_names == ["numerics", "waves"]

    def test_presence_matrix(self):
        assert self.stats.presence_matrix["P1"]["waves"] == "ok"
        assert self.stats.presence_matrix["P1"]["numerics"] == "file_not_found"
        assert self.stats.presence_matrix["P2"]["waves"] == "ok"
        assert self.stats.presence_matrix["P2"]["numerics"] == "ok"

    def test_completeness_scores(self):
        p1 = next(ps for ps in self.stats.patient_summaries if ps.patient_name == "P1")
        p2 = next(ps for ps in self.stats.patient_summaries if ps.patient_name == "P2")
        assert p1.completeness_score == 0.5
        assert p2.completeness_score == 1.0

    def test_datasource_summary_patient_counts(self):
        waves_sum = next(
            ds for ds in self.stats.datasource_summaries if ds.datasource_name == "waves"
        )
        num_sum = next(
            ds for ds in self.stats.datasource_summaries if ds.datasource_name == "numerics"
        )
        assert waves_sum.patient_count == 2
        assert num_sum.patient_count == 1

    def test_column_aggregate_stats(self):
        waves_sum = next(
            ds for ds in self.stats.datasource_summaries if ds.datasource_name == "waves"
        )
        art = waves_sum.columns["ART"]
        assert art.patient_count == 2  # Both patients have >0 points
        assert art.total_points == 300  # 100 + 200
        assert art.mean_points == 150.0
        assert art.min_points == 100
        assert art.max_points == 200

        fc = waves_sum.columns["FC"]
        assert fc.patient_count == 1  # P2 has 0 points


class TestTemporalOverlap:
    def test_overlapping_ranges(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "A",
                    columns=[_make_col("x")],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T10:00:00"),
                ),
                _make_inspection(
                    "B",
                    columns=[_make_col("y")],
                    filtered_range=("2024-01-01T09:00:00", "2024-01-01T11:00:00"),
                ),
            ],
        }
        stats = compute_database_statistics(inspections)
        assert stats.temporal_overlap["A"]["B"] == 1
        assert stats.temporal_overlap["B"]["A"] == 1
        # Self-overlap
        assert stats.temporal_overlap["A"]["A"] == 1

    def test_non_overlapping_ranges(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "A",
                    columns=[_make_col("x")],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T09:00:00"),
                ),
                _make_inspection(
                    "B",
                    columns=[_make_col("y")],
                    filtered_range=("2024-01-01T10:00:00", "2024-01-01T11:00:00"),
                ),
            ],
        }
        stats = compute_database_statistics(inspections)
        assert stats.temporal_overlap["A"]["B"] == 0

    def test_missing_range(self):
        inspections = {
            "P1": [
                _make_inspection("A", status="file_not_found"),
                _make_inspection(
                    "B",
                    columns=[_make_col("y")],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T09:00:00"),
                ),
            ],
        }
        stats = compute_database_statistics(inspections)
        assert stats.temporal_overlap["A"]["B"] == 0


class TestConfigCoverage:
    def test_all_configured(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "ds",
                    columns=[
                        _make_col("a", configured=True),
                        _make_col("b", configured=True),
                    ],
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        ds_sum = stats.datasource_summaries[0]
        assert ds_sum.config_coverage == 1.0

    def test_partial_coverage(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "ds",
                    columns=[
                        _make_col("a", configured=True),
                        _make_col("b", configured=False),
                    ],
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        ds_sum = stats.datasource_summaries[0]
        assert ds_sum.config_coverage == 0.5


class TestSamplingRate:
    def test_sampling_rate_computed(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "ds",
                    columns=[
                        _make_col(
                            "sig",
                            filtered_pts=3600,
                            first_ts="2024-01-01T08:00:00",
                            last_ts="2024-01-01T09:00:00",
                        )
                    ],
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        col = stats.datasource_summaries[0].columns["sig"]
        # 3600 pts / 3600 seconds = 1.0 Hz
        assert col.mean_sampling_rate_hz == 1.0

    def test_sampling_rate_none_without_timestamps(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "ds",
                    columns=[_make_col("sig", filtered_pts=100)],
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        col = stats.datasource_summaries[0].columns["sig"]
        assert col.mean_sampling_rate_hz is None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestJsonRoundtrip:
    def test_roundtrip(self):
        inspections = {
            "P1": [
                _make_inspection(
                    "waves",
                    columns=[_make_col("ART", filtered_pts=100)],
                    filtered_range=("2024-01-01T08:00:00", "2024-01-01T09:00:00"),
                )
            ]
        }
        stats = compute_database_statistics(inspections)
        data = stats_to_json(stats)
        restored = stats_from_json(data)

        assert restored.total_patients == stats.total_patients
        assert restored.datasource_names == stats.datasource_names
        assert len(restored.patient_summaries) == len(stats.patient_summaries)
        assert len(restored.datasource_summaries) == len(stats.datasource_summaries)
        assert restored.presence_matrix == stats.presence_matrix
        assert restored.temporal_overlap == stats.temporal_overlap

        # Check nested column stats survived roundtrip
        orig_col = stats.datasource_summaries[0].columns["ART"]
        rest_col = restored.datasource_summaries[0].columns["ART"]
        assert rest_col.total_points == orig_col.total_points
        assert rest_col.patient_count == orig_col.patient_count


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


class TestCsvExport:
    def test_csv_has_header_and_rows(self):
        inspections = {
            "P1": [_make_inspection("waves"), _make_inspection("nums")],
            "P2": [_make_inspection("waves", status="file_not_found"), _make_inspection("nums")],
        }
        stats = compute_database_statistics(inspections)
        csv = to_csv_string(stats)
        lines = csv.strip().split("\n")
        assert len(lines) == 3  # header + 2 patients
        assert "patient" in lines[0]
        assert "waves_status" in lines[0]
        assert "nums_status" in lines[0]

    def test_csv_completeness_values(self):
        inspections = {
            "P1": [_make_inspection("waves"), _make_inspection("nums", status="file_not_found")],
        }
        stats = compute_database_statistics(inspections)
        csv = to_csv_string(stats)
        assert "0.50" in csv  # completeness score


# ---------------------------------------------------------------------------
# Text summary
# ---------------------------------------------------------------------------


class TestTextSummary:
    def test_text_contains_patient_count(self):
        inspections = {"P1": [_make_inspection("waves")]}
        stats = compute_database_statistics(inspections)
        text = to_text_summary(stats)
        assert "Patients: 1" in text

    def test_text_contains_presence_matrix(self):
        inspections = {"P1": [_make_inspection("waves")]}
        stats = compute_database_statistics(inspections)
        text = to_text_summary(stats)
        assert "Presence Matrix" in text
        assert "OK" in text
