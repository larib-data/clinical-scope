"""
Where the in-app Docs link points, and how a guide that ships with the app is served.

A standalone bundle already carries the user guide PDF beside its executable, so the app hands
that copy to the browser itself: it renders in a tab, writes nothing to disk and needs no
network. Every other install opens the guide rendered on GitHub, pinned to the running version
so an older install never reads documentation for features it does not have.

Deliberately free of Dash imports, like :mod:`clinical_scope.dash_api.version_check`: one
function decides the href, and it is testable without an app fixture.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from flask import send_file

import clinical_scope.constants as cst
from clinical_scope.dash_api.version_check import running_version

if TYPE_CHECKING:
    from flask import Flask, Response


def bundled_guide_path() -> Path | None:
    """
    The user guide PDF shipped with a frozen bundle, or ``None`` when the app has none.

    Only a bundle counts as having the guide on disk. A source checkout holds a PDF too, but it
    is a committed artifact rebuilt once per release, so on a working tree it describes an older
    app than the one running; the rendered Markdown is the honest answer there.
    """
    if not getattr(sys, "frozen", False):
        return None
    # PyInstaller puts the executable at the bundle root, which is where the assets are copied.
    candidate = Path(sys.executable).resolve().parent / cst.USER_GUIDE_PDF_NAME
    return candidate if candidate.is_file() else None


def docs_href(bundled_pdf: Path | None) -> str:
    """
    Where the Docs link points, given whatever guide the install has on disk.

    Without a local PDF the link names a git ref, and only an exact release has a tag to name:
    a source checkout or a dev build falls back to the default branch rather than a URL that
    would 404.
    """
    if bundled_pdf is not None:
        return cst.USER_GUIDE_ROUTE
    running = running_version().strip()
    ref = (
        cst.USER_GUIDE_RELEASE_REF.format(version=running)
        if re.fullmatch(cst.RELEASE_VERSION_PATTERN, running)
        else cst.USER_GUIDE_DEFAULT_REF
    )
    return cst.USER_GUIDE_PAGE_URL.format(ref=ref)


def register_guide_route(server: Flask, pdf_path: Path) -> None:
    """Serve ``pdf_path`` inline, so the browser renders the guide instead of saving it."""

    @server.route(cst.USER_GUIDE_ROUTE)
    def _serve_user_guide() -> Response:
        return send_file(
            pdf_path,
            mimetype=cst.USER_GUIDE_PDF_MIME_TYPE,
            as_attachment=False,
        )
