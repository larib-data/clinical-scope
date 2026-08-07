"""
Tests for the shared patient-folder discovery helper (issue #53 / ADR-0001).

Covers:
- scan_patient_folder()             (registry.py) -- cheap core + deep mode
- format_zero_result_diagnostic()   (registry.py)
- emit_zero_result_diagnostic()     (registry.py)
- wrapper.main() still returns [] on these folders (pipeline behavior unchanged)
"""

from pathlib import Path

from clinical_scope import wrapper
from clinical_scope.datasource.registry import (
    emit_zero_result_diagnostic,
    format_zero_result_diagnostic,
    scan_patient_folder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).touch()


# ===========================================================================
# scan_patient_folder — path classification
# ===========================================================================


class TestScanPatientFolderClassification:
    def test_missing_path(self, tmp_path):
        scan = scan_patient_folder(tmp_path / "does_not_exist")
        assert scan.status == "missing"

    def test_path_is_a_file(self, tmp_path):
        file_path = tmp_path / "some_file.csv"
        file_path.touch()
        scan = scan_patient_folder(file_path)
        assert scan.status == "is_file"

    def test_empty_folder_is_ok_with_nothing_found(self, tmp_path):
        scan = scan_patient_folder(tmp_path)
        assert scan.status == "ok"
        assert scan.found == []
        assert scan.empty == []
        assert scan.other_subfolders == []
        assert scan.self_datasource is None


# ===========================================================================
# scan_patient_folder — device subfolder detection
# ===========================================================================


class TestScanPatientFolderDeviceDetection:
    def test_recognized_folder_with_content_is_found(self, tmp_path):
        _touch(tmp_path / "eit", "recording.asc")
        scan = scan_patient_folder(tmp_path)
        assert [ds.NAME for ds in scan.found] == ["eit"]
        assert scan.empty == []

    def test_recognized_folder_without_content_is_empty(self, tmp_path):
        (tmp_path / "eit").mkdir()
        scan = scan_patient_folder(tmp_path)
        assert scan.found == []
        assert [ds.NAME for ds in scan.empty] == ["eit"]

    def test_self_datasource_when_path_itself_is_a_device_folder(self, tmp_path):
        device_folder = tmp_path / "patient" / "eit"
        _touch(device_folder, "recording.asc")
        scan = scan_patient_folder(device_folder)
        assert scan.self_datasource is not None
        assert scan.self_datasource.NAME == "eit"

    def test_clinical_scope_output_is_skipped(self, tmp_path):
        _touch(tmp_path / "clinical_scope_output", "cache.parquet")
        scan = scan_patient_folder(tmp_path)
        assert scan.other_subfolders == []

    def test_dot_folders_are_skipped(self, tmp_path):
        _touch(tmp_path / ".git", "config")
        scan = scan_patient_folder(tmp_path)
        assert scan.other_subfolders == []


# ===========================================================================
# scan_patient_folder — Fixture A: files loose in patient root
# ===========================================================================


class TestFixtureALooseFilesInRoot:
    def test_cheap_mode_does_not_populate_loose_files(self, tmp_path):
        _touch(tmp_path, "waves.csv")
        scan = scan_patient_folder(tmp_path)
        assert scan.loose_files is None

    def test_deep_mode_reports_loose_root_files(self, tmp_path):
        _touch(tmp_path, "waves.csv", "readme.txt")
        scan = scan_patient_folder(tmp_path, deep=True)
        assert scan.loose_files == {".": ["waves.csv"]}

    def test_deep_mode_ignores_junk_files(self, tmp_path):
        # A dotfile with a recognized extension: the suffix alone wouldn't exclude it,
        # so this exercises the is_junk_file() filter specifically.
        _touch(tmp_path, ".hidden.csv")
        scan = scan_patient_folder(tmp_path, deep=True)
        assert scan.loose_files == {}

    def test_wrapper_main_still_returns_empty_list(self, tmp_path):
        _touch(tmp_path, "waves.csv")
        patient_options = {"data_folder": str(tmp_path)}
        assert wrapper.main(patient_options=patient_options) == []


# ===========================================================================
# scan_patient_folder — Fixture B: files in a misnamed subfolder
# ===========================================================================


class TestFixtureBMisnamedSubfolder:
    def test_misnamed_subfolder_is_unrecognized(self, tmp_path):
        _touch(tmp_path / "ventilator_data", "waves.csv")
        scan = scan_patient_folder(tmp_path)
        assert scan.other_subfolders == ["ventilator_data"]
        assert scan.found == []

    def test_deep_mode_reports_files_inside_misnamed_subfolder(self, tmp_path):
        _touch(tmp_path / "ventilator_data", "waves.csv", "readme.txt")
        scan = scan_patient_folder(tmp_path, deep=True)
        assert scan.loose_files == {"ventilator_data": ["waves.csv"]}

    def test_wrapper_main_still_returns_empty_list(self, tmp_path):
        _touch(tmp_path / "ventilator_data", "waves.csv")
        patient_options = {"data_folder": str(tmp_path)}
        assert wrapper.main(patient_options=patient_options) == []


# ===========================================================================
# format_zero_result_diagnostic
# ===========================================================================


class TestFormatZeroResultDiagnostic:
    def test_missing_folder_message(self, tmp_path):
        scan = scan_patient_folder(tmp_path / "nope")
        message = format_zero_result_diagnostic(scan)
        assert "doesn't exist" in message

    def test_loose_root_files_are_listed(self, tmp_path):
        _touch(tmp_path, "waves.csv")
        scan = scan_patient_folder(tmp_path, deep=True)
        message = format_zero_result_diagnostic(scan)
        assert "patient root" in message
        assert "waves.csv" in message

    def test_misnamed_subfolder_files_are_listed(self, tmp_path):
        _touch(tmp_path / "ventilator_data", "waves.csv")
        scan = scan_patient_folder(tmp_path, deep=True)
        message = format_zero_result_diagnostic(scan)
        assert "ventilator_data" in message
        assert "waves.csv" in message

    def test_points_to_organize_patient_folder_helper(self, tmp_path):
        scan = scan_patient_folder(tmp_path, deep=True)
        message = format_zero_result_diagnostic(scan)
        assert "organize-patient-folder" in message

    def test_found_but_still_zero_result_explains_config_or_load_failure(self, tmp_path):
        _touch(tmp_path / "eit", "recording.asc")
        scan = scan_patient_folder(tmp_path, deep=True)
        message = format_zero_result_diagnostic(scan)
        assert "EIT" in message


# ===========================================================================
# emit_zero_result_diagnostic -- logs the deep-scan diagnostic via logger.warning.
# ===========================================================================


class TestEmitZeroResultDiagnostic:
    def test_logs_a_warning(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            emit_zero_result_diagnostic(tmp_path)
        assert "No datasource produced any data" in caplog.text
