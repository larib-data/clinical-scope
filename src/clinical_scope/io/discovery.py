"""
Locating a patient folder's datasource folders and the data files inside them.

Folder-level predicates identify which datasource a subfolder holds; ``find_files`` then
picks the file(s) to load inside one.
"""

import logging
import re
from pathlib import Path

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


def folder_name_matches_keywords(folder_name: str, keywords: list[str]) -> bool:
    """Check if *folder_name* contains every keyword (case-insensitive)."""
    name_lower = folder_name.lower()
    return all(keyword.lower() in name_lower for keyword in keywords)


_JUNK_FILENAME_RE = re.compile("|".join(cst.JUNK_FILENAME_PATTERNS))


def is_junk_file(path: Path) -> bool:
    """Return True if *path* is VCS/OS cruft or documentation (``.gitkeep``, ``readme.txt``)."""
    return bool(_JUNK_FILENAME_RE.match(path.name))


def folder_has_real_content(folder_path: Path) -> bool:
    """Return True if *folder_path* contains at least one non-junk file (not recursive)."""
    return any(entry.is_file() and not is_junk_file(entry) for entry in folder_path.iterdir())


def deduplicate_by_stem(files: list[Path], extensions: list[str]) -> list[Path]:
    """
    Keep one file per stem, preferring the extension earliest in *extensions*.

    A device folder routinely holds both a source export and a parquet written from it;
    loading both would duplicate every signal under colliding names.
    """
    suffix_rank = {extension.lower(): index for index, extension in enumerate(extensions)}
    max_rank = len(extensions)

    def rank(file: Path) -> int:
        return suffix_rank.get(file.suffix.lower(), max_rank)

    kept_by_stem: dict[str, Path] = {}
    for file in files:
        stem = file.stem.lower()
        incumbent = kept_by_stem.get(stem)
        if incumbent is None:
            kept_by_stem[stem] = file
            continue
        winner, shadowed = (file, incumbent) if rank(file) < rank(incumbent) else (incumbent, file)
        kept_by_stem[stem] = winner
        logger.info(
            "Ignoring '%s': '%s' already covers stem '%s'.", shadowed.name, winner.name, stem
        )
    return list(kept_by_stem.values())


def _drop_empty_files(files: list[Path], datasource_name: str, folder_path: Path) -> list[Path]:
    """
    Return *files* without the zero-byte ones, warning once per file dropped.

    Runs before any selection: an empty export must neither fail the folder nor shadow a
    same-stem sibling that holds the data.
    """
    kept = []
    for file in sorted(files):
        if file.stat().st_size == 0:
            logger.warning("[%s] Skipping empty file '%s'.", datasource_name, file.name)
        else:
            kept.append(file)
    if not kept:
        logger.warning(
            "%d %s files found in '%s', all empty.", len(files), datasource_name, folder_path
        )
    return kept


def find_files(
    folder_path: Path,
    extensions: list[str],
    datasource_name: str,
    *,
    multi: bool = False,
    keywords: list[str] | None = None,
) -> list[Path] | Path | None:
    """
    Find data files in *folder_path*.

    Zero-byte files are dropped first, in both modes, so they never count as a match; if every
    match was empty, return ``None`` (the caller's "no data here").

    When *multi* is ``True``, return **all** files matching *extensions*, deduplicated by
    stem and sorted alphabetically, or ``None`` if none found.

    When *multi* is ``False``, return a **single** file (tiered disambiguation):

    1. Collect non-empty files matching *extensions* (or all files if none given).
    2. If one match, return it.
    3. Deduplicate by stem: when multiple extensions exist for the same stem,
       keep the most preferred one (earliest in *extensions*).
    4. If one stem remains, return it.
    5. If *keywords* is given, try each keyword in order to narrow the set;
       return immediately if exactly one match remains.
    6. If *extensions* is given, narrow the set by the first prefered extension that is available
       in the files. Return directly if only one remains.
    6. Warn and return ``None`` if still ambiguous.
    """
    if multi:
        ext_set = {extension.lower() for extension in extensions}
        files = [
            file
            for file in folder_path.iterdir()
            if file.is_file() and file.suffix.lower() in ext_set
        ]
        if not files:
            logger.debug("Could not find any %s files in folder '%s'", datasource_name, folder_path)
            return None
        files = _drop_empty_files(files, datasource_name, folder_path)
        if not files:
            return None
        files = sorted(deduplicate_by_stem(files, extensions))
        logger.debug("Found %s: %s in folder %s", datasource_name, files, folder_path)
        return files

    # --- single-file mode ---
    if extensions:
        suffix_set = {extension.lower() for extension in extensions}
        matches = [
            file
            for file in folder_path.iterdir()
            if file.is_file() and file.suffix.lower() in suffix_set
        ]
    else:
        # No extension filter: all non-junk files are candidates.
        matches = [
            file for file in folder_path.iterdir() if file.is_file() and not is_junk_file(file)
        ]

    if not matches:
        logger.warning("No file for '%s' found in folder '%s'.", datasource_name, folder_path)
        return None

    matches = _drop_empty_files(matches, datasource_name, folder_path)
    if not matches:
        return None

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    if extensions:
        matches = deduplicate_by_stem(matches, extensions)

    if len(matches) == 1:
        logger.info("Selected file for '%s': %s", datasource_name, matches[0])
        return matches[0]

    # Keyword filtering on stem (ordered by preference)
    if keywords:
        for keyword in keywords:
            keyword_lower = keyword.lower()
            keyword_matches = [file for file in matches if keyword_lower in file.stem.lower()]
            if len(keyword_matches) == 1:
                logger.info(
                    "Selected file by keyword for '%s': %s", datasource_name, keyword_matches[0]
                )
                return keyword_matches[0]
            if keyword_matches:
                matches = keyword_matches

    if extensions:
        suffix_rank = {extension.lower(): index for index, extension in enumerate(extensions)}
        matches.sort(key=lambda file: suffix_rank.get(file.suffix.lower(), len(extensions)))
        if suffix_rank.get(matches[0].suffix.lower(), len(extensions)) < suffix_rank.get(
            matches[1].suffix.lower(), len(extensions)
        ):
            logger.info(
                "Selected file for '%s' by extension preference: %s", datasource_name, matches[0]
            )
            return matches[0]

    logger.warning(
        "Multiple '%s' files found in '%s', could not resolve a unique match: %s",
        datasource_name,
        folder_path,
        [file.name for file in matches],
    )
    return None
