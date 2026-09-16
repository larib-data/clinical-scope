"""
Download the demo dataset that a ``pip`` install does not ship.

A source checkout has ``example/`` by definition and the standalone bundle carries a copy, so
this exists for the third channel only: a wheel packages ``src/`` and nothing else. The archive
is published as a release asset by ``build.yml``.

Deliberately free of Dash imports, like :mod:`clinical_scope.dash_api.version_check`: the whole
download is testable without an app fixture, and every failure leaves by one exception type so
callers never have to enumerate what the network can do.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


class DemoDownloadError(RuntimeError):
    """The demo dataset could not be fetched or unpacked. Carries a user-readable reason."""


def demo_folder() -> Path:
    """Where the demo lives once fetched — beside the other app state under the user's home."""
    return Path.home() / cst.CLINICAL_SCOPE_DIR_NAME / cst.DEMO_DIR_NAME


def fetch_demo_data(*, force: bool = False) -> Path:
    """
    Ensure the demo dataset is on disk and return its folder.

    A non-empty folder is left alone unless ``force``, so the command is safe to repeat and
    costs nothing the second time. Raises :class:`DemoDownloadError` for every failure.
    """
    destination = demo_folder()
    if not force and destination.is_dir() and any(destination.iterdir()):
        logger.info("Demo data already present at %s", destination)
        return destination

    archive = _download(cst.DEMO_ARCHIVE_URL)
    try:
        _extract(archive, destination)
    finally:
        archive.unlink(missing_ok=True)

    logger.info("Demo data extracted to %s", destination)
    return destination


def _download(url: str) -> Path:
    """Stream ``url`` to a temporary file, bounded in size, and return its path."""
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
    archive = Path(handle.name)
    try:
        # Scheme is fixed by the constant, so the URL cannot be steered elsewhere.
        with handle, urllib.request.urlopen(  # noqa: S310
            url, timeout=cst.DEMO_DOWNLOAD_TIMEOUT_SECONDS
        ) as response:
            received = 0
            while chunk := response.read(cst.DEMO_DOWNLOAD_CHUNK_BYTES):
                received += len(chunk)
                if received > cst.DEMO_MAX_ARCHIVE_BYTES:
                    raise DemoDownloadError(
                        f"the archive at {url} is larger than this version expects"
                    )
                handle.write(chunk)
    except DemoDownloadError:
        archive.unlink(missing_ok=True)
        raise
    except OSError as error:
        archive.unlink(missing_ok=True)
        # A release published without the asset looks exactly like being offline, so the
        # message names both rather than guessing which one happened.
        raise DemoDownloadError(
            f"could not reach {url} ({error}). Check your connection, or download the archive "
            "by hand from the latest release."
        ) from error
    return archive


def _extract(archive: Path, destination: Path) -> None:
    """
    Unpack ``archive`` into ``destination``, replacing whatever was there.

    Staged next door and moved into place at the end: an interrupted extraction must not leave
    a half-filled folder, which :func:`fetch_demo_data` would then read as already complete.
    """
    staging = destination.with_name(f"{destination.name}.part")
    shutil.rmtree(staging, ignore_errors=True)

    try:
        with zipfile.ZipFile(archive) as bundle:
            _reject_escaping_members(bundle.namelist())
            staging.mkdir(parents=True)
            bundle.extractall(staging)  # noqa: S202 -- members validated just above
    except (OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise DemoDownloadError(f"the downloaded archive could not be unpacked ({error})") from error

    shutil.rmtree(destination, ignore_errors=True)
    staging.rename(destination)


def _reject_escaping_members(names: list[str]) -> None:
    """Refuse any member that would write outside the destination (``..``, absolute, drive)."""
    escaping = [
        name
        for name in names
        if PurePosixPath(name).is_absolute()
        or ".." in PurePosixPath(name).parts
        or "\\" in name
        or (len(name) > 1 and name[1] == ":")
    ]
    if escaping:
        raise DemoDownloadError(f"the archive contains unsafe path(s): {sorted(escaping)}")
