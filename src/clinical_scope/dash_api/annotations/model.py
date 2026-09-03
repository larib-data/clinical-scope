"""
Annotation data model.

An Annotation represents a user-created mark on a plot: a time event (vertical
line), a time window (shaded rectangle), or a point (arrow + label).  It is
serialisable to a plain dict so it can be stored in a dcc.Store and written to JSON.

An AnnotationSet is an immutable collection of them, and a Group is a set of annotations
sharing a ``group_id``.  Groups are never persisted (see :mod:`.io`): a group exists only as
the annotations that carry its id, and its name, colour, type and scope are read off the
first of them.  That derivation is defined here, once, rather than at each call site.

Nothing here imports Dash: a callback hydrates the store's list of dicts into an
AnnotationSet, asks a question or produces a modified copy, and serialises back out.
The set itself is never stored — ``dcc.Store`` holds JSON only.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import clinical_scope.constants as cst

if TYPE_CHECKING:
    from collections.abc import Iterator


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
    "#999999",  # gray
    "#000000",  # black
    "#e74c3c",  # red
    "#3498db",  # blue
    "#2ecc71",  # green
    "#f39c12",  # amber
    "#9b59b6",  # purple
    "#1abc9c",  # teal
]


def normalize_hex_color(value: str | None) -> str:
    """
    Return `value` canonicalised to "#rrggbb", falling back to the first preset if malformed.

    The colour fields are free text, so a "#"-less paste is accepted and anything else malformed
    resolves to the default rather than reaching annotations.json verbatim.
    """
    candidate = (value or "").strip()
    if re.fullmatch(cst.HEX_COLOR_PATTERN, candidate):
        return f"#{candidate.lstrip('#').lower()}"
    return ANNOTATION_COLORS[0]


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
    group_name
        Display name of that group, denormalised onto every member so groups can be
        rebuilt from the annotations alone (group metadata is never persisted separately).
    trace_metadata
        ``{"datasource_name", "raw_name", "display_name"}`` of the clicked trace, or
        ``None``.  Records which signal the annotation was placed on.
    patient
        Patient identifier string set when loading annotations via
        :func:`~clinical_scope.load_database_annotations`.  ``None`` for
        annotations loaded individually.
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
    extra
        Keys present in the source dict that this class does not own, kept verbatim so a
        hand-written or externally generated ``annotations.json`` survives a round-trip
        through the app (ADR-0012).

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
    patient: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now_iso)
    extra: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        annotation_type: AnnotationType,
        plot_name: str,
        data: dict,
        is_global: bool = False,
        subplot_name: str | None = None,
        **kwargs,
    ) -> Annotation:
        """
        Build a *new* annotation, applying the creation-time defaults for its type.

        Deserialisation must not come through here: :meth:`from_dict` reproduces a stored
        annotation verbatim, so a point whose label the user explicitly un-hid loads back un-hidden.
        """
        if annotation_type is AnnotationType.POINT:
            # A point is anchored to one (x, y) inside a single subplot, so it can never be
            # global, and its label starts hidden so the dot marker alone shows.
            is_global = False
            kwargs.setdefault("label_hidden", True)
        return cls(
            type=annotation_type,
            plot_name=plot_name,
            data=data,
            subplot_name=None if is_global else subplot_name,
            **kwargs,
        )

    def to_dict(self) -> dict:
        """
        Serialise to a JSON-safe dict.

        Unowned keys go first so a known field can never be shadowed by a stale one in `extra`.
        """
        return {
            **self.extra,
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "color": self.color,
            "plot_name": self.plot_name,
            "subplot_name": self.subplot_name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "patient": self.patient,
            "data": self.data,
            "trace_metadata": self.trace_metadata,
            "label_hidden": self.label_hidden,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, annotation_dict: dict) -> Annotation:
        """Deserialise from a dict produced by :meth:`to_dict`."""
        return cls(
            id=annotation_dict.get("id") or str(uuid.uuid4()),
            type=AnnotationType(annotation_dict["type"]),
            label=annotation_dict.get("label", ""),
            color=annotation_dict.get("color", "#e74c3c"),
            plot_name=annotation_dict.get("plot_name", ""),
            subplot_name=annotation_dict.get("subplot_name"),
            group_id=annotation_dict.get("group_id"),
            group_name=annotation_dict.get("group_name"),
            patient=annotation_dict.get("patient"),
            data=annotation_dict.get("data", {}),
            trace_metadata=annotation_dict.get("trace_metadata"),
            label_hidden=annotation_dict.get("label_hidden", False),
            created_at=annotation_dict.get("created_at", _now_iso()),
            extra={
                key: value
                for key, value in annotation_dict.items()
                if key not in _OWNED_ANNOTATION_KEYS
            },
        )


# Derived from the dataclass rather than restated, so a promoted field stops landing in `extra`
# on its own.  `extra` itself is not a serialised key.
_OWNED_ANNOTATION_KEYS: frozenset[str] = frozenset(
    annotation_field.name for annotation_field in fields(Annotation)
) - {"extra"}


@dataclass(frozen=True)
class Group:
    """
    A set of annotations sharing a ``group_id``, plus the metadata derived from its first member.

    Always holds at least one annotation: a group with no members cannot be derived, and so
    cannot be represented.
    """

    id: str
    name: str
    color: str
    type: AnnotationType
    is_global: bool
    annotations: list[Annotation]

    @property
    def is_hidden(self) -> bool:
        """Whether every member's label is hidden — the state the group's eye icon shows."""
        return all(annotation.label_hidden for annotation in self.annotations)

    def __len__(self) -> int:
        return len(self.annotations)


class AnnotationSet:
    """An ordered, immutable collection of annotations. Every mutator returns a new set."""

    def __init__(self, annotations: list[Annotation] | tuple[Annotation, ...] = ()) -> None:
        self._annotations: tuple[Annotation, ...] = tuple(annotations)

    # ----------------------------------------------------------------------------------------
    # Boundaries
    # ----------------------------------------------------------------------------------------

    @classmethod
    def from_dicts(cls, annotation_dicts: list[dict] | None) -> AnnotationSet:
        """Hydrate from a ``dcc.Store`` payload, tolerating the ``None`` of an untouched store."""
        return cls([Annotation.from_dict(item) for item in (annotation_dicts or [])])

    def to_dicts(self) -> list[dict]:
        """Serialise back to a JSON-safe list for a ``dcc.Store`` payload."""
        return [annotation.to_dict() for annotation in self._annotations]

    @property
    def annotations(self) -> list[Annotation]:
        """The annotations, in order."""
        return list(self._annotations)

    def __iter__(self) -> Iterator[Annotation]:
        return iter(self._annotations)

    def __len__(self) -> int:
        return len(self._annotations)

    # ----------------------------------------------------------------------------------------
    # Derivation
    # ----------------------------------------------------------------------------------------

    def groups(self) -> list[Group]:
        """Derive the groups, in first-seen order, each carrying its members in creation order."""
        members: dict[str, list[Annotation]] = {}
        metadata: dict[str, Annotation] = {}
        for annotation in self._annotations:
            if not annotation.group_id:
                continue
            if annotation.group_id not in members:
                members[annotation.group_id] = []
                metadata[annotation.group_id] = annotation
            members[annotation.group_id].append(annotation)

        return [
            Group(
                id=group_id,
                name=first.group_name or "",
                color=first.color,
                type=first.type,
                is_global=first.subplot_name is None,
                annotations=members[group_id],
            )
            for group_id, first in metadata.items()
        ]

    def group(self, group_id: str) -> Group | None:
        """Return the group with this id, or ``None`` if no annotation carries it."""
        return next((group for group in self.groups() if group.id == group_id), None)

    def ungrouped(self) -> list[Annotation]:
        """Annotations belonging to no group, in order."""
        return [annotation for annotation in self._annotations if not annotation.group_id]

    # ----------------------------------------------------------------------------------------
    # Mutators — each returns a new set, leaving this one untouched
    # ----------------------------------------------------------------------------------------

    def with_added(self, annotation: Annotation) -> AnnotationSet:
        """Append an annotation to the end of the set."""
        return AnnotationSet([*self._annotations, annotation])

    def without(self, annotation_id: str) -> AnnotationSet:
        """Drop the annotation with this id."""
        return AnnotationSet(
            [annotation for annotation in self._annotations if annotation.id != annotation_id]
        )

    def without_group(self, group_id: str) -> AnnotationSet:
        """Drop every annotation belonging to this group."""
        return AnnotationSet(
            [annotation for annotation in self._annotations if annotation.group_id != group_id]
        )

    def with_label_toggled(self, annotation_id: str) -> AnnotationSet:
        """Flip ``label_hidden`` on the annotation with this id."""
        return AnnotationSet(
            [
                replace(annotation, label_hidden=not annotation.label_hidden)
                if annotation.id == annotation_id
                else annotation
                for annotation in self._annotations
            ]
        )

    def with_group_labels_toggled(self, group_id: str) -> AnnotationSet:
        """
        Flip a whole group's labels to the state its eye icon is not showing.

        Pairing the target with :attr:`Group.is_hidden` here is what keeps the icon and the
        button it sits on from drifting apart.
        """
        group = self.group(group_id)
        if group is None:
            return self
        target_hidden = not group.is_hidden
        return AnnotationSet(
            [
                replace(annotation, label_hidden=target_hidden)
                if annotation.group_id == group_id
                else annotation
                for annotation in self._annotations
            ]
        )

    def with_moved(
        self,
        annotation_id: str,
        *,
        data: dict,
        plot_name: str,
        subplot_name: str | None,
        trace_metadata: dict | None,
    ) -> AnnotationSet:
        """
        Re-place the annotation with this id, keeping everything that is not its position.

        Position, plot, scope and the trace it sits on are all re-derived from the new click, so a
        point dragged into another subplot takes that subplot's axis refs instead of reading its y
        off one scale and drawing it against another.

        A global annotation stays global: an absent ``subplot_name`` is a choice the user made in
        the creation modal, not a fact about coordinates, so re-deriving it would silently demote
        every global annotation the first time anyone nudged it.
        """
        return AnnotationSet(
            [
                replace(
                    annotation,
                    data=data,
                    plot_name=plot_name,
                    subplot_name=None if annotation.subplot_name is None else subplot_name,
                    trace_metadata=trace_metadata,
                )
                if annotation.id == annotation_id
                else annotation
                for annotation in self._annotations
            ]
        )
