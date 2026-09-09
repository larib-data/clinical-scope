"""Unit tests for the release check behind the version badge."""

import io
import json
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError

import pytest

from clinical_scope.dash_api import version_check


def _urlopen_returning(body: bytes):
    """Stand in for urlopen, which the checker opens as a context manager."""

    @contextmanager
    def _fake(url, timeout):
        yield io.BytesIO(body)

    return _fake


def _urlopen_raising(error: Exception):
    def _fake(url, timeout):
        raise error

    return _fake


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class TestNewerVersion:
    @pytest.mark.parametrize(
        ("running", "latest"),
        [("1.2.0", "1.3.0"), ("1.2.0", "2.0.0"), ("1.2.3", "1.2.4"), ("2.0.0", "10.0.0")],
    )
    def test_reports_a_strictly_newer_release(self, running, latest):
        assert version_check.newer_version(running, latest) == latest

    def test_double_digit_minor_beats_single_digit(self):
        """The trap a string comparison falls into: '1.10.0' sorts before '1.9.0'."""
        assert version_check.newer_version("1.9.0", "1.10.0") == "1.10.0"

    @pytest.mark.parametrize(
        ("running", "latest"),
        [("1.2.0", "1.2.0"), ("1.3.0", "1.2.0"), ("2.0.0", "1.99.99")],
    )
    def test_silent_when_not_behind(self, running, latest):
        assert version_check.newer_version(running, latest) is None

    def test_silent_without_a_published_version(self):
        """None is what a failed lookup returns, and it must flow through as 'no notice'."""
        assert version_check.newer_version("1.2.0", None) is None

    @pytest.mark.parametrize(
        "running",
        ["0.0.0-dev (not installed)", "1.2.0.dev0", "1.2", "v1.2.0", ""],
    )
    def test_unparseable_running_version_stays_quiet(self, running):
        """A source checkout, or a scheme we do not publish, is never told it is behind."""
        assert version_check.newer_version(running, "9.9.9") is None

    @pytest.mark.parametrize("latest", ["1.3.0rc1", "1.3", "not-a-version"])
    def test_unparseable_published_version_stays_quiet(self, latest):
        """A pre-release reaching PyPI must not push the whole user base towards it."""
        assert version_check.newer_version("1.2.0", latest) is None


# ---------------------------------------------------------------------------
# Reading PyPI
# ---------------------------------------------------------------------------


class TestLatestReleasedVersion:
    def test_reads_the_version_from_the_pypi_payload(self, monkeypatch):
        body = json.dumps({"info": {"version": "1.3.0"}, "releases": {}}).encode()
        monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(body))
        assert version_check.latest_released_version() == "1.3.0"

    @pytest.mark.parametrize("error", [OSError("offline"), TimeoutError("too slow")])
    def test_network_failure_is_silent(self, monkeypatch, error):
        """Offline use is supported, so a failed check costs nothing but a debug line."""
        monkeypatch.setattr("urllib.request.urlopen", _urlopen_raising(error))
        assert version_check.latest_released_version() is None

    @pytest.mark.parametrize("body", [b"not json at all", b"{}", b'{"info": {}}'])
    def test_unexpected_payload_is_silent(self, monkeypatch, body):
        """The payload shape is PyPI's to change; a surprise must degrade, not raise."""
        monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(body))
        assert version_check.latest_released_version() is None


# ---------------------------------------------------------------------------
# Running version
# ---------------------------------------------------------------------------


class TestRunningVersion:
    def test_reads_the_installed_distribution(self):
        assert version_check.running_version()

    def test_placeholder_outside_an_install_never_compares(self, monkeypatch):
        """Asserting the property rather than the literal: whatever it is, it must not parse."""

        def _raise(_name):
            raise PackageNotFoundError

        monkeypatch.setattr(version_check, "version", _raise)
        assert version_check.newer_version(version_check.running_version(), "9.9.9") is None


# ---------------------------------------------------------------------------
# Badge content
# ---------------------------------------------------------------------------


class TestBadgeContent:
    """The four outcomes. Only a confirmed-current install gets no link."""

    @staticmethod
    def _answers(monkeypatch, running, latest):
        monkeypatch.setattr(version_check, "running_version", lambda: running)
        monkeypatch.setattr(version_check, "latest_released_version", lambda: latest)

    def test_behind_names_the_newer_version(self, monkeypatch):
        self._answers(monkeypatch, "1.2.0", "1.3.0")
        assert version_check.badge_content() == ("API Version: 1.2.0", "| 1.3.0 available ↗")

    @pytest.mark.parametrize(
        ("running", "latest"),
        [("1.3.0", "1.3.0"), ("1.4.0", "1.3.0")],
    )
    def test_current_or_ahead_gets_no_link(self, monkeypatch, running, latest):
        self._answers(monkeypatch, running, latest)
        assert version_check.badge_content() == (f"API Version: {running}", None)

    def test_unreachable_pypi_still_offers_the_page(self, monkeypatch):
        """A link costs nothing, and the release page is where the answer is."""
        self._answers(monkeypatch, "1.2.0", None)
        assert version_check.badge_content() == ("API Version: 1.2.0", "| releases ↗")

    def test_unparseable_published_version_still_offers_the_page(self, monkeypatch):
        self._answers(monkeypatch, "1.2.0", "1.3.0rc1")
        assert version_check.badge_content() == ("API Version: 1.2.0", "| releases ↗")

    def test_unknown_running_version_says_so_and_offers_the_page(self, monkeypatch):
        """A source checkout is told what it is, not that it is behind something."""
        self._answers(monkeypatch, "dev (unknown version)", "1.3.0")
        text, link = version_check.badge_content()
        assert text == "API Version: dev (unknown version)"
        assert link == "| releases ↗"


# ---------------------------------------------------------------------------
# Badge rendering
# ---------------------------------------------------------------------------


class TestBadgeCallback:
    """The callback is a two-line adapter; these cover only the two shapes it returns."""

    @staticmethod
    def _module(monkeypatch, content):
        from clinical_scope.dash_api.callbacks import version_callbacks

        monkeypatch.setattr(version_callbacks, "badge_content", lambda: content)
        return version_callbacks

    def test_plain_text_when_there_is_no_link(self, monkeypatch):
        module = self._module(monkeypatch, ("API Version: 1.3.0", None))
        assert module.annotate_version_badge(1) == "API Version: 1.3.0"

    def test_links_to_the_release_page(self, monkeypatch):
        module = self._module(monkeypatch, ("API Version: 1.2.0", "| 1.3.0 available ↗"))
        text, link = module.annotate_version_badge(1)
        assert text == "API Version: 1.2.0"
        assert link.children == "| 1.3.0 available ↗"
        assert link.href == "https://github.com/larib-data/clinical-scope/releases/latest"
        assert link.target == "_blank"
