"""Tests for read_each() — per-file reading that names the file on any failure."""

import logging
from pathlib import Path

import pytest

from clinical_scope.io.file_reading import read_each


def _read_text(path: Path) -> str | None:
    text = path.read_text()
    return None if text == "nothing" else text


class TestReadEach:
    def test_returns_each_path_with_its_result(self, tmp_path):
        first = tmp_path / "a.txt"
        second = tmp_path / "b.txt"
        first.write_text("one")
        second.write_text("two")

        assert read_each([first, second], _read_text, "demo") == [(first, "one"), (second, "two")]

    def test_reader_failure_is_raised_naming_the_file(self, tmp_path):
        good = tmp_path / "good.txt"
        good.write_text("one")
        missing = tmp_path / "broken_recording.txt"

        with pytest.raises(ValueError, match=r"Cannot read demo file 'broken_recording\.txt'"):
            read_each([good, missing], _read_text, "demo")

    def test_original_exception_is_chained(self, tmp_path):
        missing = tmp_path / "broken_recording.txt"

        with pytest.raises(ValueError) as excinfo:
            read_each([missing], _read_text, "demo")

        assert isinstance(excinfo.value.__cause__, FileNotFoundError)

    def test_none_result_is_skipped_with_a_warning(self, tmp_path, caplog):
        good = tmp_path / "good.txt"
        hollow = tmp_path / "hollow_recording.txt"
        good.write_text("one")
        hollow.write_text("nothing")

        with caplog.at_level(logging.WARNING):
            result = read_each([good, hollow], _read_text, "demo")

        assert result == [(good, "one")]
        assert "hollow_recording.txt" in caplog.text

    def test_all_none_raises_naming_the_files(self, tmp_path):
        first = tmp_path / "first_hollow.txt"
        second = tmp_path / "second_hollow.txt"
        first.write_text("nothing")
        second.write_text("nothing")

        with pytest.raises(ValueError, match=r"first_hollow\.txt, second_hollow\.txt"):
            read_each([first, second], _read_text, "demo")
