"""
Annotation data model.

An Annotation represents a user-created mark on a plot: a time event (vertical
line), a time window (shaded rectangle), or a point (arrow + label).

Each Annotation is serialisable to a plain dict so it can be stored in a
dcc.Store and written to JSON.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class AnnotationType(StrEnum):
    """Supported annotation types."""

    TIME_EVENT = "time_event"
    TIME_WINDOW = "time_window"
    POINT = "point"


# Types that require a datetime x-axis and cannot be placed on loop plots.
# Centralised here so the callback layer does not hard-code this invariant.
TIME_BASED_ANNOTATION_TYPES: frozenset[AnnotationType] = frozenset(
    {AnnotationType.TIME_EVENT, AnnotationType.TIME_WINDOW}
)


# Preset color palette offered in the creation modal
ANNOTATION_COLORS: list[str] = [
    "#e74c3c",  # red
    "#3498db",  # blue
    "#2ecc71",  # green
    "#f39c12",  # amber
    "#9b59b6",  # purple
    "#1abc9c",  # teal
]


@dataclass
class Annotation:
    """
    A single user annotation attached to a specific plot.

    Parameters
    ----------
    id
        Unique identifier (UUID string). Auto-generated if not provided.
    type
        Annotation type: time_event, time_window, or point.
    label
        Display label shown on the plot.
    color
        Hex color string (e.g. ``"#e74c3c"``).
    plot_name
        Name of the PlotModel this annotation belongs to (e.g. ``"time_series"``).
    subplot_name
        Title of the subplot this annotation targets.  ``None`` means global
        (all subplots).  Used by the renderer for stable, position-independent
        lookup: if the subplot is later removed the annotation is silently skipped.
    group_id
        ID of the annotation group this annotation belongs to, or ``None``.
    label_hidden
        When ``True``, the text label / arrow is not rendered.  For ``POINT``
        annotations this defaults to ``True`` so the dot marker shows without
        cluttering the plot.
    data
        Type-specific payload dict:

        * ``time_event``  - ``{"x": "<ISO timestamp>"}``
        * ``time_window`` - ``{"x0": "<ISO timestamp>", "x1": "<ISO timestamp>"}``
        * ``point``       - ``{"x": "<ISO timestamp or value>", "y": <float>,
                               "xaxis": "x", "yaxis": "y",
                               "t": "<ISO timestamp>"}``  — ``t`` is optional; present only
                               for loop-plot points where per-point timing is available.
    created_at
        ISO datetime string of creation time.

    """

    type: AnnotationType
    plot_name: str
    data: dict
    label: str = ""
    color: str = "#e74c3c"
    subplot_name: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    trace_metadata: dict | None = None
    label_hidden: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "color": self.color,
            "plot_name": self.plot_name,
            "subplot_name": self.subplot_name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "data": self.data,
            "trace_metadata": self.trace_metadata,
            "label_hidden": self.label_hidden,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Annotation:
        """Deserialise from a dict produced by :meth:`to_dict`."""
        return cls(
            id=d.get("id") or str(uuid.uuid4()),
            type=AnnotationType(d["type"]),
            label=d.get("label", ""),
            color=d.get("color", "#e74c3c"),
            plot_name=d.get("plot_name", ""),
            subplot_name=d.get("subplot_name"),
            group_id=d.get("group_id"),
            group_name=d.get("group_name"),
            data=d.get("data", {}),
            trace_metadata=d.get("trace_metadata"),
            label_hidden=d.get("label_hidden", False),
            created_at=d.get("created_at", _now_iso()),
        )
