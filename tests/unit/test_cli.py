"""
Cover the ``clinical-scope`` console script: the argument surface a terminal user meets.

Both things the parser can reach are replaced here — the download, and the Dash app, which is
built at import time and so must never be imported by a test.
"""

import sys
import types

import pytest

from clinical_scope import cli
from clinical_scope.demo_data import DemoDownloadError

DOWNLOAD_FOLDER_NAME = "example"


@pytest.fixture
def fetched(monkeypatch, tmp_path):
    """Stand in for the download; returns the list of ``force`` values it was called with."""
    calls: list[bool] = []

    def fake_fetch(*, force=False):
        calls.append(force)
        folder = tmp_path / DOWNLOAD_FOLDER_NAME
        folder.mkdir(exist_ok=True)
        return folder

    monkeypatch.setattr(cli, "fetch_demo_data", fake_fetch)
    return calls


@pytest.fixture
def failing_fetch(monkeypatch):
    def fake_fetch(*, force=False):
        raise DemoDownloadError("could not reach the release")

    monkeypatch.setattr(cli, "fetch_demo_data", fake_fetch)


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

    def test_demo_does_not_start_the_dashboard(self, fetched, dashboard, capsys):
        cli.main(["--demo"])

        assert dashboard == []


class TestDemoOutput:
    """The printed paths are the only instructions a pip user gets; they must be the real ones."""

    def test_it_prints_the_two_paths_the_app_asks_for(self, fetched, tmp_path, capsys):
        exit_code = cli.main(["--demo"])

        printed = capsys.readouterr().out
        demo = tmp_path / DOWNLOAD_FOLDER_NAME / "demo_database"
        assert exit_code == 0
        assert str(demo / "demo_patient") in printed
        assert str(demo / "database_options.json") in printed

    def test_force_reaches_the_download(self, fetched):
        cli.main(["--demo", "--force"])

        assert fetched == [True]

    def test_without_force_the_download_may_reuse_what_is_there(self, fetched):
        cli.main(["--demo"])

        assert fetched == [False]

    def test_a_failed_download_is_a_message_not_a_traceback(self, failing_fetch, capsys):
        exit_code = cli.main(["--demo"])

        assert exit_code == 1
        assert "could not reach the release" in capsys.readouterr().err


class TestForceIsRefusedOnItsOwn:
    """Accepting ``--force`` without ``--demo`` would silently do nothing."""

    def test_force_without_demo_exits_with_usage(self, dashboard, capsys):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--force"])

        assert exit_info.value.code == 2
        assert "--force" in capsys.readouterr().err

    def test_force_without_demo_does_not_start_the_dashboard(self, dashboard):
        with pytest.raises(SystemExit):
            cli.main(["--force"])

        assert dashboard == []
