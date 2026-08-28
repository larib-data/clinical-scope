"""Leaf half of the ``loop`` plot type: one signal plotted against another, over time."""

import logging
from collections.abc import Callable
from typing import Any

from clinical_scope.plot_types.base import PlotTypeDefinition
from clinical_scope.validation import ValidationIssue

logger = logging.getLogger(__name__)

LOOP_REFERENCE_COUNT = 2


class LoopDefinition(PlotTypeDefinition):
    """
    A loop plots one signal's values against another's, e.g. a pressure-volume loop.

    Its x is a signal, not time, so it shares none of the time-series axis behaviour -- but
    every drawn point still knows when it was recorded, which is what the time slider and a
    point annotation's timestamp are read from.

    Its config entry is the odd one out: a bare ``[x_signal, y_signal]`` list rather than a
    dict of options, so it has no KNOWN_KEYS to check against.
    """

    NAME = "loop"
    SECTION_KEY = "loop"

    TIME_AXIS = False
    UNIFIED_HOVER = False
    RESAMPLED = False
    GRID_LAYOUT = True
    POINT_TIMESTAMPS = True

    SHEET_NAME = "loops"
    SHEET_REQUIRED_COLUMNS = frozenset({"datasource", "loop_name", "x_signal", "y_signal"})

    @classmethod
    def validate_entry(cls, entry: Any, path: str) -> list[ValidationIssue]:
        """A loop is exactly two signal names -- the pair *is* the plot."""
        if not isinstance(entry, (list, tuple)):
            return [
                ValidationIssue(
                    severity="error",
                    path=path,
                    message=(
                        f"Must be a list of {LOOP_REFERENCE_COUNT} signal names, "
                        f"got {type(entry).__name__}"
                    ),
                )
            ]
        if len(entry) != LOOP_REFERENCE_COUNT:
            return [
                ValidationIssue(
                    severity="error",
                    path=path,
                    message=(
                        f"Must name exactly {LOOP_REFERENCE_COUNT} signals "
                        f"(x then y), got {len(entry)}"
                    ),
                )
            ]
        return [
            ValidationIssue(
                severity="error",
                path=f"{path}[{index}]",
                message=f"Must be a signal name string, got {reference!r}",
            )
            for index, reference in enumerate(entry)
            if not isinstance(reference, str) or not reference
        ]

    @classmethod
    def map_refs(cls, config: Any, map_ref: Callable[[str], str]) -> Any:
        if not isinstance(config, (list, tuple)):
            return config
        return [map_ref(reference) for reference in config]

    @classmethod
    def read_sheet(cls, rows: Any, cells: Any) -> dict[str, dict[str, Any]]:
        by_datasource: dict[str, dict[str, Any]] = {}
        for row_idx, row in rows.iterrows():
            try:
                datasource = cells.text(row, "datasource")
                loop_name = cells.text(row, "loop_name")
                x_signal = cells.text(row, "x_signal")
                y_signal = cells.text(row, "y_signal")

                if any(
                    cells.is_empty(value) for value in (datasource, loop_name, x_signal, y_signal)
                ):
                    continue

                by_datasource.setdefault(datasource, {})[loop_name] = [x_signal, y_signal]
            except Exception:
                logger.warning(
                    "Skipping loops row %s due to unexpected error.", row_idx, exc_info=True
                )
        return by_datasource
