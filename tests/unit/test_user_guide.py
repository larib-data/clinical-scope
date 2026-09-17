"""Unit tests for the target of the in-app Docs link, and for serving a bundled guide."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from flask import Flask

from clinical_scope.dash_api import user_guide


def _fake_bundle(monkeypatch, root: Path, *, with_pdf: bool) -> None:
    """Make the process look like a PyInstaller bundle whose root is ``root``."""
    executable = root / "ClinicalScope"
    executable.write_bytes(b"")
    if with_pdf:
        (root / "ClinicalScope_UserGuide.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))


def _running(monkeypatch, version: str) -> None:
    monkeypatch.setattr(user_guide, "running_version", lambda: version)


# ---------------------------------------------------------------------------
# Finding a guide on disk
# ---------------------------------------------------------------------------


class TestBundledGuidePath:
    def test_nothing_outside_a_bundle(self, monkeypatch):
        """A checkout's PDF is a per-release artifact, so it is not the guide of what runs."""
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert user_guide.bundled_guide_path() is None

    def test_finds_the_pdf_beside_the_executable(self, monkeypatch, tmp_path):
        _fake_bundle(monkeypatch, tmp_path, with_pdf=True)
        found = user_guide.bundled_guide_path()
        assert found is not None
        assert found.name == "ClinicalScope_UserGuide.pdf"
        assert found.read_bytes() == b"%PDF-1.4 fake"

    def test_nothing_when_the_bundle_lacks_its_pdf(self, monkeypatch, tmp_path):
        """The asset copy only warns when it fails, so the app must survive a bundle without it."""
        _fake_bundle(monkeypatch, tmp_path, with_pdf=False)
        assert user_guide.bundled_guide_path() is None


# ---------------------------------------------------------------------------
# Choosing the href
# ---------------------------------------------------------------------------


class TestDocsHref:
    def test_a_bundled_guide_is_served_by_the_app(self, tmp_path):
        assert user_guide.docs_href(tmp_path / "ClinicalScope_UserGuide.pdf") == "/user-guide"

    def test_a_bundled_guide_wins_over_the_running_version(self, monkeypatch, tmp_path):
        """The shipped PDF describes this build exactly, and reaching it costs no network."""
        _running(monkeypatch, "1.3.1")
        assert user_guide.docs_href(tmp_path / "ClinicalScope_UserGuide.pdf") == "/user-guide"

    def test_a_release_install_reads_its_own_version(self, monkeypatch):
        _running(monkeypatch, "1.2.0")
        assert user_guide.docs_href(None) == (
            "https://github.com/larib-data/clinical-scope/blob/v1.2.0/docs/user_guide/user_guide.md"
        )

    def test_a_later_release_reads_that_one(self, monkeypatch):
        _running(monkeypatch, "2.10.3")
        assert user_guide.docs_href(None) == (
            "https://github.com/larib-data/clinical-scope/blob/v2.10.3/docs/user_guide/user_guide.md"
        )

    @pytest.mark.parametrize(
        "running",
        ["dev (unknown version)", "1.3.1.dev0", "1.4.0rc1", "1.3", "v1.3.0", ""],
    )
    def test_anything_without_a_tag_falls_back_to_the_default_branch(self, monkeypatch, running):
        """Naming a ref we never published would be a 404, which is worse than a newer guide."""
        _running(monkeypatch, running)
        assert user_guide.docs_href(None) == (
            "https://github.com/larib-data/clinical-scope/blob/main/docs/user_guide/user_guide.md"
        )

    def test_surrounding_whitespace_still_pins(self, monkeypatch):
        _running(monkeypatch, " 1.3.1 ")
        assert user_guide.docs_href(None) == (
            "https://github.com/larib-data/clinical-scope/blob/v1.3.1/docs/user_guide/user_guide.md"
        )

    def test_never_points_at_a_release_asset(self, monkeypatch):
        """The bug being fixed: GitHub serves release assets as attachments, so they download."""
        _running(monkeypatch, "1.3.1")
        assert "releases/latest/download" not in user_guide.docs_href(None)


# ---------------------------------------------------------------------------
# Serving the bundled PDF
# ---------------------------------------------------------------------------


class TestGuideRoute:
    @staticmethod
    def _response(tmp_path):
        pdf = tmp_path / "ClinicalScope_UserGuide.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        server = Flask(__name__)
        user_guide.register_guide_route(server, pdf)
        return server.test_client().get("/user-guide")

    def test_serves_the_file_it_was_given(self, tmp_path):
        response = self._response(tmp_path)
        assert response.status_code == 200
        assert response.data == b"%PDF-1.4 fake"

    def test_serves_it_as_a_pdf(self, tmp_path):
        assert self._response(tmp_path).mimetype == "application/pdf"

    def test_serves_it_inline(self, tmp_path):
        """Inline is the whole point: a misclick costs a tab, not a file in Downloads."""
        disposition = self._response(tmp_path).headers.get("Content-Disposition", "")
        assert "attachment" not in disposition
