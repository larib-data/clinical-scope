"""Tests for Dash inspection callback helpers with real data."""

from clinical_scope.dash_api.callbacks.data_callbacks import _build_inspection_content
from clinical_scope.datasource.inspection import ColumnInfo, DataSourceInspection
from clinical_scope.wrapper import inspect


class TestBuildInspectionWithRealData:
    def test_build_from_real_inspection(self, patient_options_full, default_database_options):
        results = inspect(patient_options_full, default_database_options)
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0


class TestPrunedViewNotice:
    """A table showing only configured signals must say so, or a reader misreads it."""

    RESULT = DataSourceInspection(
        datasource_name="servo_u", status="ok", columns=[ColumnInfo("HR", True, 100, 100)]
    )

    def test_notice_absent_on_a_full_view(self):
        assert "Pruned view" not in str(_build_inspection_content([self.RESULT]))

    def test_notice_shown_on_a_pruned_view(self):
        pruned = DataSourceInspection(
            datasource_name=self.RESULT.datasource_name,
            status=self.RESULT.status,
            columns=self.RESULT.columns,
            columns_pruned=True,
        )
        assert "Pruned view" in str(_build_inspection_content([pruned]))
