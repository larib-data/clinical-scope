"""
Convert Annotation objects into Plotly ``layout.shapes`` / ``layout.annotations`` dicts.

Design notes
------------
* Time events and time windows default to ``yref="paper"`` so they span the
  full figure height (global).  When ``subplot_name`` is set the renderer
  resolves it to the matching row via ``subplot_rows`` and restricts the yref
  to that subplot's domain.  If the subplot no longer exists the annotation is
  silently skipped.
* Point annotations use a Plotly annotation with an arrowhead pointing at the
  data coordinate.  The ``yref`` targets the specific subplot y-axis so the
  arrow anchors correctly as the plot is zoomed.
* The x-axis reference is always ``"x"`` for time-series plots because all
  subplots share the same time axis.  Loop plots use the per-subplot xaxis
  stored in the annotation data.
* Subplot title annotations created by ``make_subplots`` live in
  ``layout.annotations`` alongside ours.  Callers must merge them; this module
  only produces the *annotation* portion.
* A ``hidden`` annotation produces nothing — no shape, no label, no point marker — and is
  skipped before its subplot is even resolved.  ``label_hidden`` is the narrower control,
  suppressing only the text.  This is the correctness boundary for hiding: whatever the
  caller passes in, a hidden annotation is never drawn.
"""

from __future__ import annotations

import dataclasses

from clinical_scope.dash_api.annotations.model import Annotation, AnnotationType
from clinical_scope.datasource.formatting.timezone import to_naive_display_ts

# ---------------------------------------------------------------------------
# Helper: axis reference strings
# ---------------------------------------------------------------------------


def _yref_paper_or_domain(subplot_yaxis: str | None) -> str:
    """
    Return the `yref` spanning either the full figure or one subplot.

    ``None`` (a global annotation) gives ``"paper"``; a subplot's primary yaxis ref
    ("y", "y3", …) gives that axis's domain.
    """
    if subplot_yaxis is None:
        return "paper"
    return f"{subplot_yaxis} domain"


# Sentinel returned by _resolve_subplot_yaxis when the subplot no longer exists.
_SUBPLOT_REMOVED = "-1"


def _resolve_subplot_yaxis(annotation: Annotation, subplot_rows: list[dict]) -> str | None:
    """
    Return the primary yaxis reference for an annotation's subplot.

    Returns
    -------
    None
        Annotation is global (``subplot_name`` is ``None``).
    str
        The yaxis reference string (e.g., "y", "y3") for the subplot.
    _SUBPLOT_REMOVED
        Subplot was removed — caller should skip this annotation.

    """
    if annotation.subplot_name is None:
        return None
    match = next((row for row in subplot_rows if row["name"] == annotation.subplot_name), None)
    if match is None:
        return _SUBPLOT_REMOVED
    return match.get("yaxis", None)


def _xref_for_annotation(annotation: Annotation) -> str:
    """Return the x-axis reference string for this annotation."""
    # Points store their xaxis explicitly; others default to the primary time axis.
    return annotation.data.get("xaxis", "x")


def _yref_for_point(annotation: Annotation) -> str:
    """Return the y-axis reference for a point annotation."""
    return annotation.data.get("yaxis", "y")


# ---------------------------------------------------------------------------
# Shape builders
# ---------------------------------------------------------------------------


def _time_event_shape(annotation: Annotation, subplot_yaxis: str | None) -> dict:
    x = annotation.data["x"]
    return {
        "type": "line",
        "x0": x,
        "x1": x,
        "y0": 0,
        "y1": 1,
        "xref": _xref_for_annotation(annotation),
        "yref": _yref_paper_or_domain(subplot_yaxis),
        "line": {"color": annotation.color, "width": 2, "dash": "dash"},
    }


def _time_window_shape(annotation: Annotation, subplot_yaxis: str | None) -> dict:
    return {
        "type": "rect",
        "x0": annotation.data["x0"],
        "x1": annotation.data["x1"],
        "y0": 0,
        "y1": 1,
        "xref": _xref_for_annotation(annotation),
        "yref": _yref_paper_or_domain(subplot_yaxis),
        "fillcolor": annotation.color,
        "opacity": 0.15,
        "line": {"width": 1, "color": annotation.color},
    }


# ---------------------------------------------------------------------------
# Plotly annotation builders (text labels)
# ---------------------------------------------------------------------------


def _time_event_label(annotation: Annotation, subplot_yaxis: str | None) -> dict | None:
    if not annotation.label:
        return None
    x = annotation.data["x"]
    yref = _yref_paper_or_domain(subplot_yaxis)
    # y is in [0, 1] for both paper and domain refs, so 0.99 pins the label to the top.
    return {
        "x": x,
        "y": 0.99,
        "xref": _xref_for_annotation(annotation),
        "yref": yref,
        "text": annotation.label,
        "showarrow": False,
        "xanchor": "left",
        "yanchor": "top",
        "bgcolor": annotation.color,
        "font": {"color": "white", "size": 11},
        "opacity": 0.9,
    }


def _time_window_label(annotation: Annotation, subplot_yaxis: str | None) -> dict | None:
    if not annotation.label:
        return None
    x = annotation.data["x0"]
    yref = _yref_paper_or_domain(subplot_yaxis)
    return {
        "x": x,
        "y": 0.99,
        "xref": _xref_for_annotation(annotation),
        "yref": yref,
        "text": annotation.label,
        "showarrow": False,
        "xanchor": "left",
        "yanchor": "top",
        "bgcolor": annotation.color,
        "font": {"color": "white", "size": 11},
        "opacity": 0.9,
    }


def _point_dot(annotation: Annotation) -> dict:
    """Minimal dot marker shown for a point when its label/arrow is hidden."""
    return {
        "x": annotation.data["x"],
        "y": annotation.data["y"],
        "xref": _xref_for_annotation(annotation),
        "yref": _yref_for_point(annotation),
        "text": "●",
        "showarrow": False,
        "font": {"color": annotation.color, "size": 12},
    }


def _point_label(annotation: Annotation) -> dict:
    return {
        "x": annotation.data["x"],
        "y": annotation.data["y"],
        "xref": _xref_for_annotation(annotation),
        "yref": _yref_for_point(annotation),
        "text": annotation.label or "•",
        "showarrow": True,
        "arrowhead": 2,
        "arrowsize": 1,
        "arrowwidth": 2,
        "arrowcolor": annotation.color,
        "ax": 0,
        "ay": -40,
        "font": {"color": annotation.color, "size": 12},
        "bgcolor": "rgba(255,255,255,0.85)",
        "bordercolor": annotation.color,
        "borderwidth": 1,
        "borderpad": 3,
    }


# ---------------------------------------------------------------------------
# Timezone normalization (tz-aware stored → naive display-TZ for Plotly)
# ---------------------------------------------------------------------------


def normalize_annotation_for_display(annotation: Annotation, display_tz: str) -> Annotation:
    """
    Return a copy of *annotation* with x values converted to naive display-TZ wall-clock strings.

    Trace x-data uses timezone-naive datetime64 (wall-clock in display TZ).  Annotation x
    values are stored as tz-aware ISO strings.  Converting here keeps rendering correct
    regardless of the UTC offset and is idempotent for already-naive values.
    """
    data = dict(annotation.data)
    if annotation.type == AnnotationType.TIME_EVENT:
        if "x" in data:
            data["x"] = to_naive_display_ts(data["x"], display_tz)
    elif annotation.type == AnnotationType.TIME_WINDOW:
        if "x0" in data:
            data["x0"] = to_naive_display_ts(data["x0"], display_tz)
        if "x1" in data:
            data["x1"] = to_naive_display_ts(data["x1"], display_tz)
    elif annotation.type == AnnotationType.POINT and "x" in data:
        # time-series POINT: x is a timestamp; loop POINT: x is numeric (unchanged by to_naive)
        data["x"] = to_naive_display_ts(data["x"], display_tz)
    return dataclasses.replace(annotation, data=data)


# ---------------------------------------------------------------------------
# Preview shape (pending time-window first click)
# ---------------------------------------------------------------------------


def make_preview_shape(x: str, xref: str = "x") -> dict:
    """Return a thin dotted line used as a visual preview for the first click of a time window."""
    return {
        "type": "line",
        "x0": x,
        "x1": x,
        "y0": 0,
        "y1": 1,
        "xref": xref,
        "yref": "paper",
        "line": {"color": "#aaaaaa", "width": 1, "dash": "dot"},
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def annotation_to_shapes(annotation: Annotation, subplot_yaxis: str | None) -> list[dict]:
    """
    Convert an `Annotation` to zero or more Plotly shape dicts.

    Points are rendered purely as Plotly annotations (arrows), so they produce no shapes.
    """
    if annotation.type == AnnotationType.TIME_EVENT:
        return [_time_event_shape(annotation, subplot_yaxis)]
    if annotation.type == AnnotationType.TIME_WINDOW:
        return [_time_window_shape(annotation, subplot_yaxis)]
    return []


def annotation_to_plotly_annotation(
    annotation: Annotation, subplot_yaxis: str | None
) -> dict | None:
    """
    Convert an `Annotation` to a single Plotly annotation dict (text label / arrow).

    Returns ``None`` when there is nothing to show.
    """
    if annotation.type == AnnotationType.TIME_EVENT:
        return _time_event_label(annotation, subplot_yaxis)
    if annotation.type == AnnotationType.TIME_WINDOW:
        return _time_window_label(annotation, subplot_yaxis)
    if annotation.type == AnnotationType.POINT:
        return _point_label(annotation)
    return None


def build_figure_overlays(
    annotations: list[Annotation],
    plot_name: str,
    subplot_annotations: list[dict],
    subplot_rows: list[dict] = (),
    pending_x0: str | None = None,
    pending_xref: str = "x",
) -> tuple[list[dict], list[dict]]:
    """
    Build the complete ``layout.shapes`` and ``layout.annotations`` lists for one plot.

    Parameters
    ----------
    annotations
        All annotations (filtered here to this ``plot_name``, and to those not ``hidden``).
        Callers must pre-normalise their timestamps to naive display-TZ wall-clock strings via
        :func:`normalize_annotation_for_display`.
    plot_name
        Name of the target PlotModel.
    subplot_annotations
        The original ``layout.annotations`` produced by ``make_subplots``
        (subplot titles).  These are prepended so they are never lost.
    subplot_rows
        Dicts from the graph-subplots store, used to resolve ``annotation.subplot_name`` to the
        subplot's yaxis ref.  Annotations whose subplot no longer exists are silently skipped.
    pending_x0
        If set, a grey preview line is added at this x position.  Must already
        be a naive display-TZ string if it represents a datetime.
    pending_xref
        x-axis reference for the preview line.

    Returns
    -------
    shapes, annotations
        Two lists ready to assign to ``figure.layout``.

    """
    relevant = [candidate for candidate in annotations if candidate.plot_name == plot_name]

    shapes: list[dict] = []
    our_annotations: list[dict] = []

    for annotation in relevant:
        # Ahead of the subplot lookup, so a hidden group of any size costs nothing to render.
        if annotation.hidden:
            continue
        yaxis = _resolve_subplot_yaxis(annotation, subplot_rows)
        if yaxis == _SUBPLOT_REMOVED:
            continue
        shapes.extend(annotation_to_shapes(annotation, yaxis))

        label_hidden = annotation.label_hidden

        if annotation.type == AnnotationType.POINT:
            # Dot marker always visible (mirrors time-event bar always appearing).
            our_annotations.append(_point_dot(annotation))
            if not label_hidden:
                our_annotations.append(_point_label(annotation))
        elif not label_hidden:
            label = annotation_to_plotly_annotation(annotation, yaxis)
            if label is not None:
                our_annotations.append(label)

    if pending_x0 is not None:
        shapes.append(make_preview_shape(pending_x0, xref=pending_xref))

    return shapes, subplot_annotations + our_annotations
