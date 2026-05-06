"""Unit tests for patient_options_io: load/locate patient_options.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinical_scope.dash_api.io import get_patient_options_path, load_patient_options


class TestGetPatientOptionsPath:
    def test_path_structure(self, tmp_path):
        path = get_patient_options_path(tmp_path)
        assert path == tmp_path / "clinical_scope_output" / "patient_options.json"

    def test_accepts_string(self, tmp_path):
        path = get_patient_options_path(str(tmp_path))
        assert isinstance(path, Path)


class TestLoadPatientOptions:
    def _write_opts(self, tmp_path: Path, data: object) -> None:
        dest = get_patient_options_path(tmp_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data))

    def test_returns_none_when_file_missing(self, tmp_path):
        assert load_patient_options(tmp_path) is None

    def test_raises_on_malformed_json(self, tmp_path):
        dest = get_patient_options_path(tmp_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("not json {{{")
        with pytest.raises(ValueError, match="Cannot read"):
            load_patient_options(tmp_path)

    def test_raises_when_root_is_not_dict(self, tmp_path):
        self._write_opts(tmp_path, [1, 2, 3])
        with pytest.raises(TypeError, match="not a JSON object"):
            load_patient_options(tmp_path)

    def test_loads_valid_options(self, tmp_path):
        opts = {"data_folder": str(tmp_path), "datetime_start": "2024-01-01 00:00:00"}
        self._write_opts(tmp_path, opts)
        assert load_patient_options(tmp_path) == opts

    def test_orphaned_datasource_fields_returned_as_is(self, tmp_path):
        """Fields for datasources no longer in db options are included; caller filters them."""
        opts = {"data_folder": str(tmp_path), "removed_source": {"time_shift": 5.0}}
        self._write_opts(tmp_path, opts)
        result = load_patient_options(tmp_path)
        assert result == opts
