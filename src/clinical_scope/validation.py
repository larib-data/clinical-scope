"""The one type every ``database_options`` validator returns."""

from typing import Literal, NamedTuple


class ValidationIssue(NamedTuple):
    """
    One problem found in a config file: where it is, how bad it is, what to do.

    A leaf of its own so a plot type's ``schema.py`` can report issues without importing
    the parser that collects them -- the parser reaches every schema, so the reverse edge
    would close a cycle.
    """

    severity: Literal["error", "warning", "info"]
    path: str
    message: str
