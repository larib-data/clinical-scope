"""
Cover the ``clinical-scope`` console script: the argument surface a terminal user meets.

The Dash app is stubbed wherever the parser could reach it: it builds its layout at import
time, so a test must never import the real thing. Nothing else here needs a stub — ``--demo``
only prints, which is the property most of these tests are about.
"""

import sys
import types
from pathlib import Path

import pytest

from clinical_scope import cli

DEMO_ARCHIVE_URL = (
    "https://github.com/larib-data/clinical-scope/releases/latest/download/"
    "clinical-scope-example.zip"
)


@pytest.fixture
def dashboard(monkeypatch):
    """A stub ``core_api`` in ``sys.modules``, so launching never builds a real Dash app."""
    launches: list[bool] = []
    module = types.ModuleType("clinical_scope.dash_api.core_api")
    module.main = lambda: launches.append(True)
    monkeypatch.setitem(sys.modules, "clinical_scope.dash_api.core_api", module)
    return launches


class TestLaunching:
    """A bare invocation is still the ordinary way in."""

    def test_no_arguments_starts_the_dashboard(self, dashboard):
        assert cli.main([]) == 0
        assert dashboard == [True]

    def test_demo_does_not_start_the_dashboard(self, dashboard):
        cli.main(["--demo"])

        assert dashboard == []


class TestDemoOutput:
    """The printed link and paths are the only instructions a pip user gets."""

    def test_it_prints_the_download_link(self, capsys):
        exit_code = cli.main(["--demo"])

        assert exit_code == 0
        assert DEMO_ARCHIVE_URL in capsys.readouterr().out

    def test_it_prints_the_two_paths_the_app_asks_for(self, capsys):
        cli.main(["--demo"])

        printed = capsys.readouterr().out
        assert "clinical-scope-example/demo_database/demo_patient" in printed
        assert "clinical-scope-example/demo_database/database_options.json" in printed

    def test_the_paths_sit_inside_the_folder_the_archive_unpacks_to(self, capsys):
        # The archive holds one top-level folder; a path printed without it would not exist.
        cli.main(["--demo"])

        for line in capsys.readouterr().out.splitlines():
            if "demo_database" in line:
                assert "clinical-scope-example/demo_database" in line


class TestDemoWritesNothing:
    """The whole point of the change: a link to read, not a folder the user cannot find."""

    def test_demo_touches_neither_the_home_folder_nor_the_working_directory(
        self, monkeypatch, tmp_path
    ):
        home = tmp_path / "home"
        working = tmp_path / "working"
        home.mkdir()
        working.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.chdir(working)

        assert cli.main(["--demo"]) == 0
        assert list(home.rglob("*")) == []
        assert list(working.rglob("*")) == []


class TestForceIsGone:
    """``--force`` only ever meant re-download, and nothing downloads any more."""

    def test_force_is_no_longer_a_flag(self, dashboard, capsys):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--demo", "--force"])

        assert exit_info.value.code == 2
        assert "--force" in capsys.readouterr().err
        assert dashboard == []

    def test_help_does_not_advertise_it(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--help"])

        helped = capsys.readouterr().out
        assert exit_info.value.code == 0
        assert "--force" not in helped
        assert "--demo" in helped
