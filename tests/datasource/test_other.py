"""
Tests for other (generic) datasource — auto datetime detection, per-file grouping.

The 'other' datasource only exists in Patient_difficult_format, not demo_patient.
It has a custom main() that processes files individually rather than using _load().
"""

import pytest

from clinical_scope.database_options_parser import normalize_database_options


class TestFind:
    def test_find_folder_returns_path(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        assert folder is not None
        assert folder.is_dir()

    def test_find_returns_list(self, patient_difficult_path, other_cls):
        """Other is MULTI_FILE — _find() should return a list."""
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_find_correct_extensions(self, patient_difficult_path, other_cls):
        folder = other_cls._find_folder(patient_difficult_path)
        if folder is None:
            pytest.skip("other not in Patient_difficult")
        result = other_cls._find(folder)
        for p in result:
            assert p.suffix in (".csv", ".parquet")


class TestMainPipeline:
    """The 'other' datasource has a custom main() — test the full pipeline."""

    def test_main_returns_signals(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        assert isinstance(signals, list)
        assert len(signals) > 0

    def test_main_signals_have_data(self, patient_difficult_path):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        signals = ds.MAIN_MODULE(patient_options, {})
        for sig in signals:
            assert sig.data.x is not None
            assert sig.data.y is not None
            assert len(sig.data.x) > 0


class TestExtract:
    """The 'other' datasource does not support extract() — each file is its own signal group."""

    def test_extract_returns_none(self, patient_difficult_path, other_cls):
        patient_options = {
            "data_folder": str(patient_difficult_path),
            "datetime_start": None,
            "datetime_end": None,
            "quick_load": False,
        }
        df = other_cls.extract(patient_options, {})
        assert df is None, (
            "other.extract() must return None (multi-file datasource has no single-DataFrame representation)"
        )


# ---------------------------------------------------------------------------
# Per-file config tests (other::filename feature)
# ---------------------------------------------------------------------------

PATIENT_OPTIONS = {
    "datetime_start": None,
    "datetime_end": None,
    "quick_load": False,
}


class TestFieldDisplayFiltering:
    """field_display in an other::filename section filters signals to the listed columns."""

    def test_per_file_field_display_limits_signals(self, patient_difficult_path):
        """Only the listed columns are returned when per-file field_display is set."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}

        db_opts = {
            "other::waves_first_half_filtered": {
                "field_display": ["Solar8000/HR", "Solar8000/PLETH_SPO2"],
            }
        }
        normalize_database_options(db_opts)
        signals = ds.MAIN_MODULE(patient_options, db_opts["other"])

        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        returned_cols = {s.raw_name.split("::", 1)[1] for s in file_signals}
        assert returned_cols == {"Solar8000/HR", "Solar8000/PLETH_SPO2"}

    def test_no_field_display_returns_all_columns(self, patient_difficult_path):
        """When no field_display is configured, all numeric columns are returned."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}

        signals = ds.MAIN_MODULE(patient_options, {})

        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        # The parquet file has 6 columns — all should be loaded
        assert len(file_signals) == 6


class TestSignalOptionApplication:
    """Signal options (label, unit, color, range) are applied from database_options."""

    def _run_main(self, patient_difficult_path, db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        return ds.MAIN_MODULE(patient_options, db_opts)

    def test_per_file_label_applied(self, patient_difficult_path):
        """Signal label from other::filename section is applied to sig.name."""

        db_opts = {
            "other::waves_first_half_filtered": {
                "signals": {"Solar8000/HR": {"label": "Heart Rate (custom)"}}
            }
        }
        normalize_database_options(db_opts)
        signals = self._run_main(patient_difficult_path, db_opts["other"])

        hr = next(
            (s for s in signals if s.raw_name == "waves_first_half_filtered::Solar8000/HR"), None
        )
        assert hr is not None, "HR signal not found"
        assert hr.name == "Heart Rate (custom)"

    def test_no_config_uses_column_name_as_label(self, patient_difficult_path):
        """Without any signal config, sig.name defaults to the raw column name."""
        signals = self._run_main(patient_difficult_path, {})

        hr = next(
            (s for s in signals if s.raw_name == "waves_first_half_filtered::Solar8000/HR"), None
        )
        assert hr is not None
        assert hr.name == "Solar8000/HR"


class TestGroupedFields:
    """Per-file grouped_fields from other::filename section are injected into database_options."""

    def _run_main_and_get_db_opts(self, patient_difficult_path, global_db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        ds.MAIN_MODULE(patient_options, global_db_opts)
        return global_db_opts

    def test_per_file_grouped_fields_injected_with_prefix(self, patient_difficult_path):
        """grouped_fields from other::filename are injected with file_stem:: prefix."""

        db_opts = {
            "other::waves_first_half_filtered": {
                "grouped_fields": {
                    "Vital signs": ["Solar8000/HR", "Solar8000/PLETH_SPO2"],
                }
            }
        }
        normalize_database_options(db_opts)
        result = self._run_main_and_get_db_opts(patient_difficult_path, db_opts["other"])

        groups = result.get("grouped_fields", {})
        assert "Vital signs" in groups
        assert "waves_first_half_filtered::Solar8000/HR" in groups["Vital signs"]
        assert "waves_first_half_filtered::Solar8000/PLETH_SPO2" in groups["Vital signs"]

    def test_group_by_file_creates_auto_group(self, patient_difficult_path):
        """When group_by_file=True (default) and no custom groups, file stem is the group name."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {
            **PATIENT_OPTIONS,
            "data_folder": str(patient_difficult_path),
            "other": {"group_by_file": True},
        }
        db_opts = {}
        ds.MAIN_MODULE(patient_options, db_opts)

        groups = db_opts.get("grouped_fields", {})
        assert "waves_first_half_filtered" in groups

    def test_group_by_file_false_no_auto_group(self, patient_difficult_path):
        """When group_by_file=False, no grouped_fields are injected."""
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {
            **PATIENT_OPTIONS,
            "data_folder": str(patient_difficult_path),
            "other": {"group_by_file": False},
        }
        db_opts = {}
        ds.MAIN_MODULE(patient_options, db_opts)

        assert "grouped_fields" not in db_opts


class TestLoopConfig:
    """Per-file loop definitions from other::filename are injected into database_options."""

    def test_per_file_loop_injected_with_prefix(self, patient_difficult_path):
        """Loop entries from other::filename are injected with file_stem:: prefix."""

        db_opts = {
            "other::waves_first_half_filtered": {
                "loop": {"HR vs SpO2": ["Solar8000/HR", "Solar8000/PLETH_SPO2"]}
            }
        }
        normalize_database_options(db_opts)
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        ds.MAIN_MODULE(patient_options, db_opts["other"])

        loop = db_opts["other"].get("loop", {})
        assert "HR vs SpO2" in loop
        assert loop["HR vs SpO2"] == [
            "waves_first_half_filtered::Solar8000/HR",
            "waves_first_half_filtered::Solar8000/PLETH_SPO2",
        ]


class TestNormalizeDatabaseOptions:
    """Unit tests for database_options_parser.normalize_database_options()."""

    def test_injects_files_key(self):

        db = {"other::my_file": {"signals": {"col": {"label": "Col"}}}}
        normalize_database_options(db)
        assert "other" in db
        assert "files" in db["other"]
        assert "my_file" in db["other"]["files"]

    def test_creates_bare_other_section_if_missing(self):

        db = {"other::only_file": {}}
        normalize_database_options(db)
        assert db.get("other") == {"files": {"only_file": {}}}

    def test_merges_with_existing_other_section(self):

        db = {
            "other": {"field_display": ["only_file::col"]},
            "other::only_file": {"signals": {"col": {"label": "Col"}}},
        }
        normalize_database_options(db)
        assert "field_display" in db["other"]  # existing key preserved
        assert db["other"]["files"]["only_file"]["signals"]["col"]["label"] == "Col"

    def test_noop_when_no_per_file_keys(self):

        db = {"other": {"signals": {}}, "philips_waves": {}}
        original = dict(db)
        normalize_database_options(db)
        assert db == original


class TestTimezone:
    """Timezone is applied via additional_informations.timezone in database_options."""

    def _run_main(self, patient_difficult_path, db_opts):
        from clinical_scope.datasource.registry import DataSource

        ds = DataSource.get_subclass_by_name("other")
        patient_options = {**PATIENT_OPTIONS, "data_folder": str(patient_difficult_path)}
        return ds.MAIN_MODULE(patient_options, db_opts)

    def test_tz_aware_parquet_timezone_is_preserved(self, patient_difficult_path):
        """Timezone already embedded in a parquet file is preserved through the pipeline."""
        # The test parquet file stores Europe/Paris timestamps — they must not be stripped.
        signals = self._run_main(patient_difficult_path, {})
        file_signals = [s for s in signals if s.raw_name.startswith("waves_first_half_filtered::")]
        assert len(file_signals) > 0
        for sig in file_signals:
            assert str(sig.data.timezone) == "Europe/Paris"
