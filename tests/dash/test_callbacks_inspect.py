"""Tests for Dash inspection callback helpers with real data."""

from clinical_scope.dash_api.callbacks.data_callbacks import _build_inspection_content
from clinical_scope.wrapper import inspect


class TestBuildInspectionWithRealData:
    def test_build_from_real_inspection(self, patient_options_full, default_database_options):
        results = inspect(patient_options_full, default_database_options)
        content = _build_inspection_content(results)
        assert isinstance(content, list)
        assert len(content) > 0
