"""
Reading a datasource's files one at a time, naming the file in every failure.

A folder can hold dozens of recordings; an error that does not say which one broke leaves the
user bisecting the folder by hand.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

logger = logging.getLogger(__name__)

# A TypeVar, not PEP 695 syntax: that needs Python 3.12 and CI still runs 3.11.
T = TypeVar("T")


def read_one(path: Path, reader: Callable[[Path], T], source_name: str) -> T:  # noqa: UP047
    """Return ``reader(path)``, re-raising any failure as a ValueError naming the file."""
    try:
        return reader(path)
    except Exception as exc:
        msg = f"Cannot read {source_name} file '{path.name}': {exc}"
        raise ValueError(msg) from exc


def read_each(  # noqa: UP047
    paths: list[Path], reader: Callable[[Path], T | None], source_name: str
) -> list[tuple[Path, T]]:
    """
    Read every file in *paths*, pairing each with what *reader* returned for it.

    *reader* returns ``None`` for a file that parses but holds no data; that file is skipped
    with a warning. Only ``None`` skips: an empty result is the reader's to return, and stays.

    Raises:
        ValueError: naming the file, when *reader* fails on it; naming every file, when all
            of them were skipped.

    """
    results = []
    for path in paths:
        result = read_one(path, reader, source_name)
        if result is None:
            logger.warning("[%s] Skipping '%s': it holds no data.", source_name, path.name)
            continue
        results.append((path, result))
    if not results:
        names = ", ".join(path.name for path in paths)
        msg = f"None of the {len(paths)} {source_name} file(s) holds any data: {names}"
        raise ValueError(msg)
    return results
