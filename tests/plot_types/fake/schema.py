"""Leaf half of a plot type that does not exist, used to prove a fourth one needs no edits.

Shaped deliberately unlike the real three: its config entry is a **bare string** naming one
signal, not a list and not a dict of options. Nothing in the shared modules has ever seen that
shape, so every hook it goes through is exercised on a case the real types do not cover.
"""

from collections.abc import Callable
from typing import Any

from clinical_scope.plot_types.base import PlotTypeSchema
from clinical_scope.validation import ValidationIssue


class FakeSchema(PlotTypeSchema):
    """A fourth plot type: one signal, redrawn. Capabilities match no real type on purpose."""

    NAME = "fake"
    SECTION_KEY = "fake"

    TIME_AXIS = True
    UNIFIED_HOVER = False
    RESAMPLED = False
    GRID_LAYOUT = True
    HAS_COLORBAR = False
    POINT_TIMESTAMPS = False

    SHEET_NAME = "fakes"
    SHEET_REQUIRED_COLUMNS = frozenset({"datasource", "fake_name", "signal"})

    @classmethod
    def validate_entry(cls, entry: Any, path: str) -> list[ValidationIssue]:
        if isinstance(entry, str) and entry:
            return []
        return [
            ValidationIssue(
                severity="error",
                path=path,
                message=f"Must be a signal name string, got {entry!r}",
            )
        ]

    @classmethod
    def map_refs(cls, config: Any, map_ref: Callable[[str], str]) -> Any:
        return map_ref(config) if isinstance(config, str) else config

    @classmethod
    def read_sheet(cls, rows: Any, cells: Any) -> dict[str, dict[str, Any]]:
        by_datasource: dict[str, dict[str, Any]] = {}
        for _, row in rows.iterrows():
            datasource = str(row.get("datasource", "")).strip()
            fake_name = str(row.get("fake_name", "")).strip()
            signal = str(row.get("signal", "")).strip()
            if any(cells.is_empty(value) for value in (datasource, fake_name, signal)):
                continue
            by_datasource.setdefault(datasource, {})[fake_name] = signal
        return by_datasource
