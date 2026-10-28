"""What every ``database_options`` validator returns, and how it is reported."""

import logging
from typing import Literal, NamedTuple

_SEVERITY_LOG_LEVELS = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
}


class ValidationIssue(NamedTuple):
    """
    One problem found in a config file: where it is, how bad it is, what to do.

    A leaf of its own so a plot type's ``definition.py`` can report issues without importing
    the parser that collects them -- the parser reaches every plot type, so the reverse edge
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


def log_database_options_issues(issues: list[ValidationIssue], logger: logging.Logger) -> None:
    """
    Report every issue at the level its severity names.

    *logger* belongs to the caller: each tier that validates a config keeps its own name on
    the records, which a module-level logger here would silently rewrite to this one.
    ``stacklevel`` carries the rest of that origin -- the frame emitting the record now sits
    in this module, while a reader of the log wants the tier that found the issue. A severity
    the table does not name reports at INFO: ``severity`` binds type-checkers, not runtime.
    """
    for issue in issues:
        logger.log(
            _SEVERITY_LOG_LEVELS.get(issue.severity, logging.INFO),
            "database_options [%s]: %s",
            issue.path,
            issue.message,
            stacklevel=2,
        )
