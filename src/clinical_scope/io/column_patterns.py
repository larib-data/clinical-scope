"""
Resolving configured signal patterns against a file's actual column names.

A pattern is either a literal column name or a trailing-``*`` wildcard. Both consumers
share one definition of what ``*`` matches, so a pruned read can never select a different
set than the full read would.
"""

import logging
from collections.abc import Callable

import pandas as pd

import clinical_scope.constants as cst

logger = logging.getLogger(__name__)


def _wildcard_matches(pattern: str, columns: pd.Index | list[str]) -> list[str] | None:
    """
    Prefix-match *columns* for a trailing-``*`` wildcard; ``None`` if *pattern* is a literal.

    Single definition of what a ``*`` matches, shared by :func:`get_column_name_from_pattern`
    and :func:`_pruned_columns` so their wildcard handling can't drift. ``None`` (literal) is
    distinct from ``[]`` (wildcard with zero matches) — each caller handles literals its own way.
    """
    if not (pattern and pattern.endswith(cst.DatabaseOptions.WILDCARD_SUFFIX)):
        return None
    prefix = pattern.rstrip(cst.DatabaseOptions.WILDCARD_SUFFIX)
    return [column_name for column_name in columns if column_name.startswith(prefix)]


def get_column_name_from_pattern(columns: pd.Index | list[str], pattern: str) -> str | None:
    """Find a column name matching a pattern (supports wildcard suffix '*')."""
    matching_columns = _wildcard_matches(pattern, columns)
    if matching_columns is None:
        return pattern  # literal: assume the caller-supplied name is the column

    if len(matching_columns) == 1:
        return matching_columns[0]
    if len(matching_columns) == 0:
        logger.warning("No column found in dataframe from the pattern %s", pattern)
    else:
        logger.warning(
            "More than one column found in dataframe with the pattern %s. -> Ignored", pattern
        )
    return None


def _pruned_columns(field_display: list[str] | None, file_columns: list[str]) -> list[str] | None:
    """
    Resolve which parquet columns to read for a set of configured signal patterns.

    Pure column-name logic (no data read). Shares :func:`_wildcard_matches` with
    :func:`get_column_name_from_pattern`, so the result is by construction a superset of the
    columns that matcher finally selects — every 0/1/2+ match count, and thus every warning,
    is identical to a full read.

    - wildcard ``pre*`` → all file columns starting with ``pre`` (1)
    - literal → included iff present (an absent name in ``columns=`` would raise) (2)
    - *field_display* absent (``None``) → ``None`` ⇒ read all columns (3)
    """
    if field_display is None:  # (3)
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for pattern in field_display:
        matches = _wildcard_matches(pattern, file_columns)
        if matches is None:  # (2)
            matches = [pattern] if pattern in file_columns else []
        for name in matches:  # (1)
            if name not in seen:
                seen.add(name)
                selected.append(name)
    return selected


def make_column_selector(
    database_options_specific: dict | None,
) -> Callable[[list[str]], list[str] | None]:
    """
    Build a *select_columns* callable for :func:`read_parquet_pruned` from a datasource's options.

    Centralizes the ``field_display`` lookup shared by every parquet call site. The returned
    closure defers pattern resolution until the file's columns are known.
    """
    field_display = (database_options_specific or {}).get(cst.DatabaseOptions.FIELD_DISPLAY)
    return lambda file_columns: _pruned_columns(field_display, file_columns)
