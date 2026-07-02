"""
Tests for is_junk_file() and folder_has_real_content().

These back the junk-filtering used by find_files() (no-extension branch) and the
patient-folder preview in the UI, which needs to tell an intentionally-empty
datasource folder from one holding real data.
"""

from pathlib import Path

from clinical_scope.io.file_utils import folder_has_real_content, is_junk_file


def create(tmp_path: Path, *names: str) -> list[Path]:
    """Touch files and return their paths in the same order."""
    paths = []
    for name in names:
        p = tmp_path / name
        p.touch()
        paths.append(p)
    return paths


class TestIsJunkFile:
    def test_real_data_filenames_not_junk(self):
        assert not is_junk_file(Path("data.csv"))
        assert not is_junk_file(Path("waveforms.parquet"))

    def test_dotfiles_are_junk(self):
        for name in [".DS_Store", ".gitkeep", "._AppleDouble", ".Trash-1000"]:
            assert is_junk_file(Path(name)), name

    def test_windows_junk_names_are_junk(self):
        for name in ["Thumbs.db", "desktop.ini", "System Volume Information", "$RECYCLE.BIN"]:
            assert is_junk_file(Path(name)), name


class TestFolderHasRealContent:
    def test_empty_folder_no_real_content(self, tmp_path):
        assert not folder_has_real_content(tmp_path)

    def test_only_junk_files_no_real_content(self, tmp_path):
        create(tmp_path, ".DS_Store", ".gitkeep")
        assert not folder_has_real_content(tmp_path)

    def test_junk_plus_real_file_has_real_content(self, tmp_path):
        create(tmp_path, ".DS_Store", "data.csv")
        assert folder_has_real_content(tmp_path)

    def test_subfolder_alone_not_real_content(self, tmp_path):
        """find_files() never recurses, so a bare subfolder isn't usable data."""
        (tmp_path / "archive").mkdir()
        assert not folder_has_real_content(tmp_path)

    def test_subfolder_with_files_inside_still_not_real_content(self, tmp_path):
        """Nested files aren't seen either — matches find_files()'s non-recursive scan."""
        sub = tmp_path / "archive"
        sub.mkdir()
        (sub / "data.csv").touch()
        assert not folder_has_real_content(tmp_path)
