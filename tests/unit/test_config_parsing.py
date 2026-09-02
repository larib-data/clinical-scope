"""
Tests for config.parsing -- the file-path route into database_options.

Covers:
- load_database_options_from_path() on .json and .xlsx, plus its two refusals
- the ``<stem>_from_xlsx.json`` sidecar the .xlsx branch writes beside its input
- build_patient_options() and load_options()

Every fixture is copied into tmp_path before loading: the .xlsx branch writes a file next
to its input, and tests/data/ is frozen surface.
"""

from __future__ import annotations

import json
import logging
import shutil
import stat
from typing import TYPE_CHECKING

import pytest

from clinical_scope.config.parsing import (
    build_patient_options,
    load_database_options_from_path,
    load_options,
)
from clinical_scope.database_options_xlsx import xlsx_to_database_options

if TYPE_CHECKING:
    from pathlib import Path

JSON_FIXTURE = "example_database_options.json"
XLSX_FIXTURE = "example_database_options.xlsx"
XLSX_SIDECAR = "example_database_options_from_xlsx.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_dir(project_root):
    """Directory holding the frozen example_database_options pair."""
    return project_root / "tests" / "data" / "option_files"


def _copy_fixture(fixture_dir: Path, destination_dir: Path, name: str) -> Path:
    """Copy a frozen fixture into *destination_dir* and return the copy's path."""
    destination = destination_dir / name
    shutil.copy(fixture_dir / name, destination)
    return destination


# ===========================================================================
# load_database_options_from_path — the entry point README and scripts/ use
# ===========================================================================


class TestLoadDatabaseOptionsFromPath:
    def test_json_path_returns_the_parsed_config(self, fixture_dir, tmp_path):
        config = load_database_options_from_path(_copy_fixture(fixture_dir, tmp_path, JSON_FIXTURE))
        assert "global" in config
        assert "eit" in config
        assert "other::waves" in config
        assert "edf" in config
        assert config["global"]["grouped_fields"]
        assert config["other::waves"]["loop"]
        assert config["edf"]["spectrogram"]
        assert config["edf"]["psd"]

    def test_xlsx_path_returns_the_parsed_config(self, fixture_dir, tmp_path):
        """The .xlsx fixture is a smaller spreadsheet than its .json sibling, not a copy of it."""
        config = load_database_options_from_path(_copy_fixture(fixture_dir, tmp_path, XLSX_FIXTURE))
        assert "global" in config
        assert "eit" in config
        assert "other::waves" in config
        assert config["global"]["grouped_fields"]
        assert config["eit"]["signals"]
        assert config["other::waves"]["loop"]

    def test_uppercase_suffix_is_accepted(self, fixture_dir, tmp_path):
        """Extension matching is case-insensitive, so a Windows-cased .JSON still loads."""
        source = _copy_fixture(fixture_dir, tmp_path, JSON_FIXTURE)
        shouted = source.with_suffix(".JSON")
        source.rename(shouted)
        assert "eit" in load_database_options_from_path(shouted)

    def test_unsupported_suffix_raises_value_error(self, fixture_dir, tmp_path):
        source = _copy_fixture(fixture_dir, tmp_path, JSON_FIXTURE)
        disguised = source.with_suffix(".csv")
        source.rename(disguised)
        with pytest.raises(ValueError, match=r"\.csv"):
            load_database_options_from_path(disguised)

    def test_missing_path_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_database_options_from_path(tmp_path / "absent.json")


# ===========================================================================
# The .xlsx branch's sidecar — intended behaviour, not a surprise
# ===========================================================================


class TestIntermediateJsonSideEffect:
    def test_sidecar_lands_beside_the_spreadsheet(self, fixture_dir, tmp_path):
        source = _copy_fixture(fixture_dir, tmp_path, XLSX_FIXTURE)
        config = load_database_options_from_path(source)

        sidecar = tmp_path / XLSX_SIDECAR
        assert sidecar.exists()
        assert json.loads(sidecar.read_text(encoding="utf-8")) == config
        # It follows the input path rather than a fixed location — tests/data/ stays clean.
        assert not (fixture_dir / XLSX_SIDECAR).exists()

    def test_read_only_directory_does_not_break_the_conversion(self, fixture_dir, tmp_path, caplog):
        """The sidecar is best-effort: a failed write is warned about, not raised."""
        locked_dir = tmp_path / "locked"
        locked_dir.mkdir()
        source = _copy_fixture(fixture_dir, locked_dir, XLSX_FIXTURE)
        locked_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with caplog.at_level(logging.WARNING):
                config = xlsx_to_database_options(source)
            if (locked_dir / XLSX_SIDECAR).exists():
                pytest.skip("read-only directory still accepted the write (running as root?)")
            assert "eit" in config
            assert config["eit"]["signals"]
            # The warning names the unwritten file, so a write that never happened cannot pass here.
            assert [
                record.levelname
                for record in caplog.records
                if record.name == "clinical_scope.database_options_xlsx"
                and XLSX_SIDECAR in record.getMessage()
            ] == ["WARNING"]
        finally:
            # Restore write permission or tmp_path teardown fails.
            locked_dir.chmod(stat.S_IRWXU)


# ===========================================================================
# build_patient_options
# ===========================================================================


class TestBuildPatientOptions:
    def test_sets_data_folder_and_preserves_the_other_keys(self, tmp_path):
        options_path = tmp_path / "patient_options.json"
        options_path.write_text(
            json.dumps(
                {
                    "data_folder": "/stale/folder/from/another/machine",
                    "quick_load": True,
                    "eit": {"day": "2004-09-15"},
                }
            ),
            encoding="utf-8",
        )
        # A str options path, so the Path() coercion the signature promises is load-bearing here.
        options = build_patient_options("/patients/007", str(options_path))
        assert options["data_folder"] == "/patients/007"
        assert options["quick_load"] is True
        assert options["eit"] == {"day": "2004-09-15"}

    def test_without_an_options_path_only_data_folder_is_set(self):
        assert build_patient_options("/patients/007") == {"data_folder": "/patients/007"}

    def test_a_path_folder_is_stored_as_text(self, tmp_path):
        """patient_options is JSON-bound, so the folder is serialised on the way in."""
        assert build_patient_options(tmp_path)["data_folder"] == str(tmp_path)


# ===========================================================================
# load_options — forgiving where load_database_options_from_path is strict
# ===========================================================================


class TestLoadOptions:
    def test_reads_an_existing_json_file(self, tmp_path):
        path = tmp_path / "options.json"
        path.write_text(json.dumps({"quick_load": True}), encoding="utf-8")
        assert load_options(path) == {"quick_load": True}

    def test_none_path_returns_empty_dict(self):
        assert load_options(None) == {}

    def test_missing_file_is_forgiven_here_and_fatal_in_the_database_loader(self, tmp_path):
        """An absent options file is optional; a config the caller named by path is not."""
        absent = tmp_path / "absent.json"
        assert load_options(absent) == {}
        with pytest.raises(FileNotFoundError):
            load_database_options_from_path(absent)
