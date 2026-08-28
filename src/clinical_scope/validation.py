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

    @classmethod
    def unknown_keys(
        cls, path: str, found: set[str], known: frozenset[str] | set[str]
    ) -> "ValidationIssue":
        """
        A block carrying keys the app does not know: a warning, since the rest still applies.

        One phrasing for every tier -- a datasource section, a signal, a trace block, a plot
        type's entry -- so a reader who has seen the message once recognises it anywhere.
        """
        return cls(
            severity="warning",
            path=path,
            message=f"Unknown keys: {sorted(found)}. Expected: {sorted(known)}",
        )
