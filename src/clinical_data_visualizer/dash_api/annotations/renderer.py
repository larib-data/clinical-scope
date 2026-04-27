"""
Convert Annotation objects into Plotly ``layout.shapes`` and ``layout.annotations`` dicts ready to be assigned to a figure.

Design notes
------------
* Time events and time windows default to ``yref="paper"`` so they span the
  full figure height (global).  When ``subplot_row`` is set the yref is
  restricted to that subplot's domain.
* Point annotations use a Plotly annotation with an arrowhead pointing at the
  data coordinate.  The ``yref`` targets the specific subplot y-axis so the
  arrow anchors correctly as the plot is zoomed.
* The x-axis reference is always ``"x"`` for time-series plots because all
  subplots share the same time axis.  Loop plots use the per-subplot xaxis
  stored in the annotation data.
* Subplot title annotations created by ``make_subplots`` live in
  ``layout.annotations`` alongside ours.  Callers must merge them; this module
  only produces the *annotation* portion.
"""  # noqa: E501

from __future__ import annotations

from clinical_data_visualizer.dash_api.annotations.model import Annotation, AnnotationType

# ---------------------------------------------------------------------------
# Helper: axis reference strings
# ---------------------------------------------------------------------------


def _yref_paper_or_domain(subplot_row: int | None, n_cols: int = 1) -> str:
    """
    Return the right `yref` for a shape that should span either the full figure or a single subplot.

    Plotly numbers y-axes sequentially across the grid: for an n_cols layout,
    the first y-axis of row r is at index (r-1)*n_cols + 1.  Domain refs use
    ``"y domain"`` for axis 1 and ``"y<n> domain"`` for n > 1.
    """
    if subplot_row is None:
        return "paper"
    axis_idx = (subplot_row - 1) * n_cols + 1
    axis_num = "" if axis_idx == 1 else str(axis_idx)
    return f"y{axis_num} domain"


def _xref_for_annotation(ann: Annotation) -> str:
    """Return the x-axis reference string for this annotation."""
    # Points store their xaxis explicitly; others default to the primary time axis.
    return ann.data.get("xaxis", "x")


def _yref_for_point(ann: Annotation) -> str:
    """Return the y-axis reference for a point annotation."""
    return ann.data.get("yaxis", "y")


# ---------------------------------------------------------------------------
# Shape builders
# ---------------------------------------------------------------------------


def _time_event_shape(ann: Annotation, n_cols: int = 1) -> dict:
    x = ann.data["x"]
    return {
        "type": "line",
        "x0": x,
        "x1": x,
        "y0": 0,
        "y1": 1,
        "xref": _xref_for_annotation(ann),
        "yref": _yref_paper_or_domain(ann.subplot_row, n_cols),
        "line": {"color": ann.color, "width": 2, "dash": "dash"},
    }


def _time_window_shape(ann: Annotation, n_cols: int = 1) -> dict:
    return {
        "type": "rect",
        "x0": ann.data["x0"],
        "x1": ann.data["x1"],
        "y0": 0,
        "y1": 1,
        "xref": _xref_for_annotation(ann),
        "yref": _yref_paper_or_domain(ann.subplot_row, n_cols),
        "fillcolor": ann.color,
        "opacity": 0.15,
        "line": {"width": 1, "color": ann.color},
    }


# ---------------------------------------------------------------------------
# Plotly annotation builders (text labels)
# ---------------------------------------------------------------------------


def _time_event_label(ann: Annotation, n_cols: int = 1) -> dict | None:
    if not ann.label:
        return None
    x = ann.data["x"]
    yref = _yref_paper_or_domain(ann.subplot_row, n_cols)
    # For paper yref the y coordinate is in [0, 1]; for domain refs also [0, 1].
    return {
        "x": x,
        "y": 0.99,
        "xref": _xref_for_annotation(ann),
        "yref": yref,
        "text": ann.label,
        "showarrow": False,
        "xanchor": "left",
        "yanchor": "top",
        "bgcolor": ann.color,
        "font": {"color": "white", "size": 11},
        "opacity": 0.9,
    }


def _time_window_label(ann: Annotation, n_cols: int = 1) -> dict | None:
    if not ann.label:
        return None
    # Place label at the left edge of the window near the top.
    x = ann.data["x0"]
    yref = _yref_paper_or_domain(ann.subplot_row, n_cols)
    return {
        "x": x,
        "y": 0.99,
        "xref": _xref_for_annotation(ann),
        "yref": yref,
        "text": ann.label,
        "showarrow": False,
        "xanchor": "left",
        "yanchor": "top",
        "bgcolor": ann.color,
        "font": {"color": "white", "size": 11},
        "opacity": 0.9,
    }


def _point_label(ann: Annotation) -> dict:
    return {
        "x": ann.data["x"],
        "y": ann.data["y"],
        "xref": _xref_for_annotation(ann),
        "yref": _yref_for_point(ann),
        "text": ann.label or "•",
        "showarrow": True,
        "arrowhead": 2,
        "arrowsize": 1,
        "arrowwidth": 2,
        "arrowcolor": ann.color,
        "ax": 0,
        "ay": -40,
        "font": {"color": ann.color, "size": 12},
        "bgcolor": "rgba(255,255,255,0.85)",
        "bordercolor": ann.color,
        "borderwidth": 1,
        "borderpad": 3,
    }


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


def annotation_to_shapes(ann: Annotation, n_cols: int = 1) -> list[dict]:
    """
    Convert an custom class `Annotation` to zero or more Plotly shape dicts.

    Points are rendered purely as Plotly annotations (arrows), so they
    produce no shapes.
    """
    if ann.type == AnnotationType.TIME_EVENT:
        return [_time_event_shape(ann, n_cols)]
    if ann.type == AnnotationType.TIME_WINDOW:
        return [_time_window_shape(ann, n_cols)]
    # POINT — no shape needed, handled by annotation arrow
    return []


def annotation_to_plotly_annotation(ann: Annotation, n_cols: int = 1) -> dict | None:
    """
    Convert an custom class `Annotation` to a single Plotly annotation dict (textlabel / arrow).

    Returns ``None`` when there is nothing to show.
    """
    if ann.type == AnnotationType.TIME_EVENT:
        return _time_event_label(ann, n_cols)
    if ann.type == AnnotationType.TIME_WINDOW:
        return _time_window_label(ann, n_cols)
    if ann.type == AnnotationType.POINT:
        return _point_label(ann)
    return None


def build_figure_overlays(
    annotations: list[Annotation],
    plot_name: str,
    subplot_annotations: list[dict],
    pending_x0: str | None = None,
    pending_xref: str = "x",
    n_cols: int = 1,
) -> tuple[list[dict], list[dict]]:
    """
    Build figure overlay from the annotations and plot name.

    Build the complete ``layout.shapes`` and ``layout.annotations`` lists for one plot, merging
    subplot title annotations with user annotations.

    Parameters
    ----------
    annotations
        All annotations (will be filtered to this ``plot_name``).
    plot_name
        Name of the target PlotModel.
    subplot_annotations
        The original ``layout.annotations`` produced by ``make_subplots``
        (subplot titles).  These are prepended so they are never lost.
    pending_x0
        If set, a grey preview line is added at this x position.
    pending_xref
        x-axis reference for the preview line.

    Returns
    -------
    shapes, annotations
        Two lists ready to assign to ``figure.layout``.

    """
    relevant = [a for a in annotations if a.plot_name == plot_name]

    shapes: list[dict] = []
    our_annotations: list[dict] = []

    for ann in relevant:
        shapes.extend(annotation_to_shapes(ann, n_cols))
        label = annotation_to_plotly_annotation(ann, n_cols)
        if label is not None:
            our_annotations.append(label)

    if pending_x0 is not None:
        shapes.append(make_preview_shape(pending_x0, xref=pending_xref))

    return shapes, subplot_annotations + our_annotations
