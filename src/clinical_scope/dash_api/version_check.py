"""
What the version badge should say: the running version, the newest published one, and the verdict.

Deliberately free of Dash imports. ``badge_content`` decides every case, so the callback that
renders it is a two-line adapter and the whole decision is testable without an app fixture.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from importlib.metadata import PackageNotFoundError, version

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


def running_version() -> str:
    """
    Version of the installed ``clinical_scope`` distribution, or a placeholder outside one.

    Editable installs report whatever was current when ``pip install -e .`` last ran; developers
    have the git tags for the real answer, so that staleness is not worth correcting here.
    """
    try:
        return version("clinical_scope")
    except PackageNotFoundError:
        return cst.UNKNOWN_VERSION_LABEL


def latest_released_version() -> str | None:
    """
    Newest version published to PyPI, or ``None`` when it cannot be read.

    Every failure is one return: offline, a proxy, a timeout, a changed payload shape. None is
    logged above debug, because the badge already shows the user what happened.
    """
    try:
        # Scheme is fixed by the constant, so the URL cannot be steered elsewhere.
        with urllib.request.urlopen(  # noqa: S310
            cst.PYPI_PROJECT_JSON_URL,
            timeout=cst.UPDATE_CHECK_TIMEOUT_SECONDS,
        ) as response:
            payload = json.load(response)
        latest = payload["info"]["version"]
    except (OSError, ValueError, KeyError, TypeError):
        logger.debug("Update check could not read the version from PyPI", exc_info=True)
        return None
    return str(latest)


def _as_release_tuple(candidate: str | None) -> tuple[int, ...] | None:
    """Split an exact ``X.Y.Z`` string into comparable integers; ``None`` for anything else."""
    match = re.fullmatch(cst.RELEASE_VERSION_PATTERN, candidate.strip()) if candidate else None
    return tuple(int(part) for part in match.groups()) if match else None


def newer_version(running: str, latest: str | None) -> str | None:
    """
    Return ``latest`` when it is a strictly newer release than ``running``, else ``None``.

    Either side failing to parse also returns ``None``: an unrecognised version is never grounds
    for telling someone they are behind. ``badge_content`` is what turns that silence into a
    plain link, since not knowing and being current are different answers.
    """
    running_parts = _as_release_tuple(running)
    latest_parts = _as_release_tuple(latest)
    if running_parts is None or latest_parts is None:
        return None
    return latest if latest_parts > running_parts else None


def _badge_text(running: str) -> str:
    return f"{cst.VERSION_BADGE_LABEL}{running}"


def initial_badge_text() -> str:
    """The badge as first served, before the check has anything to add to it."""
    return _badge_text(running_version())


def badge_content() -> tuple[str, str | None]:
    """
    The badge's text and the label of the link to append, ``None`` meaning no link.

    Four outcomes, and only one of them is link-free. Behind: the newer version is named. Unable
    to tell — the check failed, or the running version is not a release we recognise: the page is
    offered unnamed, because a link costs nothing and is where the answer is. Current: no link,
    so an up-to-date install is the quiet case rather than one more thing to read past.
    """
    running = running_version()
    latest = latest_released_version()
    text = _badge_text(running)

    if _as_release_tuple(running) is None or _as_release_tuple(latest) is None:
        logger.debug("Update check inconclusive (running %s, published %s)", running, latest)
        return text, cst.RELEASES_PAGE_LABEL

    newer = newer_version(running, latest)
    if newer is None:
        return text, None
    logger.info("Newer release available: %s (running %s)", newer, running)
    return text, cst.UPDATE_AVAILABLE_LABEL.format(version=newer)
